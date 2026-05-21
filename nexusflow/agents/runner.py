from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from nexusflow.shared.observability.logging import setup_logging

logger = logging.getLogger(__name__)


def build_agent(agent_type: str):
    """Factory: return the correct agent instance for a given type string."""
    from nexusflow.agents.retriever.agent import RetrieverAgent
    from nexusflow.agents.analyzer.agent import AnalyzerAgent
    from nexusflow.agents.writer.agent import WriterAgent
    from nexusflow.agents.validator.agent import ValidatorAgent
    from nexusflow.agents.planner_agent.agent import PlannerAgent

    registry = {
        "retriever": RetrieverAgent,
        "analyzer": AnalyzerAgent,
        "writer": WriterAgent,
        "validator": ValidatorAgent,
        "planner": PlannerAgent,
    }

    cls = registry.get(agent_type.lower())
    if cls is None:
        raise ValueError(
            f"Unknown agent type: '{agent_type}'. "
            f"Valid types: {list(registry.keys())}"
        )
    return cls()


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="NexusFlow Agent Runner")
    parser.add_argument(
        "--agent-type",
        default=os.environ.get("AGENT_TYPE", ""),
        help="Agent type to run (retriever/analyzer/writer/validator/planner)",
    )
    args = parser.parse_args()

    if not args.agent_type:
        print("ERROR: --agent-type or AGENT_TYPE env var required", file=sys.stderr)
        sys.exit(1)

    from nexusflow.shared.config.settings import get_settings
    settings = get_settings()
    setup_logging(
        f"agent-{args.agent_type}",
        level=settings.log_level,
        json_output=settings.is_production,
    )

    agent = build_agent(args.agent_type)
    loop = asyncio.get_running_loop()

    def _stop(*_):
        logger.info("Shutdown signal received for %s agent", args.agent_type)
        asyncio.create_task(agent.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    logger.info("Starting agent: %s", args.agent_type)
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
