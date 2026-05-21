from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DLQ = "dlq"


class AgentType(str, Enum):
    RETRIEVER = "retriever"
    ANALYZER = "analyzer"
    WRITER = "writer"
    VALIDATOR = "validator"
    PLANNER = "planner"


class Priority(int, Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: float = Field(default=2.0, ge=0.1)
    max_delay_seconds: float = Field(default=60.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    jitter: float = Field(default=0.2, ge=0.0, le=1.0)

    def compute_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter."""
        import random
        base = self.base_delay_seconds * (self.backoff_multiplier ** (attempt - 1))
        capped = min(base, self.max_delay_seconds)
        jitter_amount = capped * self.jitter * random.random()  # noqa: S311
        return capped + jitter_amount


class Subtask(BaseModel):
    id: str = Field(default_factory=_new_id)
    task_id: str
    name: str
    description: str

    agent_type: AgentType
    priority: Priority = Priority.NORMAL

    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Optional[Dict[str, Any]] = None

    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = Field(default=0, ge=0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

    depends_on: List[str] = Field(default_factory=list)

    assigned_worker_id: Optional[str] = None
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    error_message: Optional[str] = None
    error_traceback: Optional[str] = None

    tokens_used: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            TaskStatus.COMPLETED, TaskStatus.FAILED,
            TaskStatus.CANCELLED, TaskStatus.DLQ
        }

    @property
    def can_retry(self) -> bool:
        return (
            self.status == TaskStatus.FAILED
            and self.retry_count < self.retry_policy.max_attempts
        )


class TaskInput(BaseModel):
    """Payload accepted by the API to create a new task."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    priority: Priority = Priority.NORMAL
    metadata: Dict[str, Any] = Field(default_factory=dict)

    max_subtasks: Optional[int] = Field(default=None, le=50)
    timeout_seconds: Optional[int] = Field(default=None, ge=10)


class Task(BaseModel):
    id: str = Field(default_factory=_new_id)
    title: str
    description: str
    priority: Priority = Priority.NORMAL

    status: TaskStatus = TaskStatus.PENDING
    subtasks: List[Subtask] = Field(default_factory=list)

    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None

    submitted_by: Optional[str] = None
    timeout_seconds: int = Field(default=300)

    total_tokens_used: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)

    execution_plan_version: int = Field(default=0)

    def get_subtask(self, subtask_id: str) -> Optional[Subtask]:
        for st in self.subtasks:
            if st.id == subtask_id:
                return st
        return None

    def get_ready_subtasks(self) -> List[Subtask]:
        """Return subtasks whose dependencies are all completed and are still PENDING/QUEUED."""
        completed_ids = {
            st.id for st in self.subtasks if st.status == TaskStatus.COMPLETED
        }
        ready = []
        for st in self.subtasks:
            if st.status not in {TaskStatus.PENDING, TaskStatus.QUEUED}:
                continue
            if all(dep in completed_ids for dep in st.depends_on):
                ready.append(st)
        return ready

    @property
    def is_complete(self) -> bool:
        if not self.subtasks:
            return False
        return all(st.is_terminal for st in self.subtasks)

    @property
    def has_failures(self) -> bool:
        return any(
            st.status in {TaskStatus.FAILED, TaskStatus.DLQ}
            for st in self.subtasks
        )

    def update_aggregates(self) -> None:
        """Recompute cost/token totals from subtasks."""
        self.total_tokens_used = sum(st.tokens_used for st in self.subtasks)
        self.total_cost_usd = sum(st.estimated_cost_usd for st in self.subtasks)
        self.updated_at = _utcnow()


class EventType(str, Enum):
    TASK_CREATED = "task.created"
    TASK_PLANNED = "task.planned"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    SUBTASK_QUEUED = "subtask.queued"
    SUBTASK_STARTED = "subtask.started"
    SUBTASK_COMPLETED = "subtask.completed"
    SUBTASK_FAILED = "subtask.failed"
    SUBTASK_RETRYING = "subtask.retrying"
    SUBTASK_DLQ = "subtask.dlq"

    AGENT_LOG = "agent.log"
    AGENT_PARTIAL_OUTPUT = "agent.partial_output"
    AGENT_HEARTBEAT = "agent.heartbeat"

    BATCH_SUBMITTED = "batch.submitted"
    BATCH_COMPLETED = "batch.completed"

    SYSTEM_ERROR = "system.error"


class ExecutionEvent(BaseModel):
    id: str = Field(default_factory=_new_id)
    event_type: EventType
    task_id: str
    subtask_id: Optional[str] = None
    agent_type: Optional[AgentType] = None
    worker_id: Optional[str] = None

    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)

    is_partial: bool = False
    sequence_number: int = Field(default=0)
