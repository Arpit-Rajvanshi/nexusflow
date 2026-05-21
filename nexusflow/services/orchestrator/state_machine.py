from __future__ import annotations

from typing import Dict, Set

from nexusflow.shared.models.task import Task, TaskStatus, Subtask


class StateTransitionError(Exception):
    pass


TASK_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.PENDING:    {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNING:   {TaskStatus.PLANNED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.PLANNED:    {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING:    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.FAILED:     {TaskStatus.RETRYING},
    TaskStatus.RETRYING:   {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.DLQ},
    TaskStatus.COMPLETED:  set(),
    TaskStatus.CANCELLED:  set(),
    TaskStatus.DLQ:        set(),
}

SUBTASK_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.PENDING:    {TaskStatus.QUEUED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED:     {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING:    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.FAILED:     {TaskStatus.RETRYING, TaskStatus.DLQ},
    TaskStatus.RETRYING:   {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.DLQ},
    TaskStatus.COMPLETED:  set(),
    TaskStatus.CANCELLED:  set(),
    TaskStatus.DLQ:        set(),
}


def transition_task(task: Task, new_status: TaskStatus) -> None:
    """Transition a Task to a new status. Raises StateTransitionError on invalid transition."""
    current = task.status
    allowed = TASK_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise StateTransitionError(
            f"Task {task.id}: invalid transition {current.value} → {new_status.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    task.status = new_status


def transition_subtask(subtask: Subtask, new_status: TaskStatus) -> None:
    """Transition a Subtask to a new status. Raises StateTransitionError on invalid transition."""
    current = subtask.status
    allowed = SUBTASK_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise StateTransitionError(
            f"Subtask {subtask.id}: invalid transition {current.value} → {new_status.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    subtask.status = new_status


def compute_task_status(task: Task) -> TaskStatus:
    """Derive aggregate task status from its subtasks."""
    if not task.subtasks:
        return task.status

    statuses = {st.status for st in task.subtasks}

    if TaskStatus.DLQ in statuses:
        return TaskStatus.FAILED
    if TaskStatus.RUNNING in statuses or TaskStatus.RETRYING in statuses:
        return TaskStatus.RUNNING
    if TaskStatus.FAILED in statuses:
        return TaskStatus.FAILED
    if all(st.status == TaskStatus.COMPLETED for st in task.subtasks):
        return TaskStatus.COMPLETED
    return TaskStatus.PLANNED
