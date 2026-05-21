import pytest
from datetime import datetime, timezone

from nexusflow.shared.models.task import (
    AgentType,
    Priority,
    RetryPolicy,
    Subtask,
    Task,
    TaskStatus,
)
from nexusflow.services.orchestrator.state_machine import (
    StateTransitionError,
    compute_task_status,
    transition_subtask,
    transition_task,
)


class TestRetryPolicy:
    def test_delay_increases_with_attempts(self):
        policy = RetryPolicy(base_delay_seconds=2.0, backoff_multiplier=2.0, jitter=0.0)
        delays = [policy.compute_delay(i) for i in range(1, 5)]
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1], f"Delay at attempt {i+1} not >= previous"

    def test_delay_capped_at_max(self):
        policy = RetryPolicy(
            base_delay_seconds=10.0,
            max_delay_seconds=30.0,
            backoff_multiplier=10.0,
            jitter=0.0,
        )
        for attempt in range(1, 10):
            delay = policy.compute_delay(attempt)
            assert delay <= policy.max_delay_seconds, f"Delay {delay} exceeded max {policy.max_delay_seconds}"

    def test_jitter_adds_variation(self):
        policy = RetryPolicy(base_delay_seconds=5.0, jitter=0.5)
        results = set(round(policy.compute_delay(2), 3) for _ in range(20))
        assert len(results) > 1, "Jitter should produce varied delays"


class TestStateMachine:
    def _make_task(self, status: TaskStatus = TaskStatus.PENDING) -> Task:
        return Task(title="Test Task", description="Test", status=status)

    def _make_subtask(self, status: TaskStatus = TaskStatus.PENDING) -> Subtask:
        return Subtask(
            task_id="fake-task-id",
            name="Test Subtask",
            description="Test",
            agent_type=AgentType.RETRIEVER,
            status=status,
        )

    def test_valid_task_transitions(self):
        task = self._make_task(TaskStatus.PENDING)
        transition_task(task, TaskStatus.PLANNING)
        assert task.status == TaskStatus.PLANNING

        transition_task(task, TaskStatus.PLANNED)
        assert task.status == TaskStatus.PLANNED

        transition_task(task, TaskStatus.RUNNING)
        assert task.status == TaskStatus.RUNNING

        transition_task(task, TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED

    def test_invalid_task_transition_raises(self):
        task = self._make_task(TaskStatus.COMPLETED)
        with pytest.raises(StateTransitionError):
            transition_task(task, TaskStatus.RUNNING)

    def test_valid_subtask_transitions(self):
        st = self._make_subtask(TaskStatus.PENDING)
        transition_subtask(st, TaskStatus.QUEUED)
        assert st.status == TaskStatus.QUEUED

        transition_subtask(st, TaskStatus.RUNNING)
        assert st.status == TaskStatus.RUNNING

        transition_subtask(st, TaskStatus.COMPLETED)
        assert st.status == TaskStatus.COMPLETED

    def test_retry_transition(self):
        st = self._make_subtask(TaskStatus.RUNNING)
        transition_subtask(st, TaskStatus.FAILED)
        transition_subtask(st, TaskStatus.RETRYING)
        assert st.status == TaskStatus.RETRYING

    def test_dlq_is_terminal(self):
        st = self._make_subtask(TaskStatus.DLQ)
        with pytest.raises(StateTransitionError):
            transition_subtask(st, TaskStatus.PENDING)


class TestDAGReadiness:
    def _make_subtask(self, tid: str, agent: AgentType, depends_on=None, status=TaskStatus.PENDING):
        return Subtask(
            id=tid,
            task_id="task-1",
            name=tid,
            description="test",
            agent_type=agent,
            status=status,
            depends_on=depends_on or [],
        )

    def test_independent_subtasks_all_ready(self):
        task = Task(title="T", description="D")
        task.subtasks = [
            self._make_subtask("a", AgentType.RETRIEVER),
            self._make_subtask("b", AgentType.ANALYZER),
        ]
        ready = task.get_ready_subtasks()
        assert len(ready) == 2

    def test_dependent_subtask_not_ready_until_dep_complete(self):
        task = Task(title="T", description="D")
        task.subtasks = [
            self._make_subtask("a", AgentType.RETRIEVER),
            self._make_subtask("b", AgentType.ANALYZER, depends_on=["a"]),
        ]
        ready = task.get_ready_subtasks()
        ready_ids = {st.id for st in ready}
        assert "b" not in ready_ids
        assert "a" in ready_ids

    def test_dependent_subtask_ready_after_dep_complete(self):
        task = Task(title="T", description="D")
        task.subtasks = [
            self._make_subtask("a", AgentType.RETRIEVER, status=TaskStatus.COMPLETED),
            self._make_subtask("b", AgentType.ANALYZER, depends_on=["a"]),
        ]
        ready = task.get_ready_subtasks()
        assert any(st.id == "b" for st in ready)

    def test_chain_dependency(self):
        task = Task(title="T", description="D")
        task.subtasks = [
            self._make_subtask("a", AgentType.RETRIEVER),
            self._make_subtask("b", AgentType.ANALYZER, depends_on=["a"]),
            self._make_subtask("c", AgentType.WRITER, depends_on=["b"]),
        ]
        ready = task.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_compute_task_status_all_complete(self):
        task = Task(title="T", description="D")
        task.subtasks = [
            self._make_subtask("a", AgentType.RETRIEVER, status=TaskStatus.COMPLETED),
            self._make_subtask("b", AgentType.ANALYZER, status=TaskStatus.COMPLETED),
        ]
        status = compute_task_status(task)
        assert status == TaskStatus.COMPLETED

    def test_compute_task_status_dlq_means_failed(self):
        task = Task(title="T", description="D")
        task.subtasks = [
            self._make_subtask("a", AgentType.RETRIEVER, status=TaskStatus.COMPLETED),
            self._make_subtask("b", AgentType.ANALYZER, status=TaskStatus.DLQ),
        ]
        status = compute_task_status(task)
        assert status == TaskStatus.FAILED
