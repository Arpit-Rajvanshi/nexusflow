"""
Analyzer Agent — processes retrieved information and extracts structured insights.

Receives raw context from Retriever, performs pattern extraction, comparison,
summarization, and semantic reasoning. Output feeds directly into Writer.

Key design choice: The analyzer does NOT call external APIs or fetch data.
That's Retriever's job. Analyzer operates purely on what it was given.
This separation makes the system easier to test and debug — you can replay
a failed analysis with different LLM parameters without re-fetching data.

Confidence scoring:
  The analyzer produces a confidence score for its output. If confidence
  is below 0.6, the orchestrator can optionally trigger a re-retrieval pass
  with a more targeted query. (Not implemented in v1 — tracked as TODO.)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from nexusflow.agents.base import BaseAgent
from nexusflow.shared.models.task import AgentType, Subtask

logger = logging.getLogger(__name__)

ANALYZER_SYSTEM_PROMPT = """You are a specialized data analysis agent in a multi-agent AI system.
You receive raw retrieved information and must extract structured insights.

Your job:
1. Identify key patterns, trends, and relationships in the data
2. Compare and contrast different data points or sources
3. Extract quantitative metrics where available
4. Flag contradictions or data quality issues
5. Produce a structured analysis ready for a writer to synthesize

Return JSON:
{
  "summary": "2-3 sentence executive summary",
  "key_findings": [{"finding": "...", "evidence": "...", "confidence": 0.9}, ...],
  "patterns": ["pattern 1", "pattern 2", ...],
  "comparisons": [{"item_a": "...", "item_b": "...", "comparison": "..."}],
  "metrics": {"metric_name": value, ...},
  "data_quality_notes": ["any issues with source data"],
  "analysis_confidence": 0.85,
  "recommended_focus_areas": ["area 1", "area 2"]
}"""


class AnalyzerAgent(BaseAgent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.ANALYZER

    async def execute(self, subtask: Subtask) -> Dict[str, Any]:
        # Pull context from parent task input and any retriever outputs
        # passed through the subtask's input_data
        task_desc = subtask.input_data.get("task_description", "")
        retrieved_context = subtask.input_data.get("retrieved_context", "")
        raw_data = subtask.input_data.get("raw_data", "")

        # Combine available context
        context_for_analysis = retrieved_context or raw_data or task_desc

        await self._publish_log(
            subtask,
            f"Analyzing {len(context_for_analysis)} chars of context"
        )

        user_prompt = (
            f"Task to analyze: {task_desc[:300]}\n\n"
            f"Subtask focus: {subtask.description}\n\n"
            f"Source material:\n{context_for_analysis[:4000]}\n\n"
            "Produce structured analysis as JSON."
        )

        response = await self._llm.complete_with_metadata(
            system_prompt=ANALYZER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=3500,
        )

        result = self._parse_analysis(response.content)

        # Stream key findings as partial output
        for finding in result.get("key_findings", [])[:3]:
            await self._publish_partial_output(
                subtask, f"Finding: {finding.get('finding', '')}"
            )

        await self._publish_log(
            subtask,
            f"Analysis complete — confidence: {result.get('analysis_confidence', 0):.2f}"
        )

        result["_tokens_used"] = response.total_tokens
        result["_cost_usd"] = response.estimated_cost_usd
        return result

    def _parse_analysis(self, content: str) -> Dict[str, Any]:
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[1:-1])
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("AnalyzerAgent: JSON parse failed, wrapping raw response")
            return {
                "summary": content[:300],
                "key_findings": [{"finding": content[:200], "evidence": "", "confidence": 0.5}],
                "patterns": [],
                "analysis_confidence": 0.5,
                "parse_error": True,
            }
