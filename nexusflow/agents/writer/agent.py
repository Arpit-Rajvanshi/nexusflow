"""
Writer Agent — synthesizes analysis into polished, structured output.

Takes the analysis results and produces the final deliverable:
  - Research reports
  - Comparative analyses
  - Summaries
  - Technical documentation

The writer is designed to produce Markdown output with clear structure.
We explicitly instruct it to use headers, tables, and bullet points
because these format well in the dashboard's streaming log panel.

Streaming note: Writer is the most latency-sensitive agent from a user
perspective because they're usually waiting to see the final report.
We stream partial output as the LLM generates each section.

In v2, we'd use the streaming API properly here (openai.stream=True)
to get true token-by-token streaming. For now, we simulate it by
splitting the response into chunks after generation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from nexusflow.agents.base import BaseAgent
from nexusflow.shared.models.task import AgentType, Subtask

logger = logging.getLogger(__name__)

WRITER_SYSTEM_PROMPT = """You are a specialized technical writer in a multi-agent AI system.
You receive structured analysis and produce polished, professional reports in Markdown.

Guidelines:
- Use clear headers (##, ###)
- Include executive summary at the top
- Use tables for comparative data
- Use bullet points for key findings
- Include specific numbers, dates, and names
- End with actionable recommendations
- Write in an authoritative, professional tone
- Length: comprehensive but not padded — aim for quality over quantity

Structure:
# [Report Title]

## Executive Summary
[2-3 sentences]

## Key Findings
[Bullet points with evidence]

## Detailed Analysis
[Sections per major topic]

## Comparative Analysis
[Tables or structured comparison if applicable]

## Conclusions & Recommendations
[Actionable next steps]"""


class WriterAgent(BaseAgent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.WRITER

    async def execute(self, subtask: Subtask) -> Dict[str, Any]:
        task_title = subtask.input_data.get("task_title", "Analysis Report")
        task_desc = subtask.input_data.get("task_description", "")
        analysis_data = subtask.input_data.get("analysis_results", {})
        retrieved_sources = subtask.input_data.get("retrieved_sources", [])

        await self._publish_log(subtask, "Synthesizing final report...")

        # Build rich context for the writer
        analysis_text = self._format_analysis(analysis_data)
        sources_text = self._format_sources(retrieved_sources)

        user_prompt = (
            f"Write a comprehensive report on: {task_title}\n\n"
            f"Original task: {task_desc[:400]}\n\n"
            f"Analysis results:\n{analysis_text}\n\n"
            f"Source material for citations:\n{sources_text[:1500]}"
        )

        response = await self._llm.complete_with_metadata(
            system_prompt=WRITER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.6,
            max_tokens=4000,
        )

        report_content = response.content

        # Simulate streaming by publishing chunks every ~200 chars
        await self._stream_report_chunks(subtask, report_content)

        result = {
            "report": report_content,
            "format": "markdown",
            "word_count": len(report_content.split()),
            "section_count": report_content.count("\n##"),
            "_tokens_used": response.total_tokens,
            "_cost_usd": response.estimated_cost_usd,
        }

        await self._publish_log(
            subtask,
            f"Report generated — {result['word_count']} words, "
            f"{result['section_count']} sections"
        )
        return result

    async def _stream_report_chunks(self, subtask: Subtask, content: str) -> None:
        """Publish report in chunks to simulate streaming to the client."""
        chunk_size = 200
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            await self._publish_partial_output(subtask, chunk)
            await asyncio.sleep(0.05)  # Simulate progressive generation

    def _format_analysis(self, analysis: dict) -> str:
        if not analysis:
            return "No structured analysis available."
        parts = []
        if "summary" in analysis:
            parts.append(f"Summary: {analysis['summary']}")
        if "key_findings" in analysis:
            parts.append("Key Findings:")
            for f in analysis["key_findings"][:10]:
                parts.append(f"  - {f.get('finding', '')}")
        if "metrics" in analysis:
            parts.append(f"Metrics: {analysis['metrics']}")
        return "\n".join(parts)

    def _format_sources(self, sources: list) -> str:
        if not sources:
            return "No source material available."
        lines = []
        for s in sources[:5]:
            title = s.get("title", "Unknown")
            content = s.get("content", "")[:300]
            lines.append(f"[{title}]: {content}")
        return "\n".join(lines)
