"""
Planner Agent — handles dynamic re-planning mid-execution.

Unlike the TaskPlanner service (which does initial decomposition),
the PlannerAgent runs as part of the execution DAG. It's invoked when:
  1. Initial execution reveals missing information
  2. An earlier subtask's output suggests the plan needs adjustment
  3. Validation fails and the task needs re-scoping
  4. Task complexity was underestimated during initial planning

This is the "adaptive execution" component. Instead of failing the entire
task, the planner agent can mutate the remaining subtask graph.

Current limitations:
  - The planner agent can suggest a revised plan in its output, but the
    orchestrator in v1 doesn't act on it — it's logged for the operator.
  - Full adaptive re-planning is the most complex feature in this system
    and is explicitly deferred to v2. The interfaces are designed to support
    it when we get there.
  - This is an honest engineering call: ship working v1, add complexity later.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from nexusflow.agents.base import BaseAgent
from nexusflow.shared.models.task import AgentType, Subtask

logger = logging.getLogger(__name__)

PLANNER_AGENT_SYSTEM_PROMPT = """You are a dynamic re-planning agent in a multi-agent AI system.
You receive the current execution state and decide if the plan needs adjustment.

Your output should:
1. Assess whether the current execution is on track
2. Identify any missing information or scope gaps
3. Recommend specific adjustments to the remaining subtasks
4. Estimate the impact of any plan changes on timeline and cost

Return JSON:
{
  "plan_status": "on_track" | "needs_adjustment" | "scope_change_required",
  "assessment": "Brief description of current state",
  "recommended_adjustments": [
    {
      "action": "add_subtask" | "modify_subtask" | "skip_subtask",
      "description": "What to change and why",
      "agent_type": "retriever|analyzer|writer|validator",
      "priority": "high|normal|low"
    }
  ],
  "risk_factors": ["risk 1", "risk 2"],
  "estimated_additional_cost_tokens": 0,
  "replanning_confidence": 0.8
}"""


class PlannerAgent(BaseAgent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.PLANNER

    async def execute(self, subtask: Subtask) -> Dict[str, Any]:
        task_desc = subtask.input_data.get("task_description", "")
        execution_state = subtask.input_data.get("execution_state", {})
        completed_outputs = subtask.input_data.get("completed_outputs", [])

        await self._publish_log(subtask, "Evaluating execution state for re-planning...")

        state_summary = json.dumps(execution_state, indent=2)[:1000] if execution_state else "No state provided"
        outputs_summary = "\n".join(
            str(o)[:200] for o in completed_outputs[:5]
        ) if completed_outputs else "No completed outputs"

        user_prompt = (
            f"Original task: {task_desc[:400]}\n\n"
            f"Current execution state:\n{state_summary}\n\n"
            f"Completed subtask outputs:\n{outputs_summary}\n\n"
            "Assess and produce a re-planning recommendation as JSON."
        )

        response = await self._llm.complete_with_metadata(
            system_prompt=PLANNER_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=2000,
        )

        result = self._parse_plan(response.content)
        plan_status = result.get("plan_status", "on_track")
        adjustments = result.get("recommended_adjustments", [])

        await self._publish_log(
            subtask,
            f"Re-planning assessment: {plan_status} — {len(adjustments)} adjustments recommended"
        )

        if plan_status != "on_track" and adjustments:
            logger.info(
                "Planner agent recommends %d adjustments for task. "
                "Note: v1 orchestrator does not auto-apply these — operator review needed.",
                len(adjustments)
            )
            for adj in adjustments[:3]:
                await self._publish_partial_output(
                    subtask, f"Adjustment: {adj.get('description', '')}"
                )

        result["_tokens_used"] = response.total_tokens
        result["_cost_usd"] = response.estimated_cost_usd
        return result

    def _parse_plan(self, content: str) -> Dict[str, Any]:
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[1:-1])
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {
                "plan_status": "on_track",
                "assessment": content[:200],
                "recommended_adjustments": [],
                "replanning_confidence": 0.4,
                "parse_error": True,
            }
