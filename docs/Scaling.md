# Scaling — NexusFlow

## Design Targets

NexusFlow v1 is designed to handle:
- ~100 concurrent tasks
- ~500 subtasks in flight simultaneously
- ~50 concurrent WebSocket streaming connections
- LLM throughput limited by provider (GPT-4o: ~50 req/min on Tier 1)

These aren't hard limits — they're the targets that informed design decisions.

## What Scales Horizontally

**Agent Workers** — The easiest scale target. Each worker type reads from a shared consumer group. Add more containers:

```bash
docker compose up --scale worker-retriever=5 --scale worker-writer=3
```

Redis automatically distributes work. No configuration change needed.

**API Gateway** — Stateless. Run behind a load balancer. The only state is JWT validation (stateless by design) and in-memory rate limiting (per-process, see note below).

**Streaming Gateway** — Stateless per connection. WebSocket connections are maintained against the process that accepted them. Scale by adding instances behind a sticky-session load balancer, OR use a shared pub/sub mechanism (current approach: all instances read from Redis `streaming.events`).

## What Doesn't Scale Easily

**Orchestrator** — Currently designed as a single process. It holds active task DAG state in memory. Running two orchestrators would require distributed locking or state sharding to avoid scheduling the same subtask twice.

*Scaling path:* Shard tasks across orchestrator instances by task ID hash (`task_id % num_orchestrators`). Each orchestrator owns a subset of tasks. No coordination needed for scheduling.

**Planner** — Can technically run multiple instances (stateless), but LLM planning calls are slow (~2-5s each). Latency is the bottleneck, not throughput. Multiple planners help with concurrent planning, not individual task latency.

**Redis** — Single instance in our setup. Redis 7.x can handle ~100k+ ops/sec on modern hardware. Not a bottleneck at our target scale. Scaling Redis requires Redis Cluster (sharded) or switching to Kafka.

## Bottleneck Analysis

### 1. LLM API Rate Limits

At 100 concurrent tasks with 4 subtasks each = 400 concurrent LLM requests. GPT-4o Tier 1 allows ~50 req/min per API key.

**Mitigations:**
- Use `BatchScheduler` to combine requests where possible
- Add LLM request queuing with global concurrency cap
- Use `gpt-4o-mini` for cheaper subtasks (Retriever, validation)
- Add multiple API keys with round-robin routing

### 2. WebSocket Fanout

At 500 concurrent WebSocket connections, the streaming gateway process can become memory-bound. Each WebSocket costs ~200KB of process memory (buffer + SSL state).

**Mitigations currently in place:**
- Event buffers are capped at 100 events per connection
- Old events dropped when buffer fills (oldest-first)
- Ping timeout disconnects zombie connections

**Not yet implemented:**
- Connection pooling across streaming gateway instances
- Shared pub/sub (currently each instance reads all streaming events)

### 3. Redis Memory Under Heavy Streaming

`streaming.events` grows fast during heavy execution. With 100 tasks, each generating 50 log events + partial outputs = 5000 events/minute.

At MAXLEN=100k, Redis caps memory at roughly:
- ~100k * ~500 bytes/event ≈ 50MB of stream data

That's fine. But if you lower the flush interval or increase partial output frequency, it can grow faster than consumers drain it.

**Monitor with:** `redis-cli XLEN streaming.events`

### 4. PostgreSQL Write Amplification

Every subtask state change = 1 DB write. At 100 concurrent tasks × 4 subtasks × 3 state changes each = 1200 writes/task run. For 10 concurrent task runs = 12,000 writes.

PostgreSQL on modern hardware handles >50k simple writes/sec. Not a bottleneck at our scale.

**If it becomes a bottleneck:**
- Batch DB updates within the orchestrator (accumulate state changes, flush every 500ms)
- Use PostgreSQL COPY for bulk subtask inserts at planning time
- Add a read replica for dashboard queries

## Rate Limiting Note

Current rate limiting is in-memory per API gateway process. This means:
- If you run 3 gateway instances, a client gets 3x the rate limit
- Rate limit state is lost on process restart

For production with multiple gateways: replace with Redis-backed rate limiting using a sliding window counter per IP.

## Scaling Roadmap

| Milestone | Target | Required Changes |
|---|---|---|
| v1 (current) | 100 concurrent tasks | Single orchestrator, single Redis |
| v2 | 1,000 concurrent tasks | Sharded orchestrator, Redis Cluster |
| v3 | 10,000 concurrent tasks | Kafka instead of Redis Streams, distributed state |
