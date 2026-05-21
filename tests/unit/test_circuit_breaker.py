import pytest
import time

from nexusflow.shared.models.task import AgentType
from nexusflow.shared.retry.manager import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    def _make_breaker(self, **kwargs) -> CircuitBreaker:
        defaults = {
            "agent_type": AgentType.RETRIEVER,
            "failure_threshold": 0.5,
            "window_seconds": 60.0,
            "recovery_timeout": 5.0,
            "min_requests": 4,
        }
        defaults.update(kwargs)
        return CircuitBreaker(**defaults)

    def test_starts_closed(self):
        breaker = self._make_breaker()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    def test_stays_closed_below_threshold(self):
        breaker = self._make_breaker(failure_threshold=0.5, min_requests=4)
        breaker.record_failure()
        breaker.record_success()
        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        breaker = self._make_breaker(failure_threshold=0.5, min_requests=4)
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.allow_request() is False

    def test_opens_only_after_min_requests(self):
        breaker = self._make_breaker(failure_threshold=0.5, min_requests=10)
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_after_recovery_timeout(self):
        breaker = self._make_breaker(recovery_timeout=0.05)
        for _ in range(4):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        time.sleep(0.1)
        assert breaker.allow_request() is True
        assert breaker.state == CircuitState.HALF_OPEN

    def test_closes_after_successful_probe(self):
        breaker = self._make_breaker(recovery_timeout=0.01)
        for _ in range(4):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.05)
        breaker.allow_request()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_reopens_on_failed_probe(self):
        breaker = self._make_breaker(recovery_timeout=0.01)
        for _ in range(4):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.05)
        breaker.allow_request()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
