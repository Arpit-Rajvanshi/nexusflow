from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, Generic, List, Optional, TypeVar
from uuid import uuid4

from nexusflow.shared.config.settings import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class BatchRequest(Generic[T]):
    request_id: str = field(default_factory=lambda: str(uuid4()))
    payload: Any = None
    future: Optional[asyncio.Future] = field(default=None)
    enqueued_at: float = field(default_factory=time.monotonic)


class BatchScheduler(Generic[T]):
    """
    Time-window batch scheduler.

    Accumulates requests over a short window and dispatches them together.
    Results are returned via per-request asyncio.Future objects.
    """

    def __init__(
        self,
        batch_handler: Callable[[List[Any]], Coroutine[Any, Any, List[T]]],
        window_ms: Optional[int] = None,
        max_batch_size: Optional[int] = None,
        min_batch_size: Optional[int] = None,
        name: str = "default",
    ) -> None:
        self._handler = batch_handler
        settings = get_settings().batching
        self._window_ms = (window_ms or settings.window_ms) / 1000
        self._max_batch_size = max_batch_size or settings.max_batch_size
        self._min_batch_size = min_batch_size or settings.min_batch_size
        self._name = name

        self._queue: deque[BatchRequest[T]] = deque()
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

        self._batches_dispatched = 0
        self._total_requests_processed = 0
        self._last_flush_at: Optional[float] = None

    async def start(self) -> None:
        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name=f"batch-scheduler-{self._name}"
        )
        logger.info(
            "BatchScheduler '%s' started (window=%.0fms, max=%d, min=%d)",
            self._name, self._window_ms * 1000, self._max_batch_size, self._min_batch_size
        )

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()
        logger.info(
            "BatchScheduler '%s' stopped. Total batches=%d, requests=%d",
            self._name, self._batches_dispatched, self._total_requests_processed
        )

    async def enqueue(self, payload: Any) -> T:
        """Add a request to the batch queue and wait for its result."""
        loop = asyncio.get_running_loop()
        request: BatchRequest[T] = BatchRequest(
            payload=payload,
            future=loop.create_future()
        )
        async with self._lock:
            self._queue.append(request)

        async with self._lock:
            if len(self._queue) >= self._max_batch_size:
                asyncio.create_task(self._flush())

        return await request.future

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._window_ms)
            async with self._lock:
                queue_size = len(self._queue)
            if queue_size >= self._min_batch_size or queue_size > 0:
                await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._queue:
                return
            batch = []
            while self._queue and len(batch) < self._max_batch_size:
                batch.append(self._queue.popleft())

        if not batch:
            return

        payloads = [req.payload for req in batch]
        self._batches_dispatched += 1
        self._last_flush_at = time.monotonic()

        logger.debug(
            "BatchScheduler '%s' dispatching batch size=%d",
            self._name, len(batch)
        )

        try:
            results = await self._handler(payloads)
            if len(results) != len(batch):
                raise ValueError(
                    f"Handler returned {len(results)} results for {len(batch)} requests"
                )
            for req, result in zip(batch, results):
                if not req.future.done():
                    req.future.set_result(result)
            self._total_requests_processed += len(batch)

        except Exception as e:
            logger.error(
                "BatchScheduler '%s' handler failed: %s",
                self._name, str(e), exc_info=True
            )
            for req in batch:
                if not req.future.done():
                    req.future.set_exception(e)

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "pending": len(self._queue),
            "batches_dispatched": self._batches_dispatched,
            "total_processed": self._total_requests_processed,
            "last_flush_at": self._last_flush_at,
        }
