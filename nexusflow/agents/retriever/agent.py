"""
Retriever Agent — gathers information from external sources.

Primary responsibility: given a query or topic, fetch relevant content
and return structured results for downstream agents to analyze.

In a real deployment this would connect to:
  - A search API (Tavily, SerpAPI, Brave)
  - Internal vector stores (Qdrant, Weaviate, Pinecone)
  - Document databases
  - Web scraping pipelines

For now: simulates retrieval with an LLM call that generates plausible
retrieved content. The interface is the same as real retrieval — swap
the implementation when integrating real data sources.

Design note on batching integration:
  The retriever registers itself with the BatchScheduler so that when
  multiple subtasks are all doing retrieval simultaneously, their LLM
  calls get batched together. The batch_scheduler is passed in at
  construction — allows replacing with a no-op in tests.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from nexusflow.agents.base import BaseAgent
from nexusflow.shared.models.task import AgentType, Subtask

logger = logging.getLogger(__name__)

RETRIEVER_SYSTEM_PROMPT = """You are a specialized information retrieval agent.
Given a research task, generate comprehensive, factual information as if you had
searched the web and accessed relevant documents.

Return a JSON object with:
{
  "sources": [
    {
      "title": "Source title",
      "url": "https://example.com/source",
      "content": "Relevant content excerpt",
      "relevance_score": 0.95
    }
  ],
  "key_facts": ["fact 1", "fact 2", ...],
  "raw_context": "Combined context for downstream analysis",
  "retrieval_confidence": 0.85
}

Be specific, factual, and thorough. Include numbers, names, and dates where relevant."""


class RetrieverAgent(BaseAgent):
    """
    Fetches and aggregates information relevant to a subtask.

    Output schema:
      sources: list of retrieved source objects
      key_facts: extracted key facts for quick reference
      raw_context: full text context for the analyzer
      retrieval_confidence: 0-1 confidence in retrieval quality
    """

    @property
    def agent_type(self) -> AgentType:
        return AgentType.RETRIEVER

    async def execute(self, subtask: Subtask) -> Dict[str, Any]:
        task_desc = subtask.input_data.get("task_description", "")
        task_title = subtask.input_data.get("task_title", "")
        query = subtask.description or task_desc

        await self._publish_log(subtask, f"Retrieving information for: {query[:100]}")

        user_prompt = (
            f"Research task: {task_title}\n\n"
            f"Specific retrieval query: {query}\n\n"
            f"Full task context: {task_desc[:500]}\n\n"
            "Retrieve comprehensive, factual information and return JSON."
        )

        response = await self._llm.complete_with_metadata(
            system_prompt=RETRIEVER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=3000,
        )

        await self._publish_log(
            subtask,
            f"Retrieval complete — {response.total_tokens} tokens used"
        )

        # Parse the response
        result = self._parse_retrieval_response(response.content, query)
        result["_tokens_used"] = response.total_tokens
        result["_cost_usd"] = response.estimated_cost_usd

        # Stream a preview of what was found
        source_count = len(result.get("sources", []))
        await self._publish_partial_output(
            subtask,
            f"Found {source_count} sources. Key facts: "
            + "; ".join(result.get("key_facts", [])[:3])
        )

        return result

    def _parse_retrieval_response(
        self, content: str, fallback_query: str
    ) -> Dict[str, Any]:
        """Parse JSON response with graceful fallback."""
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("RetrieverAgent: failed to parse JSON response, using fallback")
            return {
                "sources": [{"title": "Retrieved Content", "url": "", "content": content[:1000]}],
                "key_facts": [content[:200]],
                "raw_context": content,
                "retrieval_confidence": 0.5,
                "parse_error": True,
            }
