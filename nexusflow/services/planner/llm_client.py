from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from nexusflow.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def estimated_cost_usd(self) -> float:
        COST_PER_TOKEN: Dict[str, Dict[str, float]] = {
            "gpt-4o": {"in": 5.0 / 1_000_000, "out": 15.0 / 1_000_000},
            "gpt-4o-mini": {"in": 0.15 / 1_000_000, "out": 0.60 / 1_000_000},
            "gpt-3.5-turbo": {"in": 0.5 / 1_000_000, "out": 1.5 / 1_000_000},
        }
        pricing = COST_PER_TOKEN.get(self.model, {"in": 0.01 / 1000, "out": 0.03 / 1000})
        return (self.tokens_in * pricing["in"]) + (self.tokens_out * pricing["out"])


class LLMClient:
    """Async LLM client supporting OpenAI and OpenAI-compatible local providers."""

    def __init__(self) -> None:
        self._settings = get_settings().llm
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self._settings.provider in ("openai", "local"):
            from openai import AsyncOpenAI

            base_url = (
                self._settings.local_base_url
                if self._settings.provider == "local"
                else self._settings.openai_base_url
            )
            api_key = (
                "local-key"
                if self._settings.provider == "local"
                else self._settings.openai_api_key
            )
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self._settings.provider}")

        return self._client

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: Optional[str] = None,
    ) -> str:
        """Return the response text for a completion request."""
        response = await self.complete_with_metadata(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        return response.content

    async def complete_with_metadata(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Full completion with token tracking and exponential backoff on rate limits."""
        resolved_model = model or (
            self._settings.local_model
            if self._settings.provider == "local"
            else self._settings.openai_model
        )

        api_key = self._settings.openai_api_key
        is_placeholder = not api_key or "your-openai-api-key" in api_key.lower() or api_key == "demo"
        if self._settings.provider == "openai" and is_placeholder:
            return self._generate_mock_response(system_prompt, user_prompt, resolved_model)

        client = await self._get_client()
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                usage = response.usage

                return LLMResponse(
                    content=content,
                    tokens_in=usage.prompt_tokens if usage else 0,
                    tokens_out=usage.completion_tokens if usage else 0,
                    model=resolved_model,
                    provider=self._settings.provider,
                )

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    delay = 2 ** attempt
                    logger.warning(
                        "LLM rate limited (attempt %d/%d), retrying in %ds",
                        attempt, max_retries, delay
                    )
                    await asyncio.sleep(delay)
                elif attempt == max_retries:
                    logger.error("LLM call failed after %d attempts: %s", max_retries, e)
                    raise
                else:
                    logger.warning("LLM call failed (attempt %d): %s", attempt, e)
                    await asyncio.sleep(1)

        raise RuntimeError("LLM client exhausted retries")

    def _generate_mock_response(self, system_prompt: str, user_prompt: str, model: str) -> LLMResponse:
        import json
        system_prompt_lower = system_prompt.lower()

        # 1. Decomposition Engine (Planner)
        if "task decomposition engine" in system_prompt_lower:
            content = json.dumps({
                "subtasks": [
                    {
                        "name": "Information Retrieval",
                        "description": "Fetch sources and factual material regarding the task.",
                        "agent_type": "retriever",
                        "depends_on": [],
                        "estimated_cost_tokens": 1000
                    },
                    {
                        "name": "Data Analysis",
                        "description": "Extract insights, key trends, and comparison points.",
                        "agent_type": "analyzer",
                        "depends_on": [0],
                        "estimated_cost_tokens": 1200
                    },
                    {
                        "name": "Report Writing",
                        "description": "Synthesize the analysis and context into a final markdown report.",
                        "agent_type": "writer",
                        "depends_on": [1],
                        "estimated_cost_tokens": 2500
                    },
                    {
                        "name": "Output Validation",
                        "description": "Validate the final report structure, accuracy, and completeness.",
                        "agent_type": "validator",
                        "depends_on": [2],
                        "estimated_cost_tokens": 800
                    }
                ],
                "reasoning": "We perform a standard linear pipeline: retrieve -> analyze -> write -> validate."
            }, indent=2)

        # 2. Retriever Agent
        elif "information retrieval agent" in system_prompt_lower:
            content = json.dumps({
                "sources": [
                    {
                        "title": "NexusFlow Architecture Documentation",
                        "url": "https://nexusflow.ai/docs/arch",
                        "content": "NexusFlow orchestrates DAGs of agent subtasks via Redis Streams and Postgres.",
                        "relevance_score": 0.98
                    },
                    {
                        "title": "Agent Coordination Patterns",
                        "url": "https://nexusflow.ai/docs/patterns",
                        "content": "Multi-agent systems execute subtasks concurrently using lock-free state machines.",
                        "relevance_score": 0.95
                    }
                ],
                "key_facts": [
                    "Uses Redis Streams for event pub/sub",
                    "Uses Postgres with SQLAlchemy for ACID state transactions",
                    "Implements dynamic re-planning on subtask failures"
                ],
                "raw_context": "NexusFlow is a high-performance orchestration system utilizing Redis and Postgres.",
                "retrieval_confidence": 0.95
            }, indent=2)

        # 3. Analyzer Agent
        elif "data analysis agent" in system_prompt_lower:
            content = json.dumps({
                "summary": "NexusFlow achieves high-performance asynchronous orchestration through lock-free state transitions and batch-scheduled LLM calls.",
                "key_findings": [
                    {"finding": "State transitions are strictly monitored via PostgreSQL transactions.", "evidence": "TaskRepository uses SQLAlchemy async sessions.", "confidence": 0.95},
                    {"finding": "Subtask scheduling latency is minimized using batching windows.", "evidence": "BatchScheduler combines parallel subtasks within 100ms.", "confidence": 0.90}
                ],
                "patterns": [
                    "Redis Streams for publish-subscribe event routing",
                    "Postgres for ACID state compliance"
                ],
                "comparisons": [
                    {"item_a": "Redis Streams", "item_b": "HTTP polling", "comparison": "Redis streams are event-driven, lowering CPU utilization under heavy load."}
                ],
                "metrics": {
                    "latency_reduction_percent": 35.5,
                    "throughput_tasks_per_sec": 120
                },
                "data_quality_notes": ["Retrieved context is complete and highly consistent."],
                "analysis_confidence": 0.95,
                "recommended_focus_areas": ["Benchmark under peak concurrent workloads", "Tune Redis Stream trim values"]
            }, indent=2)

        # 4. Technical Writer Agent
        elif "technical writer" in system_prompt_lower:
            content = """# NexusFlow System Performance Analysis

## Executive Summary
This report analyzes the asynchronous agentic orchestration model of NexusFlow. By combining Redis Streams and PostgreSQL state tracking, NexusFlow provides lock-free task transitions and batch scheduling, reducing overall network latency by 35.5%.

## Key Findings
- **Transactional State Safety**: Leveraging Postgres ACID guarantees prevents task execution concurrency conflicts.
- **Batching Optimization**: Combining multiple parallel tasks inside a 100ms window dramatically decreases the rate-limit pressure on downstream LLM providers.
- **Event-Driven Subtasks**: Redis Streams provides highly responsive subtask scheduling compared to legacy polling mechanisms.

## Detailed Analysis
### Architectural Layers
NexusFlow separates concerns into an API Gateway, an Orchestrator service, and individual worker agent runners. This decouples API ingestion from resource-intensive task processing.

### Event-Driven Scheduling
The event stream acts as a central hub where the Orchestrator publishes tasks and agents consume them asynchronously. This ensures that failures in agent runners do not affect the main API gateway availability.

## Comparative Analysis
| Metric | Redis Streams | HTTP Polling |
| --- | --- | --- |
| Throughput | 120 tasks/sec | 35 tasks/sec |
| Latency | < 5ms | > 200ms |
| CPU Overhead | Low | High |

## Conclusions & Recommendations
- **Adopt Stream Trimming**: Set appropriate max stream lengths to manage Redis memory usage.
- **Scale Worker Agents**: Deploy additional worker replicas for retriever and writer agents to address queuing bottlenecks."""

        # 5. Quality Assurance (Validator) Agent
        elif "quality assurance agent" in system_prompt_lower:
            content = json.dumps({
                "verdict": "pass",
                "overall_score": 9.2,
                "scores": {
                    "completeness": 9,
                    "accuracy": 9,
                    "coherence": 10,
                    "quality": 9
                },
                "hallucination_risk": "low",
                "issues": [],
                "warnings": [],
                "feedback_for_improvement": "",
                "confidence": 0.95
            }, indent=2)

        # 6. Re-planning Agent
        elif "re-planning agent" in system_prompt_lower:
            content = json.dumps({
                "plan_status": "on_track",
                "assessment": "Task execution is proceeding perfectly on schedule.",
                "recommended_adjustments": [],
                "risk_factors": [],
                "estimated_additional_cost_tokens": 0,
                "replanning_confidence": 0.95
            }, indent=2)

        # 7. Default fallback
        else:
            content = "Mock response generated successfully."

        return LLMResponse(
            content=content,
            tokens_in=100,
            tokens_out=200,
            model=model,
            provider="mock"
        )

