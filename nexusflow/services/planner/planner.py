from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.task import (
    AgentType,
    Priority,
    RetryPolicy,
    Subtask,
    Task,
    TaskStatus,
)
from nexusflow.services.planner.llm_client import LLMClient

logger = logging.getLogger(__name__)

RESEARCH_REPORT_TEMPLATE = [
    {
        "name": "Information Retrieval",
        "description": "Gather relevant information, data, and sources for the task.",
        "agent_type": "retriever",
        "depends_on": [],
    },
    {
        "name": "Data Analysis",
        "description": "Analyze the retrieved information, extract patterns, and compare data.",
        "agent_type": "analyzer",
        "depends_on": [0],
    },
    {
        "name": "Report Writing",
        "description": "Synthesize the analysis into a structured, coherent report.",
        "agent_type": "writer",
        "depends_on": [1],
    },
    {
        "name": "Output Validation",
        "description": "Validate the report for accuracy, completeness, and coherence.",
        "agent_type": "validator",
        "depends_on": [2],
    },
]

PLANNER_SYSTEM_PROMPT = """You are a task decomposition engine for a multi-agent AI system.
Given a user task, decompose it into 2-8 atomic subtasks that can be executed by specialized agents.

Available agent types:
- retriever: fetches external information, documents, and data
- analyzer: processes and extracts insights from data
- writer: generates structured text output and reports
- validator: checks output quality, accuracy, and schema conformance
- planner: handles dynamic re-planning when context changes mid-execution

Rules:
1. Each subtask must be executable by exactly one agent type
2. Specify dependencies as a list of subtask indices (0-indexed)
3. Keep subtask descriptions concrete and actionable
4. Ensure the DAG is acyclic — circular dependencies are rejected
5. Output ONLY valid JSON, no explanation text

Output format:
{
  "subtasks": [
    {
      "name": "Short task name",
      "description": "Specific, actionable description",
      "agent_type": "retriever|analyzer|writer|validator|planner",
      "depends_on": [<list of 0-indexed subtask positions>],
      "estimated_cost_tokens": <rough LLM token estimate>
    }
  ],
  "reasoning": "Brief explanation of decomposition strategy"
}"""


class TaskPlanner:
    """Decomposes a Task into a DAG of Subtasks using LLM planning or templates."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client or LLMClient()
        self._settings = get_settings()

    async def plan(self, task: Task) -> List[Subtask]:
        """Return a list of Subtask objects with resolved ID-based dependencies."""
        logger.info("Planning task %s: %s", task.id, task.title[:80])

        raw_plan = self._check_template(task)
        if raw_plan is None:
            raw_plan = await self._llm_plan(task)

        subtasks = self._build_subtasks(task, raw_plan)
        logger.info("Task %s planned into %d subtasks", task.id, len(subtasks))
        return subtasks

    def _check_template(self, task: Task) -> Optional[List[Dict[str, Any]]]:
        keywords_research = {"research", "report", "analyze", "summarize", "compare", "trends"}
        description_lower = task.description.lower()
        if sum(1 for k in keywords_research if k in description_lower) >= 2:
            logger.debug("Using research report template for task %s", task.id)
            return RESEARCH_REPORT_TEMPLATE
        return None

    async def _llm_plan(self, task: Task) -> List[Dict[str, Any]]:
        user_prompt = (
            f"Task title: {task.title}\n\n"
            f"Task description: {task.description}\n\n"
            f"Priority: {task.priority.name}\n"
            f"Decompose this into atomic subtasks."
        )
        response_text = await self._llm.complete(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=2000,
        )
        return self._parse_llm_plan(response_text, task)

    def _parse_llm_plan(self, response_text: str, task: Task) -> List[Dict[str, Any]]:
        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])

            parsed = json.loads(cleaned)
            subtask_list = parsed.get("subtasks", parsed)
            if not isinstance(subtask_list, list):
                raise ValueError("Expected a list of subtasks")
            if not subtask_list:
                raise ValueError("Empty subtask list")
            return subtask_list

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(
                "LLM plan parse failed for task %s: %s. Falling back to research template.",
                task.id, str(e)
            )
            return RESEARCH_REPORT_TEMPLATE

    def _build_subtasks(
        self, task: Task, raw_plan: List[Dict[str, Any]]
    ) -> List[Subtask]:
        subtasks: List[Subtask] = []
        for item in raw_plan:
            agent_type_str = item.get("agent_type", "retriever")
            try:
                agent_type = AgentType(agent_type_str)
            except ValueError:
                logger.warning("Unknown agent type '%s', defaulting to retriever", agent_type_str)
                agent_type = AgentType.RETRIEVER

            subtask = Subtask(
                task_id=task.id,
                name=item.get("name", f"Subtask {len(subtasks)+1}"),
                description=item.get("description", ""),
                agent_type=agent_type,
                priority=task.priority,
                retry_policy=RetryPolicy(
                    max_attempts=self._settings.orchestrator.max_retries
                ),
                input_data={
                    "task_description": task.description,
                    "task_title": task.title,
                    "task_metadata": task.metadata,
                },
                depends_on=[],
            )
            subtasks.append(subtask)

        for i, (subtask, item) in enumerate(zip(subtasks, raw_plan)):
            raw_deps = item.get("depends_on", [])
            resolved_deps: List[str] = []
            for dep_idx in raw_deps:
                if isinstance(dep_idx, int) and 0 <= dep_idx < len(subtasks):
                    if dep_idx != i:
                        resolved_deps.append(subtasks[dep_idx].id)
                elif isinstance(dep_idx, str):
                    resolved_deps.append(dep_idx)
            subtask.depends_on = resolved_deps

        return subtasks
