# Failure Handling — NexusFlow

## Failure Taxonomy

We categorize failures by where they occur and how they're detected:

| Failure Type | Detection | Recovery |
|---|---|---|
| Agent crash (mid-task) | PEL idle timeout (XAUTOCLAIM) | Message reclaimed, re-assigned |
| Agent timeout | asyncio.wait_for timeout | Failure event published, retry |
| Agent logic error | Exception caught in base agent | Retry with backoff |
| LLM rate limit | 429 response in LLM client | Exponential backoff, retry |
| LLM API down | Connection error | Circuit breaker trips, DLQ |
| Orchestrator crash | External liveness probe | Restart, rehydrate from DB |
| Planner failure | Un-ACK'd message in PEL | Reprocessed after recovery |
| Redis unavailable | Connection error on XADD | Services enter degraded state |
| PostgreSQL unavailable | DB query exception | Error returned to client |
| Max retries exceeded | retry_count >= max_attempts | Route to DLQ |

## Retry Strategy

We use **exponential backoff with full jitter**:

```
delay = min(base_delay * (multiplier ^ attempt), max_delay) * (1 + jitter * random())
```

Default configuration:
- `base_delay_seconds`: 2.0
- `backoff_multiplier`: 2.0
- `max_delay_seconds`: 60.0
- `jitter`: 0.2 (20% randomness)
- `max_attempts`: 3

Example delays (attempt 1-3, no jitter):
- Attempt 1 fail → wait 2s
- Attempt 2 fail → wait 4s
- Attempt 3 fail → route to DLQ

**Why jitter matters:** Without it, if 100 tasks fail simultaneously (e.g., LLM API returns 503), they'd all retry at exactly the same time, creating a retry storm that amplifies the failure. Jitter spreads the retries across a window.

**Why we cap retries at 3:** More retries help for transient issues but hurt for systemic failures. At attempt 4+, you're probably in a situation where the LLM API is down or the task input is fundamentally bad. The right response is DLQ, not infinite retrying.

## Circuit Breaker

Each agent type has a sliding-window circuit breaker (in-process, not distributed):

```
CLOSED ──(failure rate > threshold)──► OPEN ──(recovery_timeout)──► HALF_OPEN
  ▲                                                                       │
  └──────────────────(probe succeeds)────────────────────────────────────┘
```

Parameters:
- `failure_threshold`: 0.5 (50% failure rate within window)
- `window_seconds`: 60
- `min_requests`: 5 (don't trip on 1-2 failures)
- `recovery_timeout`: 30s

When OPEN, the retry manager skips execution entirely and routes to DLQ immediately. This prevents a struggling downstream service from being overwhelmed by retry traffic.

**Limitation:** Circuit breaker state is per-process. If you run 3 orchestrator instances, each has independent breaker state. A distributed breaker (backed by Redis) would be more accurate but adds latency on every request. Acceptable trade-off for our scale.

## Dead-Letter Queue

When a subtask exceeds max retries or the circuit breaker is OPEN, it's sent to `dlq.events` with full context:

```json
{
  "subtask_id": "...",
  "task_id": "...",
  "agent_type": "retriever",
  "retry_count": 3,
  "reason": "LLM API connection timeout after 3 attempts",
  "input_data": { "..." },
  "retry_policy": { "max_attempts": 3, "base_delay_seconds": 2.0 }
}
```

DLQ events are:
- Persisted in Redis Streams (retained for 100k events, configurable)
- Visible in the dashboard's Failure Inspector page
- Available for manual replay via the API (TODO in v2: `POST /api/v1/tasks/{id}/replay`)

## Worker Crash Recovery

When a worker crashes while processing a subtask:

1. The Redis PEL entry stays (not ACK'd)
2. After `claim_idle_ms` (default 30s), XAUTOCLAIM transfers it to another active consumer
3. The subtask is re-processed from scratch (agents are stateless by design)
4. If `retry_count` was already at max, the reclaimed message gets routed to DLQ immediately

This is "at-least-once" processing. Idempotency is maintained by checking subtask status before writing results — if a subtask is already COMPLETED, a second completion event is ignored.

## Orchestrator Recovery

If the orchestrator crashes with active tasks:

1. On restart, it reads RUNNING tasks from PostgreSQL
2. Rehydrates in-memory DAG state from subtask records
3. Re-subscribes to Redis Streams consumer group
4. Scheduling loop resumes from current state
5. Agent PEL entries are either still active or will be reclaimed by XAUTOCLAIM

**Gap:** Events that fired during the downtime and are in Redis PEL will be re-processed. This can cause duplicate completion events. The state machine's terminal state check prevents double-completion, but there's a brief window where the orchestrator might double-dispatch a subtask. This is tracked as a known issue.

## Partial Task Recovery

If some subtasks complete before a failure, those results are preserved in PostgreSQL. On recovery, the orchestrator resumes from the last persisted state — completed subtasks don't re-run.

This works because:
1. Subtask status is persisted before ACK-ing the completion event
2. The scheduling loop skips subtasks that are already in terminal state
3. Retry count is persisted, so backoff delays are correctly applied after recovery

## Poison Message Handling

A "poison message" is a subtask that repeatedly causes worker crashes (not just LLM errors — actual panics or unhandled exceptions).

Detection: if a subtask's `retry_count` equals `max_attempts` on the first reclaim, that means the worker crashed before ACK-ing even one attempt. We don't have special handling for this yet beyond the normal DLQ routing.

TODO: Add a "crash count" field separate from "retry count" to distinguish LLM failures from worker crashes. Crash count > 2 should immediately route to DLQ without retrying.
