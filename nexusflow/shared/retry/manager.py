from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional, TypeVar

from nexusflow.shared.models.task import AgentType, RetryPolicy, Subtask, TaskStatus
from nexusflow.shared.queue.redis_streams import STREAM_DLQ, RedisStreamProducer

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Sliding-window circuit breaker for a given agent type."""

    agent_type: AgentType
    failure_threshold: float = 0.5
    window_seconds: float = 60.0
    recovery_timeout: float = 30.0
    min_requests: int = 5

    state: CircuitState = CircuitState.CLOSED
    _requests: list[tuple[float, bool]] = field(default_factory=list)
    _opened_at: Optional[float] = None

    def record_success(self) -> None:
        self._requests.append((time.monotonic(), True))
        self._cleanup_window()
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker CLOSED for %s (probe succeeded)", self.agent_type)
            self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._requests.append((time.monotonic(), False))
        self._cleanup_window()
        if self.state == CircuitState.HALF_OPEN:
            logger.warning("Circuit breaker re-OPENED for %s (probe failed)", self.agent_type)
            self.state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            return

        if self.state == CircuitState.CLOSED:
            failure_rate = self._failure_rate()
            if (
                len(self._requests) >= self.min_requests
                and failure_rate >= self.failure_threshold
            ):
                logger.error(
                    "Circuit breaker OPENED for %s (failure rate=%.2f)",
                    self.agent_type, failure_rate
                )
                self.state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self._opened_at and (time.monotonic() - self._opened_at) >= self.recovery_timeout:
                logger.info("Circuit breaker HALF_OPEN for %s (trying probe)", self.agent_type)
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        return False

    def _failure_rate(self) -> float:
        if not self._requests:
            return 0.0
        failures = sum(1 for _, success in self._requests if not success)
        return failures / len(self._requests)

    def _cleanup_window(self) -> None:
        cutoff = time.monotonic() - self.window_seconds
        self._requests = [(ts, s) for ts, s in self._requests if ts > cutoff]


class CircuitBreakerRegistry:
    """One circuit breaker per agent type, shared across the process."""

    _breakers: Dict[AgentType, CircuitBreaker] = {}

    @classmethod
    def get(cls, agent_type: AgentType) -> CircuitBreaker:
        if agent_type not in cls._breakers:
            cls._breakers[agent_type] = CircuitBreaker(agent_type=agent_type)
        return cls._breakers[agent_type]

    @classmethod
    def get_all_states(cls) -> Dict[str, str]:
        return {str(k): v.state.value for k, v in cls._breakers.items()}


class RetryManager:
    """Wraps agent execution with retry logic, circuit breaking, and DLQ routing."""

    @staticmethod
    async def execute_with_retry(
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
        subtask: Subtask,
        producer: RedisStreamProducer,
        on_retry: Optional[Callable[[int, Exception], Coroutine[Any, Any, None]]] = None,
    ) -> Optional[T]:
        """
        Execute the coroutine with retry/circuit-breaker/DLQ logic.

        Returns the result on success, None if routed to DLQ.
        on_retry: optional async callback invoked before each retry attempt.
        """
        policy = subtask.retry_policy
        breaker = CircuitBreakerRegistry.get(subtask.agent_type)

        for attempt in range(1, policy.max_attempts + 1):
            if not breaker.allow_request():
                logger.error(
                    "Circuit breaker OPEN for %s — skipping attempt %d/%d",
                    subtask.agent_type, attempt, policy.max_attempts
                )
                await RetryManager._send_to_dlq(subtask, producer, "circuit_breaker_open")
                return None

            try:
                result = await asyncio.wait_for(
                    coro_factory(),
                    timeout=subtask.retry_policy.max_delay_seconds * 2,
                )
                breaker.record_success()
                return result

            except asyncio.TimeoutError as e:
                breaker.record_failure()
                logger.warning(
                    "Subtask %s timed out (attempt %d/%d)",
                    subtask.id, attempt, policy.max_attempts
                )
                last_exception = e

            except Exception as e:
                breaker.record_failure()
                logger.warning(
                    "Subtask %s failed (attempt %d/%d): %s",
                    subtask.id, attempt, policy.max_attempts, str(e)
                )
                last_exception = e

            if attempt < policy.max_attempts:
                delay = policy.compute_delay(attempt)
                logger.info(
                    "Retrying subtask %s in %.2fs (attempt %d/%d)",
                    subtask.id, delay, attempt + 1, policy.max_attempts
                )
                if on_retry:
                    await on_retry(attempt, last_exception)
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Subtask %s exhausted all %d retries. Routing to DLQ.",
                    subtask.id, policy.max_attempts,
                    exc_info=True,
                )
                await RetryManager._send_to_dlq(
                    subtask, producer, str(last_exception)
                )

        return None

    @staticmethod
    async def _send_to_dlq(
        subtask: Subtask,
        producer: RedisStreamProducer,
        reason: str,
    ) -> None:
        """Write failed subtask to the dead-letter queue for operator inspection."""
        dlq_payload = {
            "subtask_id": subtask.id,
            "task_id": subtask.task_id,
            "agent_type": subtask.agent_type.value,
            "retry_count": subtask.retry_count,
            "reason": reason,
            "input_data": subtask.input_data,
            "retry_policy": subtask.retry_policy.model_dump(),
        }
        try:
            await producer.publish(STREAM_DLQ, dlq_payload)
            logger.warning("Subtask %s written to DLQ", subtask.id)
        except Exception as e:
            logger.critical(
                "FAILED to write subtask %s to DLQ: %s",
                subtask.id, str(e), exc_info=True
            )
