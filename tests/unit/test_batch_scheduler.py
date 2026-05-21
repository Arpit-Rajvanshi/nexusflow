import asyncio
import pytest
from unittest.mock import AsyncMock, call

from nexusflow.shared.batching.scheduler import BatchScheduler


@pytest.fixture
def scheduler():
    async def noop_handler(payloads):
        return payloads
    return BatchScheduler(
        batch_handler=noop_handler,
        window_ms=50,
        max_batch_size=10,
        min_batch_size=1,
        name="test",
    )


class TestBatchScheduler:
    @pytest.mark.asyncio
    async def test_single_request_returns_result(self, scheduler):
        await scheduler.start()
        result = await scheduler.enqueue("hello")
        assert result == "hello"
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_concurrent_requests_batched(self):
        batch_calls = []

        async def tracking_handler(payloads):
            batch_calls.append(len(payloads))
            return payloads

        sched = BatchScheduler(
            batch_handler=tracking_handler,
            window_ms=100,
            max_batch_size=20,
            min_batch_size=1,
            name="tracking",
        )
        await sched.start()

        results = await asyncio.gather(*[sched.enqueue(f"item-{i}") for i in range(5)])
        await sched.stop()

        assert sorted(results) == [f"item-{i}" for i in range(5)]
        assert sum(batch_calls) == 5

    @pytest.mark.asyncio
    async def test_max_batch_size_respected(self):
        received_batch_sizes = []

        async def handler(payloads):
            received_batch_sizes.append(len(payloads))
            return payloads

        sched = BatchScheduler(
            batch_handler=handler,
            window_ms=500,
            max_batch_size=3,
            min_batch_size=1,
            name="size-test",
        )
        await sched.start()

        results = await asyncio.gather(*[sched.enqueue(i) for i in range(9)])
        await sched.stop()

        assert sorted(results) == list(range(9))
        assert all(s <= 3 for s in received_batch_sizes), f"Batch sizes: {received_batch_sizes}"

    @pytest.mark.asyncio
    async def test_handler_exception_propagates_to_callers(self):
        async def failing_handler(payloads):
            raise ValueError("Handler error")

        sched = BatchScheduler(
            batch_handler=failing_handler,
            window_ms=50,
            max_batch_size=5,
            min_batch_size=1,
            name="fail-test",
        )
        await sched.start()

        with pytest.raises(ValueError, match="Handler error"):
            await sched.enqueue("test")

        await sched.stop()

    @pytest.mark.asyncio
    async def test_stats_tracked_correctly(self, scheduler):
        await scheduler.start()
        for i in range(3):
            await scheduler.enqueue(f"item-{i}")
        await scheduler.stop()

        stats = scheduler.stats()
        assert stats["total_processed"] == 3
        assert stats["batches_dispatched"] >= 1
        assert stats["name"] == "test"
