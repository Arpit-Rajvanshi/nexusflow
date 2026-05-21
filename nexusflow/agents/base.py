from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.task import AgentType, Subtask, TaskStatus
from nexusflow.shared.observability.logging import bind_task_context, clear_task_context
from nexusflow.shared.queue.redis_streams import (
    STREAM_AGENT_HEARTBEAT,
    STREAM_STREAMING_EVENTS,
    STREAM_TASK_ASSIGNED,
    STREAM_TASK_COMPLETED,
    STREAM_TASK_FAILED,
    RedisConnectionPool,
    RedisStreamConsumer,
    RedisStreamProducer,
)
from nexusflow.services.planner.llm_client import LLMClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all NexusFlow agents."""

    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        ...

    def __init__(self) -> None:
        self._settings = get_settings()
        pid = os.getpid()
        hostname = socket.gethostname()
        self._worker_id = f"{self.agent_type.value}-{hostname}-{pid}"
        self._llm = LLMClient()
        self._running = False
        self._producer: Optional[RedisStreamProducer] = None
        self._consumer: Optional[RedisStreamConsumer] = None
        self._tasks_processed = 0
        self._tasks_failed = 0

    @abstractmethod
    async def execute(self, subtask: Subtask) -> Dict[str, Any]:
        """Execute the subtask and return the output dict."""
        ...

    async def start(self) -> None:
        redis = await RedisConnectionPool.get()
        self._producer = RedisStreamProducer(redis)
        self._consumer = RedisStreamConsumer(
            client=redis,
            group_name=f"{self._settings.redis.consumer_group}-{self.agent_type.value}",
            consumer_name=self._worker_id,
            streams=[STREAM_TASK_ASSIGNED],
            batch_size=5,
        )
        self._running = True
        logger.info(
            "Agent started: %s (worker_id=%s)", self.agent_type.value, self._worker_id
        )
        await asyncio.gather(
            self._consume_loop(),
            self._heartbeat_loop(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            self._consumer.stop()

    async def _consume_loop(self) -> None:
        async for stream_name, msg_id, data in self._consumer.read_messages():
            assigned_agent = data.get("agent_type")
            if assigned_agent != self.agent_type.value:
                await self._consumer.ack(stream_name, msg_id)
                continue

            task_id = data.get("task_id", "")
            subtask_id = data.get("subtask_id", "")
            bind_task_context(task_id, subtask_id)

            try:
                await self._process_assignment(data)
                await self._consumer.ack(stream_name, msg_id)
                self._tasks_processed += 1
            except Exception as e:
                logger.error(
                    "Agent %s failed to process assignment: %s",
                    self._worker_id, str(e), exc_info=True
                )
                self._tasks_failed += 1
            finally:
                clear_task_context()

    async def _process_assignment(self, data: dict) -> None:
        from nexusflow.shared.models.task import RetryPolicy, AgentType as AT, Priority

        subtask = Subtask(
            id=data["subtask_id"],
            task_id=data["task_id"],
            name=data.get("name", "subtask"),
            description=data.get("description", ""),
            agent_type=AT(data["agent_type"]),
            priority=Priority(data.get("priority", 5)),
            input_data=data.get("input_data", {}),
            retry_count=data.get("retry_count", 0),
            retry_policy=RetryPolicy(**(data.get("retry_policy") or {})),
        )
        subtask.status = TaskStatus.RUNNING
        subtask.started_at = datetime.now(timezone.utc)
        subtask.assigned_worker_id = self._worker_id

        await self._publish_log(
            subtask, f"[{self.agent_type.value}] Starting execution"
        )

        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.execute(subtask),
                timeout=self._settings.orchestrator.task_timeout_seconds,
            )
            duration = time.monotonic() - start_time
            subtask.completed_at = datetime.now(timezone.utc)

            tokens_used = result.pop("_tokens_used", 0)
            cost_usd = result.pop("_cost_usd", 0.0)

            await self._publish_completed(subtask, result, tokens_used, cost_usd)
            logger.info(
                "Subtask %s completed in %.2fs (tokens=%d)",
                subtask.id, duration, tokens_used
            )

        except asyncio.TimeoutError:
            logger.error("Subtask %s timed out after %ds", subtask.id,
                         self._settings.orchestrator.task_timeout_seconds)
            await self._publish_failed(subtask, "Execution timed out", "TimeoutError")
            raise

        except Exception as e:
            tb = traceback.format_exc()
            await self._publish_failed(subtask, str(e), tb)
            raise

    async def _publish_completed(
        self, subtask: Subtask, output: dict, tokens: int, cost: float
    ) -> None:
        assert self._producer is not None
        await self._producer.publish(
            STREAM_TASK_COMPLETED,
            {
                "task_id": subtask.task_id,
                "subtask_id": subtask.id,
                "worker_id": self._worker_id,
                "output_data": output,
                "tokens_used": tokens,
                "cost_usd": cost,
            },
        )

    async def _publish_failed(
        self, subtask: Subtask, error: str, traceback_str: str
    ) -> None:
        assert self._producer is not None
        await self._producer.publish(
            STREAM_TASK_FAILED,
            {
                "task_id": subtask.task_id,
                "subtask_id": subtask.id,
                "worker_id": self._worker_id,
                "error_message": error,
                "error_traceback": traceback_str[:2000],
            },
        )

    async def _publish_log(self, subtask: Subtask, message: str) -> None:
        assert self._producer is not None
        from nexusflow.shared.models.task import EventType, ExecutionEvent
        event = ExecutionEvent(
            event_type=EventType.AGENT_LOG,
            task_id=subtask.task_id,
            subtask_id=subtask.id,
            agent_type=self.agent_type,
            worker_id=self._worker_id,
            payload={"message": message},
            is_partial=True,
        )
        await self._producer.publish_event(
            STREAM_STREAMING_EVENTS, event.model_dump(mode="json")
        )

    async def _publish_partial_output(
        self, subtask: Subtask, partial_text: str
    ) -> None:
        assert self._producer is not None
        from nexusflow.shared.models.task import EventType, ExecutionEvent
        event = ExecutionEvent(
            event_type=EventType.AGENT_PARTIAL_OUTPUT,
            task_id=subtask.task_id,
            subtask_id=subtask.id,
            agent_type=self.agent_type,
            worker_id=self._worker_id,
            payload={"text": partial_text},
            is_partial=True,
        )
        await self._producer.publish_event(
            STREAM_STREAMING_EVENTS, event.model_dump(mode="json")
        )

    async def _heartbeat_loop(self) -> None:
        interval = self._settings.orchestrator.heartbeat_interval_seconds
        while self._running:
            await asyncio.sleep(interval)
            if self._producer:
                await self._producer.publish(
                    STREAM_AGENT_HEARTBEAT,
                    {
                        "worker_id": self._worker_id,
                        "agent_type": self.agent_type.value,
                        "tasks_processed": self._tasks_processed,
                        "tasks_failed": self._tasks_failed,
                    },
                )
