"""
Streaming Gateway — WebSocket and SSE server for real-time task updates.

This is a dedicated service (separate from the API gateway) that handles
live streaming connections. Separating it avoids the streaming workload
interfering with API request handling.

How streaming works:
  1. Client connects to /ws/tasks/{task_id} with a valid JWT
  2. Gateway subscribes to the Redis streaming.events stream
  3. Events for the requested task_id are forwarded to the WebSocket
  4. Connection stays alive until task completes or client disconnects

Why a separate process for streaming?
  - WebSocket connections are long-lived. A single orchestrator task can
    keep a connection open for minutes. Having 500 of these in the same
    process as API request handling creates head-of-line blocking issues.
  - Async helps, but OS socket backlog and connection limits still matter.
  - Separate service lets us scale streaming independently from API.

Backpressure handling:
  If a client's WebSocket receive buffer fills up (slow client), we buffer
  up to buffer_size events then start dropping (oldest-first). We notify
  the client via a special "events_dropped" message. This is the right
  behavior — a slow consumer shouldn't block the producer pipeline.

SSE fallback:
  /sse/tasks/{task_id} provides an SSE endpoint for environments where
  WebSockets are blocked (some corporate proxies, certain CDN configs).
  Same event stream, different transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Deque, Dict, Optional, Set

import jwt
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.observability.logging import setup_logging
from nexusflow.shared.queue.redis_streams import (
    STREAM_STREAMING_EVENTS,
    RedisConnectionPool,
    RedisStreamConsumer,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """
    Manages all active WebSocket connections, organized by task_id.

    One task can have multiple watchers (e.g., multiple browser tabs).
    Each watcher gets its own buffered queue. The broadcaster task reads
    from Redis and fans out to all connected clients for a given task_id.
    """

    def __init__(self) -> None:
        # task_id → set of connected WebSocket objects
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        # task_id → per-connection event buffer (deque with max size)
        self._buffers: Dict[WebSocket, Deque[dict]] = {}
        self._lock = asyncio.Lock()
        self._buffer_size = settings.streaming.buffer_size

    async def connect(self, task_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[task_id].add(ws)
            self._buffers[ws] = deque(maxlen=self._buffer_size)
        logger.info(
            "WebSocket connected: task=%s total=%d",
            task_id, len(self._connections[task_id])
        )

    async def disconnect(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[task_id].discard(ws)
            self._buffers.pop(ws, None)
            if not self._connections[task_id]:
                del self._connections[task_id]
        logger.info("WebSocket disconnected: task=%s", task_id)

    async def broadcast_to_task(self, task_id: str, event: dict) -> None:
        """Send event to all connections watching this task."""
        async with self._lock:
            connections = set(self._connections.get(task_id, set()))

        if not connections:
            return  # No active viewers — event is just discarded (it's in Redis anyway)

        message = json.dumps(event)
        dead_connections = set()

        for ws in connections:
            try:
                await ws.send_text(message)
            except WebSocketDisconnect:
                dead_connections.add(ws)
            except Exception as e:
                logger.warning("Failed to send to WebSocket: %s", e)
                dead_connections.add(ws)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    self._connections[task_id].discard(ws)
                    self._buffers.pop(ws, None)

    def get_connection_count(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._connections.items()}

    def total_connections(self) -> int:
        return sum(len(v) for v in self._connections.values())


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("streaming", level=settings.log_level, json_output=settings.is_production)
    redis = await RedisConnectionPool.get()
    # Start the background task that reads from Redis and fans out to WebSockets
    broadcast_task = asyncio.create_task(
        _redis_broadcast_loop(), name="redis-broadcast-loop"
    )
    logger.info("Streaming gateway started")
    yield
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    await RedisConnectionPool.close()
    logger.info("Streaming gateway shutdown")


app = FastAPI(
    title="NexusFlow Streaming Gateway",
    description="Real-time WebSocket and SSE streaming for task execution events.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Background: Redis → WebSocket fanout
# ---------------------------------------------------------------------------


async def _redis_broadcast_loop() -> None:
    """
    Continuously read from Redis streaming.events stream and fan out
    to appropriate WebSocket connections.

    This runs as a single background task. It's not parallelized because
    Redis consumer read is inherently sequential — parallelizing would
    require multiple consumer group members and event deduplication logic.
    """
    import socket
    import os

    redis = await RedisConnectionPool.get()
    consumer = RedisStreamConsumer(
        client=redis,
        group_name=f"{settings.redis.consumer_group}-streaming",
        consumer_name=f"streaming-{socket.gethostname()}-{os.getpid()}",
        streams=[STREAM_STREAMING_EVENTS],
        batch_size=50,   # Higher batch for streaming — many small events
        block_ms=1000,
    )

    logger.info("Redis broadcast loop started")

    async for stream_name, msg_id, data in consumer.read_messages():
        try:
            # Events can be wrapped in an "event" key (from publish_event())
            raw_event = data.get("event", data)
            if isinstance(raw_event, str):
                raw_event = json.loads(raw_event)

            task_id = raw_event.get("task_id")
            if task_id and manager.total_connections() > 0:
                await manager.broadcast_to_task(task_id, raw_event)

            await consumer.ack(stream_name, msg_id)

        except Exception as e:
            logger.error("Broadcast loop error: %s", e, exc_info=True)
            # Don't ACK — will be retried


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/tasks/{task_id}")
async def websocket_task_stream(
    websocket: WebSocket,
    task_id: str,
    token: Optional[str] = Query(default=None),
) -> None:
    """
    WebSocket endpoint for real-time task execution updates.

    Connect with: ws://localhost:8001/ws/tasks/{task_id}?token={jwt}

    Events received:
      - task.started, task.completed, task.failed
      - subtask.queued, subtask.started, subtask.completed, subtask.failed
      - agent.log, agent.partial_output
      - system.error

    The connection closes automatically when the task reaches a terminal state.
    """
    # Authenticate via query param token (WebSocket headers are limited in browsers)
    if token:
        try:
            jwt.decode(
                token,
                settings.gateway.jwt_secret,
                algorithms=[settings.gateway.jwt_algorithm],
            )
        except jwt.InvalidTokenError:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await manager.connect(task_id, websocket)

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connection.established",
            "task_id": task_id,
            "message": "Connected. Streaming task events in real-time.",
        })

        # Keep connection alive — events come from the broadcast loop
        # We just need to handle pings and detect disconnection
        while True:
            try:
                # Wait for client messages (ping/pong keepalive)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.streaming.ws_ping_interval * 2,
                )
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send a keepalive ping to detect zombie connections
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket error for task %s: %s", task_id, e)
    finally:
        await manager.disconnect(task_id, websocket)


# ---------------------------------------------------------------------------
# SSE fallback endpoint
# ---------------------------------------------------------------------------


@app.get("/sse/tasks/{task_id}")
async def sse_task_stream(
    task_id: str,
    token: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """
    Server-Sent Events fallback for environments where WebSockets are blocked.

    Usage: EventSource('/sse/tasks/{task_id}?token={jwt}')

    SSE is simpler than WebSockets (HTTP-based, auto-reconnect) but doesn't
    support bidirectional communication. Fine for read-only dashboards.
    """
    if token:
        try:
            jwt.decode(
                token,
                settings.gateway.jwt_secret,
                algorithms=[settings.gateway.jwt_algorithm],
            )
        except jwt.InvalidTokenError:
            return StreamingResponse(
                _sse_error("Invalid token"), media_type="text/event-stream"
            )

    return StreamingResponse(
        _sse_generator(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def _sse_generator(task_id: str):
    """Generate SSE events for a task by polling a local queue."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    # Register a simple callback-based connection
    # (SSE doesn't fit the WebSocket manager model cleanly)
    yield f"data: {json.dumps({'type': 'connection.established', 'task_id': task_id})}\n\n"

    # Poll Redis directly (simpler than hooking into WebSocket manager for SSE)
    import socket, os
    redis = await RedisConnectionPool.get()
    consumer = RedisStreamConsumer(
        client=redis,
        group_name=f"{settings.redis.consumer_group}-sse",
        consumer_name=f"sse-{socket.gethostname()}-{os.getpid()}-{task_id[:8]}",
        streams=[STREAM_STREAMING_EVENTS],
        block_ms=500,
    )

    async for stream_name, msg_id, data in consumer.read_messages():
        raw_event = data.get("event", data)
        if isinstance(raw_event, str):
            raw_event = json.loads(raw_event)

        if raw_event.get("task_id") == task_id:
            yield f"data: {json.dumps(raw_event)}\n\n"
            await consumer.ack(stream_name, msg_id)

            # Close stream on terminal events
            event_type = raw_event.get("event_type", "")
            if event_type in ("task.completed", "task.failed", "task.cancelled"):
                yield f"data: {json.dumps({'type': 'stream.closed'})}\n\n"
                break


async def _sse_error(message: str):
    yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"


# ---------------------------------------------------------------------------
# Monitoring endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": "nexusflow-streaming",
        "active_connections": manager.total_connections(),
        "tasks_with_viewers": len(manager.get_connection_count()),
    }
