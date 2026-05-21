# Architecture — NexusFlow

## High-Level Design

NexusFlow is a distributed, event-driven system. The primary design principle is **loose coupling through message queues** — services communicate via Redis Streams rather than direct function calls or HTTP. This means:

- Services can be scaled, restarted, and deployed independently
- Failures in one service don't cascade synchronously to others
- Execution history is preserved in the stream (replayable)
- Adding a new agent type doesn't require modifying existing services

## Component Responsibilities

### API Gateway (`services/gateway`)
- Accepts task submissions via REST
- Validates input, issues JWT tokens, enforces rate limits
- Persists tasks to PostgreSQL immediately (for quick status checks)
- Publishes `task.created` events to Redis Streams
- Returns 202 Accepted — task processing is fully async

The gateway doesn't wait for planning or execution. It enqueues the task and returns a task ID. Clients poll or connect via WebSocket for updates.

### Planner Service (`services/planner`)
- Consumes `task.created` events
- Uses LLM to decompose tasks into a DAG of subtasks
- Persists subtasks to PostgreSQL
- Publishes `task.planned` with the full task + subtask graph
- Falls back to hardcoded templates for recognized task patterns

The planner is stateless and easily replaceable. The decomposition strategy can be improved without touching the orchestrator or agents.

### Orchestrator Engine (`services/orchestrator`)
- Consumes `task.planned` events, loads task into in-memory DAG state
- Runs a 500ms scheduling loop that finds subtasks whose dependencies are all complete
- Dispatches ready subtasks to `task.assigned` stream
- Handles `task.completed` and `task.failed` events
- Manages retries, DLQ routing, and task completion detection
- Publishes streaming events for real-time client updates

The orchestrator holds execution state in memory for performance, with PostgreSQL as the persistent backup for recovery. If it crashes, it rehydrates from the DB.

### Agent Workers (`agents/`)
- Consume `task.assigned` events (filtered by `agent_type`)
- Execute their specialized logic (LLM calls, data processing)
- Publish completion/failure events back to the queue
- Send partial outputs and logs to `streaming.events` for live display

Each agent type runs as an independent process pool. Multiple workers of the same type share a Redis consumer group for automatic load balancing.

### Streaming Gateway (`services/streaming`)
- Accepts WebSocket connections from clients (one per task)
- Subscribes to Redis `streaming.events` stream
- Broadcasts events to all clients watching a given task
- SSE fallback for environments where WebSockets are blocked

### Queue Layer — Redis Streams

Stream names and their producers/consumers:

| Stream | Producer | Consumer |
|--------|----------|----------|
| `task.created` | API Gateway | Planner |
| `task.planned` | Planner | Orchestrator |
| `task.assigned` | Orchestrator | Agent Workers |
| `task.completed` | Agent Workers | Orchestrator |
| `task.failed` | Agent Workers | Orchestrator |
| `retry.scheduled` | Orchestrator | Orchestrator |
| `dlq.events` | Retry Manager | Operator/tooling |
| `streaming.events` | Orchestrator, Agents | Streaming Gateway |
| `agent.heartbeat` | Agents | Monitor |

Consumer groups provide:
- **At-least-once delivery** — messages are not lost if a consumer crashes
- **Load balancing** — multiple workers share a stream's messages
- **PEL recovery** — XAUTOCLAIM reclaims messages from dead workers after idle timeout

### Persistence Layer — PostgreSQL

Tables:
- `tasks` — top-level task records
- `subtasks` — individual agent subtasks with dependency graph
- `execution_events` — ordered event log for each task (used for replay)
- `agent_metrics` — per-worker performance data for monitoring

SQLAlchemy async with asyncpg. The repository pattern (`services/orchestrator/repository.py`) keeps SQL out of business logic.

## Execution Lifecycle

