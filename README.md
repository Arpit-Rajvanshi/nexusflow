# NexusFlow

**An agentic AI orchestration platform for multi-step, multi-agent task execution.**

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

NexusFlow is a distributed backend system that accepts complex tasks ("Research AI chip startups and generate an investor report"), decomposes them into subtasks using an LLM-powered planner, coordinates specialized agents to execute those subtasks asynchronously, and streams live execution events back to connected clients.

This is not a tutorial project. It's built the way an internal orchestration system at a mid-stage AI company would be: async-first, fault-tolerant, horizontally scalable, and operationally observable.

## What It Does

A user submits a task like:

> *"Research the top 5 AI chip startups, compare their funding rounds, analyze competitive positioning, and generate an investor briefing document."*

NexusFlow:
1. Accepts the task via REST API, persists it, returns a task ID
2. Decomposes the task into a DAG of subtasks (Retriever → Analyzer → Writer → Validator)
3. Distributes subtasks to specialized agent workers via Redis Streams
4. Streams live execution logs and partial outputs to the client via WebSocket
5. Persists all events for replay and debugging
6. Handles retries with exponential backoff, circuit breaking, and DLQ routing
7. Delivers the completed report and a full execution timeline

## Architecture

```
Client → API Gateway → Redis Streams → Planner → Orchestrator → Agent Workers → PostgreSQL
                ↓                                      ↑
         Streaming Gateway ←─── Redis streaming.events ─┘
```

See [docs/Architecture.md](docs/Architecture.md) for the full distributed system design.

## Tech Stack

| Layer | Technology |
|---|---|
| API Gateway | FastAPI, uvicorn |
| Async runtime | Python asyncio |
| Queue / Event bus | Redis Streams (XADD/XREADGROUP) |
| Database | PostgreSQL, SQLAlchemy async, asyncpg |
| Migrations | Alembic |
| Streaming | WebSockets, SSE fallback |
| LLM | OpenAI SDK (GPT-4o) with local LLM abstraction |
| Frontend | Next.js 15, Tailwind CSS, Tanstack Query |
| Containers | Docker, Docker Compose |

**Explicitly NOT used:** LangChain, LangGraph, AutoGen, CrewAI, or any agent framework. All orchestration logic is hand-written.

## Quick Start

### Prerequisites
- Docker + Docker Compose
- An OpenAI API key (or a local LLM at an OpenAI-compatible endpoint)

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd nexusflow
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

### 2. Start everything

```bash
make up
```

This starts: PostgreSQL, Redis, API Gateway, Streaming Gateway, Orchestrator, Planner, all 5 agent workers, and the dashboard.

### 3. Open the dashboard

[http://localhost:3000](http://localhost:3000) — sign in with any username/password.

### 4. Submit a task via CLI

```bash
make submit-task
```

Or via the dashboard at [http://localhost:3000/dashboard/submit](http://localhost:3000/dashboard/submit).

### 5. Watch live execution

The dashboard's task detail page shows:
- Live DAG visualization (which subtasks are running)
- Streaming execution log (agent logs in real-time)
- Token/cost tracking
- Retry visualization

## Repository Structure

```
nexusflow/
├── services/
│   ├── gateway/        # FastAPI API gateway
│   ├── orchestrator/   # DAG execution engine
│   ├── planner/        # Task decomposition service
│   └── streaming/      # WebSocket/SSE gateway
├── agents/
│   ├── base.py         # Abstract base agent
│   ├── retriever/      # Information retrieval
│   ├── analyzer/       # Data analysis
│   ├── writer/         # Report generation
│   ├── validator/      # Output quality check
│   └── planner_agent/  # Dynamic re-planning
├── shared/
│   ├── config/         # Pydantic settings
│   ├── models/         # Domain models + ORM
│   ├── queue/          # Redis Streams client
│   ├── retry/          # Retry + circuit breaker
│   ├── batching/       # Manual batch scheduler
│   └── observability/  # Structured logging
├── apps/
│   └── dashboard/      # Next.js frontend
├── infra/              # Dockerfiles, DB init
├── tests/              # Unit + integration tests
├── benchmarks/         # Locust load tests
├── docs/               # Architecture documentation
├── alembic/            # DB migrations
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Key Design Decisions

**Redis Streams over Kafka:** Kafka would be better at high throughput but adds significant operational overhead. Redis Streams with consumer groups gives us persistent, replayable queues with zero extra infrastructure. If we hit 10k+ msg/sec we'd migrate.

**Single orchestrator process:** Running the DAG engine as a single process avoids distributed consensus complexity. Scale by sharding tasks across multiple orchestrator instances (not yet implemented), not by running multiple orchestrators on the same task.

**Manual batching:** The `BatchScheduler` aggregates LLM requests over 100ms windows. No framework involvement — it's a deque + asyncio futures + a flush loop. Reduces LLM API call overhead when many subtasks run concurrently.

**No agent framework:** AutoGen, LangGraph, etc. abstract orchestration in ways that make it hard to understand failure modes, add custom retry logic, or control execution precisely. Writing it ourselves is more code but far more debuggable.

See [docs/Architecture.md](docs/Architecture.md) for deeper reasoning.

## Development

```bash
make dev-setup      # Install deps, copy .env, install pre-commit hooks
make infra-up       # Start just postgres + redis
make gateway        # Run API gateway locally with hot reload
make test           # Run all tests
make test-cov       # Tests with HTML coverage report
make lint           # Ruff + black check
make typecheck      # mypy strict
```

## Scaling

To scale agent workers:

```bash
docker compose up --scale worker-retriever=3 --scale worker-analyzer=2
```

Redis consumer groups automatically distribute work across all instances of the same agent type.

See [docs/Scaling.md](docs/Scaling.md) for bottleneck analysis and scaling strategy.

## Documentation

| Document | Description |
|---|---|
| [Architecture.md](docs/Architecture.md) | Full system design with diagrams |
| [AsyncPipeline.md](docs/AsyncPipeline.md) | Async execution lifecycle |
| [FailureHandling.md](docs/FailureHandling.md) | Retry, circuit breaker, DLQ |
| [Scaling.md](docs/Scaling.md) | Scaling strategy and bottlenecks |
| [DeploymentGuide.md](docs/DeploymentGuide.md) | Production deployment |
| [API_REFERENCE.md](docs/API_REFERENCE.md) | Full REST API reference |

## License

MIT
