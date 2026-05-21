import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from nexusflow.shared.models.task import AgentType, Subtask, TaskStatus, RetryPolicy
from nexusflow.shared.retry.manager import RetryManager, CircuitBreakerRegistry, CircuitState
from nexusflow.shared.queue.redis_streams import STREAM_DLQ


@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    for breaker in CircuitBreakerRegistry._breakers.values():
        breaker.state = CircuitState.CLOSED
        breaker._requests = []
        breaker._opened_at = None
    yield


@pytest.mark.asyncio
async def test_execute_success_first_attempt():
    subtask = Subtask(
        task_id="task-1",
        name="test-subtask",
        description="test",
        agent_type=AgentType.RETRIEVER,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, jitter=0.0)
    )

    mock_producer = AsyncMock()

    call_count = 0
    async def mock_coro():
        nonlocal call_count
        call_count += 1
        return "success-result"

    result = await RetryManager.execute_with_retry(
        coro_factory=mock_coro,
        subtask=subtask,
        producer=mock_producer
    )

    assert result == "success-result"
    assert call_count == 1
    mock_producer.publish.assert_not_called()


@pytest.mark.asyncio
async def test_execute_retry_then_success():
    subtask = Subtask(
        task_id="task-1",
        name="test-subtask",
        description="test",
        agent_type=AgentType.RETRIEVER,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, jitter=0.0)
    )

    mock_producer = AsyncMock()

    call_count = 0
    async def mock_coro():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("First attempt fails")
        return "success-on-second"

    on_retry_called = []
    async def on_retry_cb(attempt, exc):
        on_retry_called.append((attempt, exc))

    result = await RetryManager.execute_with_retry(
        coro_factory=mock_coro,
        subtask=subtask,
        producer=mock_producer,
        on_retry=on_retry_cb
    )

    assert result == "success-on-second"
    assert call_count == 2
    assert len(on_retry_called) == 1
    assert on_retry_called[0][0] == 1
    assert isinstance(on_retry_called[0][1], ValueError)
    mock_producer.publish.assert_not_called()


@pytest.mark.asyncio
async def test_execute_exhausts_retries_routes_to_dlq():
    subtask = Subtask(
        task_id="task-1",
        name="test-subtask",
        description="test",
        agent_type=AgentType.RETRIEVER,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.1, jitter=0.0)
    )

    mock_producer = AsyncMock()

    async def mock_coro():
        raise RuntimeError("Always fails")

    result = await RetryManager.execute_with_retry(
        coro_factory=mock_coro,
        subtask=subtask,
        producer=mock_producer
    )

    assert result is None
    mock_producer.publish.assert_called_once()
    published_args = mock_producer.publish.call_args[0]
    assert published_args[0] == STREAM_DLQ
    payload = published_args[1]
    assert payload["subtask_id"] == subtask.id
    assert payload["reason"] == "Always fails"
    assert payload["agent_type"] == "retriever"


@pytest.mark.asyncio
async def test_execute_fails_when_circuit_breaker_open():
    subtask = Subtask(
        task_id="task-1",
        name="test-subtask",
        description="test",
        agent_type=AgentType.RETRIEVER,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, jitter=0.0)
    )

    breaker = CircuitBreakerRegistry.get(AgentType.RETRIEVER)
    breaker.state = CircuitState.OPEN
    breaker._opened_at = 100000.0
    breaker.allow_request = MagicMock(return_value=False)

    mock_producer = AsyncMock()
    mock_coro = AsyncMock()

    result = await RetryManager.execute_with_retry(
        coro_factory=mock_coro,
        subtask=subtask,
        producer=mock_producer
    )

    assert result is None
    mock_coro.assert_not_called()
    mock_producer.publish.assert_called_once()
    published_args = mock_producer.publish.call_args[0]
    assert published_args[0] == STREAM_DLQ
    assert "circuit_breaker_open" in published_args[1]["reason"]