```
1. Client submits task → POST /api/v1/tasks
2. Gateway: persist task (pending), XADD task.created, return 202
3. Client connects WebSocket /ws/tasks/{id}
4. Planner: XREADGROUP task.created
5. Planner: LLM call → subtask DAG
6. Planner: persist subtasks, XADD task.planned
7. Orchestrator: XREADGROUP task.planned, load into memory
8. Orchestrator scheduling loop: find ready subtasks
9. Orchestrator: XADD task.assigned {agent_type: retriever}
10. Retriever Worker: XREADGROUP task.assigned
11. Retriever: execute, XADD streaming.events (logs), XADD task.completed
12. Streaming Gateway: XREADGROUP streaming.events → WS push to client
13. Orchestrator: XREADGROUP task.completed, mark subtask done
14. Scheduling loop: Analyzer now has deps satisfied → dispatch
15. [Repeat for Analyzer, Writer, Validator]
16. All subtasks complete → Orchestrator marks task COMPLETED
17. Final streaming event → client receives task.completed
```

## Failure & Recovery

See [FailureHandling.md](FailureHandling.md) for the full failure taxonomy.

- **Agent crash mid-task:** Message stays in Redis PEL. XAUTOCLAIM reclaims after 30s idle. Task retried by another worker.
- **Orchestrator crash:** Task state rehydrated from PostgreSQL on restart. In-flight subtasks in PEL are reclaimed.
- **Planner failure:** `task.created` message stays un-ACK'd. Reprocessed after recovery.
- **LLM timeout:** Caught at agent level, failure event published, retry scheduled with backoff.
- **Max retries exceeded:** Subtask routed to DLQ. Task marked FAILED. DLQ events preserved for operator inspection.

## Scaling Architecture

```
                    ┌─────────────────────────────────┐
                    │        Load Balancer             │
                    └──────────┬──────────┬────────────┘
                               │          │
                    ┌──────────▼──┐  ┌────▼──────────┐
                    │ API Gateway │  │  Streaming GW  │
                    │  (N replicas)│  │  (N replicas)  │
                    └──────────┬──┘  └────┬───────────┘
                               │          │
                    ┌──────────▼──────────▼────────────┐
                    │          Redis Streams            │
                    │   (Consumer Groups per service)   │
                    └──┬───────┬────────┬──────────────┘
                       │       │        │
               ┌───────▼──┐ ┌──▼──┐ ┌───▼──────────────────┐
               │ Planner  │ │Orch │ │ Agent Workers (N each) │
               │(1-N inst)│ │(1)  │ │ Retriever×N           │
               └───────┬──┘ └──┬──┘ │ Analyzer×N            │
                       │       │    │ Writer×N               │
               ┌───────▼───────▼──┐ │ Validator×N            │
               │    PostgreSQL     │ │ Planner×N              │
               │  (Primary +      │ └───────────────────────┘
               │   Read Replicas) │
               └──────────────────┘
```

## CAP Theorem Considerations

NexusFlow prioritizes **Availability + Partition Tolerance (AP)** over strict consistency:

- Task status is eventually consistent. If the orchestrator processes a subtask completion after a brief network partition, the DB update happens when connectivity resumes.
- We don't use distributed transactions across Redis and PostgreSQL. If a Redis XACK succeeds but the DB update fails, we'll re-process the event (idempotency guards prevent double-completion).
- We accept that Redis and PostgreSQL can briefly show different views of task state.

## Concurrency Model

All services are asyncio-based. Key concurrency constraints:

- **Orchestrator:** Single async loop for scheduling. `asyncio.Semaphore` caps concurrent subtask dispatches. Not thread-safe — run as a single process.
- **Agent workers:** One asyncio event loop per worker process. LLM calls are awaited (non-blocking). Multiple concurrent subtasks are handled naturally by asyncio.
- **Gateway:** uvicorn with multiple workers. Each worker is an independent process with its own event loop.
- **Streaming:** Single-process, single-loop. The Redis broadcast loop runs as a background asyncio task alongside WebSocket handlers.
