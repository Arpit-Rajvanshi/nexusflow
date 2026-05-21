from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexusflow.shared.models.database import get_db
from nexusflow.shared.models.db import (
    AgentMetricRecord,
    ExecutionEventRecord,
    SubtaskRecord,
    TaskRecord,
)
from nexusflow.shared.models.task import (
    AgentType,
    ExecutionEvent,
    Priority,
    RetryPolicy,
    Subtask,
    Task,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class TaskRepository:
    """Database access layer for tasks, subtasks, and events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        record = _task_to_record(task)
        self._session.add(record)
        await self._session.flush()
        logger.debug("Created task %s in DB", task.id)
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        result = await self._session.execute(
            select(TaskRecord)
            .where(TaskRecord.id == task_id)
            .options(selectinload(TaskRecord.subtasks))
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return _record_to_task(record)

    async def list_recent(self, limit: int = 50, offset: int = 0) -> List[Task]:
        result = await self._session.execute(
            select(TaskRecord)
            .options(selectinload(TaskRecord.subtasks))
            .order_by(TaskRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_record_to_task(r) for r in result.scalars().all()]

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        await self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.id == task_id)
            .values(
                status=status.value,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def update_subtask(self, subtask: Subtask) -> None:
        await self._session.execute(
            update(SubtaskRecord)
            .where(SubtaskRecord.id == subtask.id)
            .values(
                status=subtask.status.value,
                retry_count=subtask.retry_count,
                output_data=subtask.output_data,
                assigned_worker_id=subtask.assigned_worker_id,
                started_at=subtask.started_at,
                completed_at=subtask.completed_at,
                error_message=subtask.error_message,
                error_traceback=subtask.error_traceback,
                tokens_used=subtask.tokens_used,
                estimated_cost_usd=subtask.estimated_cost_usd,
            )
        )

    async def save_subtasks(self, subtasks: List[Subtask]) -> None:
        records = [_subtask_to_record(st) for st in subtasks]
        self._session.add_all(records)
        await self._session.flush()

    async def append_event(self, event: ExecutionEvent) -> None:
        record = ExecutionEventRecord(
            id=event.id,
            task_id=event.task_id,
            subtask_id=event.subtask_id,
            event_type=event.event_type.value,
            agent_type=event.agent_type.value if event.agent_type else None,
            worker_id=event.worker_id,
            payload=event.payload,
            is_partial=event.is_partial,
            sequence_number=event.sequence_number,
            timestamp=event.timestamp,
        )
        self._session.add(record)
        await self._session.flush()

    async def get_task_events(
        self, task_id: str, limit: int = 500
    ) -> List[ExecutionEvent]:
        result = await self._session.execute(
            select(ExecutionEventRecord)
            .where(ExecutionEventRecord.task_id == task_id)
            .order_by(ExecutionEventRecord.sequence_number.asc())
            .limit(limit)
        )
        events = []
        for r in result.scalars().all():
            from nexusflow.shared.models.task import EventType
            events.append(ExecutionEvent(
                id=r.id,
                event_type=EventType(r.event_type),
                task_id=r.task_id,
                subtask_id=r.subtask_id,
                payload=r.payload or {},
                is_partial=r.is_partial,
                sequence_number=r.sequence_number,
                timestamp=r.timestamp,
            ))
        return events

    async def record_agent_metric(self, metric: AgentMetricRecord) -> None:
        self._session.add(metric)
        await self._session.flush()


def _task_to_record(task: Task) -> TaskRecord:
    return TaskRecord(
        id=task.id,
        title=task.title,
        description=task.description,
        priority=task.priority.value,
        status=task.status.value,
        submitted_by=task.submitted_by,
        timeout_seconds=task.timeout_seconds,
        metadata_json=task.metadata,
        total_tokens_used=task.total_tokens_used,
        total_cost_usd=task.total_cost_usd,
        execution_plan_version=task.execution_plan_version,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


def _subtask_to_record(subtask: Subtask) -> SubtaskRecord:
    return SubtaskRecord(
        id=subtask.id,
        task_id=subtask.task_id,
        name=subtask.name,
        description=subtask.description,
        agent_type=subtask.agent_type.value,
        priority=subtask.priority.value,
        status=subtask.status.value,
        retry_count=subtask.retry_count,
        retry_policy_json=subtask.retry_policy.model_dump(),
        input_data=subtask.input_data,
        output_data=subtask.output_data,
        depends_on=subtask.depends_on,
        assigned_worker_id=subtask.assigned_worker_id,
        queued_at=subtask.queued_at,
        started_at=subtask.started_at,
        completed_at=subtask.completed_at,
        error_message=subtask.error_message,
        tokens_used=subtask.tokens_used,
        estimated_cost_usd=subtask.estimated_cost_usd,
    )


def _record_to_task(record: TaskRecord) -> Task:
    subtasks = [_record_to_subtask(st) for st in (record.subtasks or [])]
    return Task(
        id=record.id,
        title=record.title,
        description=record.description,
        priority=Priority(record.priority),
        status=TaskStatus(record.status),
        subtasks=subtasks,
        metadata=record.metadata_json or {},
        submitted_by=record.submitted_by,
        timeout_seconds=record.timeout_seconds,
        total_tokens_used=record.total_tokens_used,
        total_cost_usd=record.total_cost_usd,
        execution_plan_version=record.execution_plan_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def _record_to_subtask(record: SubtaskRecord) -> Subtask:
    return Subtask(
        id=record.id,
        task_id=record.task_id,
        name=record.name,
        description=record.description,
        agent_type=AgentType(record.agent_type),
        priority=Priority(record.priority),
        status=TaskStatus(record.status),
        retry_count=record.retry_count,
        retry_policy=RetryPolicy(**(record.retry_policy_json or {})),
        input_data=record.input_data or {},
        output_data=record.output_data,
        depends_on=record.depends_on or [],
        assigned_worker_id=record.assigned_worker_id,
        queued_at=record.queued_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
        tokens_used=record.tokens_used,
        estimated_cost_usd=record.estimated_cost_usd,
    )
