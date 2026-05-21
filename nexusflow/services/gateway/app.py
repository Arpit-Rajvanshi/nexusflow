from __future__ import annotations

import json
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
import time as time_module

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.database import close_db, get_db, init_db
from nexusflow.shared.models.task import Priority, Task, TaskInput, TaskStatus
from nexusflow.shared.observability.logging import setup_logging
from nexusflow.shared.queue.redis_streams import (
    STREAM_TASK_CREATED,
    RedisConnectionPool,
    RedisStreamProducer,
)
from nexusflow.services.orchestrator.repository import TaskRepository

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("gateway", level=settings.log_level, json_output=settings.is_production)
    await init_db()
    redis = await RedisConnectionPool.get()
    app.state.producer = RedisStreamProducer(redis)
    logger.info("Gateway started")
    yield
    await RedisConnectionPool.close()
    await close_db()
    logger.info("Gateway shutdown complete")


app = FastAPI(
    title="NexusFlow API",
    description=(
        "Agentic AI Orchestration Platform — multi-agent task execution "
        "with DAG scheduling, streaming, and fault tolerance."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else ["https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def create_token(username: str) -> str:
    import time
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + (settings.gateway.jwt_expire_minutes * 60),
    }
    return jwt.encode(payload, settings.gateway.jwt_secret, algorithm=settings.gateway.jwt_algorithm)


async def get_current_user(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[7:]
    try:
        payload = jwt.decode(
            token,
            settings.gateway.jwt_secret,
            algorithms=[settings.gateway.jwt_algorithm],
        )
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


_request_counts: Dict[str, List[float]] = defaultdict(list)


def check_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    now = time_module.time()
    window = 60

    _request_counts[client_ip] = [
        ts for ts in _request_counts[client_ip] if now - ts < window
    ]
    if len(_request_counts[client_ip]) >= settings.gateway.rate_limit_rpm:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {settings.gateway.rate_limit_rpm} requests/minute",
        )
    _request_counts[client_ip].append(now)


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str
    message: str
    streaming_url: str


class TaskDetailResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    priority: int
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    subtask_count: int
    total_tokens_used: int
    total_cost_usd: float
    subtasks: List[Dict[str, Any]]


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "nexusflow-gateway", "version": "1.0.0"}


@app.post("/auth/token", response_model=TokenResponse, tags=["Auth"])
async def get_token(request: TokenRequest) -> TokenResponse:
    """Issue a JWT token for API access."""
    if not request.username or not request.password:
        raise HTTPException(status_code=400, detail="Username and password required")
    token = create_token(request.username)
    return TokenResponse(access_token=token)


@app.post(
    "/api/v1/tasks",
    response_model=TaskSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Tasks"],
)
async def submit_task(
    task_input: TaskInput,
    request: Request,
    current_user: str = Depends(get_current_user),
) -> TaskSubmitResponse:
    """
    Submit a task for multi-agent execution. Returns 202 immediately.
    Connect to the streaming_url via WebSocket or poll GET /api/v1/tasks/{task_id} for status.
    """
    check_rate_limit(request)

    task = Task(
        title=task_input.title,
        description=task_input.description,
        priority=task_input.priority,
        metadata=task_input.metadata,
        submitted_by=current_user,
        timeout_seconds=task_input.timeout_seconds or settings.orchestrator.task_timeout_seconds,
    )

    async with get_db() as session:
        repo = TaskRepository(session)
        await repo.create(task)

    producer: RedisStreamProducer = request.app.state.producer
    await producer.publish(
        STREAM_TASK_CREATED,
        {"task": task.model_dump_json()},
    )

    logger.info(
        "Task submitted: id=%s title=%s user=%s",
        task.id, task.title[:50], current_user
    )

    streaming_url = f"ws://localhost:{settings.streaming.port}/ws/tasks/{task.id}"

    return TaskSubmitResponse(
        task_id=task.id,
        status="accepted",
        message="Task queued for execution. Connect to streaming_url for live updates.",
        streaming_url=streaming_url,
    )


@app.get("/api/v1/tasks", tags=["Tasks"])
async def list_tasks(
    limit: int = 20,
    offset: int = 0,
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """List recent tasks ordered by creation time."""
    async with get_db() as session:
        repo = TaskRepository(session)
        tasks = await repo.list_recent(limit=limit, offset=offset)

    return {
        "tasks": [_task_to_response(t) for t in tasks],
        "total": len(tasks),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/v1/tasks/{task_id}", response_model=TaskDetailResponse, tags=["Tasks"])
async def get_task(
    task_id: str,
    current_user: str = Depends(get_current_user),
) -> TaskDetailResponse:
    """Get full task details including all subtasks and their current status."""
    async with get_db() as session:
        repo = TaskRepository(session)
        task = await repo.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return _task_to_response(task)


@app.delete("/api/v1/tasks/{task_id}", tags=["Tasks"])
async def cancel_task(
    task_id: str,
    request: Request,
    current_user: str = Depends(get_current_user),
) -> Dict[str, str]:
    """Request task cancellation. Takes effect on the next scheduling tick."""
    async with get_db() as session:
        repo = TaskRepository(session)
        task = await repo.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        raise HTTPException(
            status_code=409,
            detail=f"Task already in terminal state: {task.status.value}"
        )

    async with get_db() as session:
        repo = TaskRepository(session)
        await repo.update_status(task_id, TaskStatus.CANCELLED)

    return {"task_id": task_id, "status": "cancellation_requested"}


@app.get("/api/v1/tasks/{task_id}/events", tags=["Tasks"])
async def get_task_events(
    task_id: str,
    limit: int = 200,
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get ordered event history for a task."""
    async with get_db() as session:
        repo = TaskRepository(session)
        events = await repo.get_task_events(task_id, limit=limit)

    return {
        "task_id": task_id,
        "events": [e.model_dump(mode="json") for e in events],
        "count": len(events),
    }


@app.get("/api/v1/system/health", tags=["System"])
async def system_health(request: Request) -> Dict[str, Any]:
    """Extended health check including Redis and DB connectivity."""
    health: Dict[str, Any] = {"gateway": "healthy"}
    try:
        redis = await RedisConnectionPool.get()
        await redis.ping()
        health["redis"] = "healthy"
    except Exception as e:
        health["redis"] = f"unhealthy: {e}"

    try:
        async with get_db() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        health["database"] = "healthy"
    except Exception as e:
        health["database"] = f"unhealthy: {e}"

    overall = "healthy" if all(v == "healthy" for v in health.values()) else "degraded"
    health["overall"] = overall
    return health


@app.get("/api/v1/system/metrics", tags=["System"])
async def system_metrics(
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Basic system metrics."""
    return {
        "service": "nexusflow-gateway",
        "rate_limiter_tracked_ips": len(_request_counts),
        "note": "Full metrics available via Prometheus endpoint on :9090",
    }


def _task_to_response(task: Task) -> Dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "subtask_count": len(task.subtasks),
        "total_tokens_used": task.total_tokens_used,
        "total_cost_usd": task.total_cost_usd,
        "subtasks": [
            {
                "id": st.id,
                "name": st.name,
                "description": st.description,
                "agent_type": st.agent_type.value,
                "status": st.status.value,
                "retry_count": st.retry_count,
                "tokens_used": st.tokens_used,
                "cost_usd": st.estimated_cost_usd,
                "started_at": st.started_at.isoformat() if st.started_at else None,
                "completed_at": st.completed_at.isoformat() if st.completed_at else None,
                "error_message": st.error_message,
            }
            for st in task.subtasks
        ],
    }
