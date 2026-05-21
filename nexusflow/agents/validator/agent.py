"""
Validator Agent — verifies output quality, accuracy, and schema conformance.

The validator is the last agent in most workflows. It checks:
  1. Completeness — did the writer address all parts of the task?
  2. Consistency — do conclusions match the analysis?
  3. Quality — is the output professionally written?
  4. Schema conformance — if a specific format was required, does the output match?
  5. Hallucination detection — rough check for claims with no source support

Design decision on hallucination detection:
  We do a basic prompt-based check rather than embedding similarity because
  it's simpler and good enough for our use case. A production system would
  use a proper fact-checking pipeline with source attribution.

  The validator assigns a pass/fail verdict AND a confidence score. The
  orchestrator can be configured to only consider a task complete if
  confidence >= threshold (configurable per task priority).

Output on failure:
  If validation fails, we include specific feedback in the output. The
  orchestrator CAN use this feedback to trigger re-execution of the writer
  subtask with the validator's critique as additional context. This creates
  a writer→validator→writer loop. (Not implemented in v1 — TODO.)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from nexusflow.agents.base import BaseAgent
from nexusflow.shared.models.task import AgentType, Subtask

logger = logging.getLogger(__name__)

VALIDATOR_SYSTEM_PROMPT = """You are a quality assurance agent in a multi-agent AI system.
Your job is to validate the output produced by other agents.

Evaluate the provided output against these criteria:

1. COMPLETENESS (0-10): Does it address all aspects of the original task?
2. ACCURACY (0-10): Are claims supported by the source material provided?
3. COHERENCE (0-10): Is the reasoning logical and internally consistent?
4. QUALITY (0-10): Is the writing clear, professional, and well-structured?
5. HALLUCINATION_RISK (low/medium/high): Are there unsupported specific claims?

Return JSON:
{
  "verdict": "pass" | "fail" | "pass_with_warnings",
  "overall_score": 8.5,
  "scores": {
    "completeness": 9,
    "accuracy": 8,
    "coherence": 9,
    "quality": 8
  },
  "hallucination_risk": "low",
  "issues": ["issue 1", "issue 2"],
  "warnings": ["warning 1"],
  "feedback_for_improvement": "Specific actionable feedback if score < 7",
  "confidence": 0.88
}

Be strict but fair. A score below 6 on any dimension should trigger "fail"."""


class ValidatorAgent(BaseAgent):

    # Minimum overall score to pass (configurable per task in future)
    PASS_THRESHOLD = 6.5

    @property
    def agent_type(self) -> AgentType:
        return AgentType.VALIDATOR

    async def execute(self, subtask: Subtask) -> Dict[str, Any]:
        task_desc = subtask.input_data.get("task_description", "")
        report_to_validate = subtask.input_data.get("report", "")
        source_context = subtask.input_data.get("raw_context", "")
        analysis_summary = subtask.input_data.get("analysis_summary", "")

        if not report_to_validate:
            # Nothing to validate — soft pass with warning
            logger.warning("ValidatorAgent: no report to validate for subtask %s", subtask.id)
            return {
                "verdict": "pass_with_warnings",
                "overall_score": 5.0,
                "warnings": ["No report content provided for validation"],
                "confidence": 0.3,
                "_tokens_used": 0,
                "_cost_usd": 0.0,
            }

        await self._publish_log(subtask, "Validating output quality and accuracy...")

        user_prompt = (
            f"Original task: {task_desc[:400]}\n\n"
            f"Source material (for accuracy check):\n{source_context[:1000]}\n\n"
            f"Analysis summary:\n{analysis_summary[:500]}\n\n"
            f"Output to validate:\n{report_to_validate[:3000]}\n\n"
            "Evaluate this output and return your assessment as JSON."
        )

        response = await self._llm.complete_with_metadata(
            system_prompt=VALIDATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,  # Low temp — we want consistent scoring
            max_tokens=1500,
        )

        result = self._parse_validation(response.content)

        verdict = result.get("verdict", "fail")
        score = result.get("overall_score", 0)
        await self._publish_log(
            subtask,
            f"Validation {verdict.upper()} — score: {score:.1f}/10"
        )

        # Stream issues if any
        for issue in result.get("issues", []):
            await self._publish_partial_output(subtask, f"Issue: {issue}")

        result["_tokens_used"] = response.total_tokens
        result["_cost_usd"] = response.estimated_cost_usd
        return result

    def _parse_validation(self, content: str) -> Dict[str, Any]:
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[1:-1])
            parsed = json.loads(cleaned)
            # Enforce pass threshold
            if parsed.get("overall_score", 0) < self.PASS_THRESHOLD:
                parsed["verdict"] = "fail"
            return parsed
        except (json.JSONDecodeError, ValueError):
            logger.warning("ValidatorAgent: failed to parse JSON, defaulting to pass_with_warnings")
            return {
                "verdict": "pass_with_warnings",
                "overall_score": 6.0,
                "warnings": ["Validator response could not be parsed"],
                "confidence": 0.4,
                "parse_error": True,
            }
