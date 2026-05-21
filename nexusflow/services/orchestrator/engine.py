from __future__ import annotations

import asyncio
import logging
import socket
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.database import get_db
from nexusflow.shared.models.task import (
    AgentType,
    EventType,
    ExecutionEvent,
    Task,
    TaskStatus,
)
from nexusflow.shared.queue.redis_streams import (
    STREAM_TASK_ASSIGNED,
    STREAM_TASK_COMPLETED,
    STREAM_TASK_FAILED,
    STREAM_TASK_PLANNED,
    STREAM_STREAMING_EVENTS,
    RedisConnectionPool,
    RedisStreamConsumer,
    RedisStreamProducer,
)
from nexusflow.services.orchestrator.repository import TaskRepository
from nexusflow.services.orchestrator.state_machine import (
    StateTransitionError,
    compute_task_status,
    transition_subtask,
    transition_task,
)

logger = logging.getLogger(__name__)


class OrchestratorEngine:
    """Central async DAG execution loop."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._worker_id = f"orchestrator-{socket.gethostname()}"
        self._active_tasks: Dict[str, Task] = {}
        self._concurrency_sem = asyncio.Semaphore(
            self._settings.orchestrator.max_concurrent_subtasks
        )
        self._event_seq = 0
        self._producer: Optional[RedisStreamProducer] = None
        self._consumer: Optional[RedisStreamConsumer] = None
        self._running = False
        self._inflight_subtasks: Set[str] = set()

    async def start(self) -> None:
        redis = await RedisConnectionPool.get()
        self._producer = RedisStreamProducer(redis)
        self._consumer = RedisStreamConsumer(
            client=redis,
            group_name=self._settings.redis.consumer_group,
            consumer_name=self._worker_id,
            streams=[
                STREAM_TASK_PLANNED,
                STREAM_TASK_COMPLETED,
                STREAM_TASK_FAILED,
            ],
        )
        self._running = True
        logger.info("Orchestrator started: %s", self._worker_id)

        await asyncio.gather(
            self._consume_loop(),
            self._scheduling_loop(),
            self._heartbeat_loop(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            self._consumer.stop()
        logger.info("Orchestrator stopping: %s", self._worker_id)

    async def _consume_loop(self) -> None:
        async for stream_name, msg_id, data in self._consumer.read_messages():
            try:
                await self._handle_message(stream_name, data)
                await self._consumer.ack(stream_name, msg_id)
            except Exception as e:
                logger.error(
                    "Failed to process message %s on %s: %s",
                    msg_id, stream_name, str(e), exc_info=True
                )

    async def _handle_message(self, stream: str, data: dict) -> None:
        if stream == STREAM_TASK_PLANNED:
            await self._on_task_planned(data)
        elif stream == STREAM_TASK_COMPLETED:
            await self._on_subtask_completed(data)
        elif stream == STREAM_TASK_FAILED:
            await self._on_subtask_failed(data)

    async def _on_task_planned(self, data: dict) -> None:
        import json
        task_data = data.get("task") or data
        if isinstance(task_data, str):
            task_data = json.loads(task_data)

        task = Task.model_validate(task_data)
        self._active_tasks[task.id] = task
        logger.info(
            "Task %s loaded into orchestrator (%d subtasks)",
            task.id, len(task.subtasks)
        )
        await self._emit_event(
            task_id=task.id,
            event_type=EventType.TASK_STARTED,
            payload={"subtask_count": len(task.subtasks)},
        )

    async def _on_subtask_completed(self, data: dict) -> None:
        subtask_id = data.get("subtask_id")
        task_id = data.get("task_id")
        output_data = data.get("output_data", {})

        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning("Received completion for unknown task %s", task_id)
            return

        subtask = task.get_subtask(subtask_id)
        if not subtask:
            logger.warning("Received completion for unknown subtask %s", subtask_id)
            return

        try:
            transition_subtask(subtask, TaskStatus.COMPLETED)
        except StateTransitionError as e:
            logger.error("State transition error: %s", e)
            return

        subtask.output_data = output_data
        subtask.completed_at = datetime.now(timezone.utc)
        subtask.tokens_used = data.get("tokens_used", 0)
        subtask.estimated_cost_usd = data.get("cost_usd", 0.0)
        self._inflight_subtasks.discard(subtask_id)
        task.update_aggregates()

        await self._emit_event(
            task_id=task_id,
            subtask_id=subtask_id,
            event_type=EventType.SUBTASK_COMPLETED,
            payload={"output_preview": str(output_data)[:200]},
        )

        async with get_db() as session:
            repo = TaskRepository(session)
            await repo.update_subtask(subtask)

        new_task_status = compute_task_status(task)
        if new_task_status == TaskStatus.COMPLETED:
            await self._complete_task(task)
        elif new_task_status == TaskStatus.FAILED:
            await self._fail_task(task, "One or more subtasks failed irrecoverably")

    async def _on_subtask_failed(self, data: dict) -> None:
        subtask_id = data.get("subtask_id")
        task_id = data.get("task_id")
        error = data.get("error_message", "Unknown error")
        traceback = data.get("error_traceback", "")

        task = self._active_tasks.get(task_id)
        if not task:
            return

        subtask = task.get_subtask(subtask_id)
        if not subtask:
            return

        subtask.error_message = error
        subtask.error_traceback = traceback
        subtask.retry_count += 1
        self._inflight_subtasks.discard(subtask_id)

        if subtask.can_retry:
            try:
                transition_subtask(subtask, TaskStatus.RETRYING)
            except StateTransitionError:
                pass

            delay = subtask.retry_policy.compute_delay(subtask.retry_count)
            logger.info(
                "Subtask %s will retry (attempt %d) after %.2fs",
                subtask_id, subtask.retry_count + 1, delay
            )
            await self._emit_event(
                task_id=task_id,
                subtask_id=subtask_id,
                event_type=EventType.SUBTASK_RETRYING,
                payload={"retry_count": subtask.retry_count, "delay": delay},
            )
            asyncio.create_task(self._requeue_subtask_after(subtask, delay))
        else:
            try:
                transition_subtask(subtask, TaskStatus.DLQ)
            except StateTransitionError:
                pass
            logger.error(
                "Subtask %s sent to DLQ after %d attempts",
                subtask_id, subtask.retry_count
            )
            await self._emit_event(
                task_id=task_id,
                subtask_id=subtask_id,
                event_type=EventType.SUBTASK_DLQ,
                payload={"error": error, "retry_count": subtask.retry_count},
            )
            async with get_db() as session:
                repo = TaskRepository(session)
                await repo.update_subtask(subtask)
            await self._fail_task(task, f"Subtask {subtask_id} exceeded max retries")

    async def _scheduling_loop(self) -> None:
        while self._running:
            await asyncio.sleep(0.5)
            for task_id, task in list(self._active_tasks.items()):
                if task.is_complete or task.has_failures:
                    continue
                ready = task.get_ready_subtasks()
                for subtask in ready:
                    if subtask.id not in self._inflight_subtasks:
                        asyncio.create_task(self._dispatch_subtask(task, subtask))

    async def _dispatch_subtask(self, task: Task, subtask) -> None:
        async with self._concurrency_sem:
            if subtask.id in self._inflight_subtasks:
                return

            self._inflight_subtasks.add(subtask.id)
            try:
                transition_subtask(subtask, TaskStatus.QUEUED)
            except StateTransitionError:
                self._inflight_subtasks.discard(subtask.id)
                return

            subtask.queued_at = datetime.now(timezone.utc)

            assignment_payload = {
                "task_id": task.id,
                "subtask_id": subtask.id,
                "agent_type": subtask.agent_type.value,
                "priority": subtask.priority.value,
                "input_data": subtask.input_data,
                "retry_count": subtask.retry_count,
                "retry_policy": subtask.retry_policy.model_dump(),
            }

            await self._producer.publish(STREAM_TASK_ASSIGNED, assignment_payload)
            await self._emit_event(
                task_id=task.id,
                subtask_id=subtask.id,
                event_type=EventType.SUBTASK_QUEUED,
                payload={"agent_type": subtask.agent_type.value},
            )
            logger.debug(
                "Dispatched subtask %s → %s", subtask.id, subtask.agent_type.value
            )

    async def _requeue_subtask_after(self, subtask, delay: float) -> None:
        await asyncio.sleep(delay)
        subtask.status = TaskStatus.PENDING
        self._inflight_subtasks.discard(subtask.id)

    async def _complete_task(self, task: Task) -> None:
        try:
            transition_task(task, TaskStatus.COMPLETED)
        except StateTransitionError:
            pass
        task.completed_at = datetime.now(timezone.utc)
        task.update_aggregates()
        self._active_tasks.pop(task.id, None)

        async with get_db() as session:
            repo = TaskRepository(session)
            await repo.update_status(task.id, TaskStatus.COMPLETED)

        await self._emit_event(
            task_id=task.id,
            event_type=EventType.TASK_COMPLETED,
            payload={
                "total_tokens": task.total_tokens_used,
                "total_cost_usd": task.total_cost_usd,
                "subtask_count": len(task.subtasks),
            },
        )
        logger.info("Task %s completed successfully", task.id)

    async def _fail_task(self, task: Task, reason: str) -> None:
        try:
            transition_task(task, TaskStatus.FAILED)
        except StateTransitionError:
            pass
        self._active_tasks.pop(task.id, None)

        async with get_db() as session:
            repo = TaskRepository(session)
            await repo.update_status(task.id, TaskStatus.FAILED)

        await self._emit_event(
            task_id=task.id,
            event_type=EventType.TASK_FAILED,
            payload={"reason": reason},
        )
        logger.error("Task %s failed: %s", task.id, reason)

    async def _emit_event(
        self,
        task_id: str,
        event_type: EventType,
        payload: dict = None,
        subtask_id: str = None,
        agent_type: AgentType = None,
    ) -> None:
        self._event_seq += 1
        event = ExecutionEvent(
            event_type=event_type,
            task_id=task_id,
            subtask_id=subtask_id,
            agent_type=agent_type,
            worker_id=self._worker_id,
            payload=payload or {},
            sequence_number=self._event_seq,
        )
        await self._producer.publish_event(
            STREAM_STREAMING_EVENTS, event.model_dump(mode="json")
        )
        try:
            async with get_db() as session:
                repo = TaskRepository(session)
                await repo.append_event(event)
        except Exception as e:
            logger.warning("Failed to persist event %s: %s", event.id, e)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(
                self._settings.orchestrator.heartbeat_interval_seconds
            )
            logger.info(
                "Orchestrator heartbeat | active_tasks=%d inflight_subtasks=%d",
                len(self._active_tasks),
                len(self._inflight_subtasks),
            )
