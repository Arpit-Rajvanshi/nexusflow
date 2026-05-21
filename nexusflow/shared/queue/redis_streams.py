from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from redis.asyncio.client import Redis

from nexusflow.shared.config.settings import get_settings

logger = logging.getLogger(__name__)

STREAM_TASK_CREATED = "task.created"
STREAM_TASK_PLANNED = "task.planned"
STREAM_TASK_ASSIGNED = "task.assigned"
STREAM_TASK_COMPLETED = "task.completed"
STREAM_TASK_FAILED = "task.failed"
STREAM_RETRY_SCHEDULED = "retry.scheduled"
STREAM_DLQ = "dlq.events"
STREAM_STREAMING_EVENTS = "streaming.events"
STREAM_AGENT_HEARTBEAT = "agent.heartbeat"

ALL_STREAMS = [
    STREAM_TASK_CREATED,
    STREAM_TASK_PLANNED,
    STREAM_TASK_ASSIGNED,
    STREAM_TASK_COMPLETED,
    STREAM_TASK_FAILED,
    STREAM_RETRY_SCHEDULED,
    STREAM_DLQ,
    STREAM_STREAMING_EVENTS,
    STREAM_AGENT_HEARTBEAT,
]


class RedisStreamProducer:
    """Thin wrapper around XADD with serialization and stream trimming."""

    def __init__(self, client: Redis) -> None:
        self._client = client
        self._settings = get_settings()

    async def publish(
        self,
        stream: str,
        data: Dict[str, Any],
        maxlen: Optional[int] = None,
    ) -> str:
        """Publish an event to a stream. Returns the message ID."""
        payload = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in data.items()}
        payload["_ts"] = datetime.now(timezone.utc).isoformat()

        msg_id = await self._client.xadd(
            stream,
            payload,
            maxlen=maxlen or self._settings.redis.stream_max_len,
            approximate=True,
        )
        logger.debug("Published to %s: id=%s", stream, msg_id)
        return msg_id  # type: ignore[return-value]

    async def publish_event(self, stream: str, event_dict: Dict[str, Any]) -> str:
        """Publish an ExecutionEvent-like dict to a stream."""
        return await self.publish(stream, {"event": json.dumps(event_dict)})


class RedisStreamConsumer:
    """Consumer group-aware XREADGROUP wrapper with ACK and PEL recovery."""

    def __init__(
        self,
        client: Redis,
        group_name: str,
        consumer_name: str,
        streams: List[str],
        batch_size: int = 10,
        block_ms: int = 2000,
        claim_idle_ms: int = 30_000,
    ) -> None:
        self._client = client
        self._group = group_name
        self._consumer = consumer_name
        self._streams = streams
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._claim_idle_ms = claim_idle_ms
        self._running = False

    async def _ensure_groups(self) -> None:
        for stream in self._streams:
            try:
                await self._client.xgroup_create(
                    stream, self._group, id="0", mkstream=True
                )
                logger.info("Created consumer group %s on stream %s", self._group, stream)
            except aioredis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    pass
                else:
                    raise

    async def _try_claim_stale_messages(self, stream: str) -> List[Tuple[str, Dict]]:
        try:
            result = await self._client.xautoclaim(
                stream,
                self._group,
                self._consumer,
                self._claim_idle_ms,
                start_id="0-0",
                count=self._batch_size,
            )
            messages = result[1] if result and len(result) > 1 else []
            if messages:
                logger.warning(
                    "Reclaimed %d stale messages from stream %s",
                    len(messages), stream
                )
            return messages
        except Exception:
            return []

    async def read_messages(self) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        """Async generator yielding (stream_name, message_id, data_dict)."""
        await self._ensure_groups()
        self._running = True

        stream_ids = {s: ">" for s in self._streams}

        while self._running:
            try:
                results = await self._client.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams=stream_ids,
                    count=self._batch_size,
                    block=self._block_ms,
                )

                if not results:
                    for stream in self._streams:
                        stale = await self._try_claim_stale_messages(stream)
                        for msg_id, raw_data in stale:
                            data = self._deserialize(raw_data)
                            yield stream, msg_id, data
                    continue

                for stream_name, messages in results:
                    stream_name = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
                    for msg_id, raw_data in messages:
                        msg_id = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                        data = self._deserialize(raw_data)
                        yield stream_name, msg_id, data

            except asyncio.CancelledError:
                logger.info("Consumer %s shutting down", self._consumer)
                self._running = False
                break
            except Exception as e:
                logger.error("Consumer read error: %s", e, exc_info=True)
                await asyncio.sleep(1)

    async def ack(self, stream: str, message_id: str) -> None:
        """Acknowledge successful processing. Removes from PEL."""
        await self._client.xack(stream, self._group, message_id)

    @staticmethod
    def _deserialize(raw: Dict[bytes | str, bytes | str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for k, v in raw.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            try:
                result[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                result[key] = val
        return result

    def stop(self) -> None:
        self._running = False


class RedisConnectionPool:
    """Manages a single shared async Redis connection pool."""

    _pool: Optional[Redis] = None

    @classmethod
    async def get(cls) -> Redis:
        if cls._pool is None:
            settings = get_settings()
            cls._pool = aioredis.from_url(
                settings.redis.url,
                encoding="utf-8",
                decode_responses=False,
                max_connections=50,
            )
            await cls._pool.ping()
            logger.info("Redis connection pool established: %s", settings.redis.url)
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        if cls._pool:
            await cls._pool.aclose()
            cls._pool = None
            logger.info("Redis connection pool closed")
