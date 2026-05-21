"""
Orchestrator service entrypoint.

Handles startup: DB init, Redis connectivity, and then hands off to the engine loop.
Signal handlers ensure graceful shutdown so in-flight tasks can finish.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.database import init_db, close_db
from nexusflow.shared.observability.logging import setup_logging
from nexusflow.shared.queue.redis_streams import RedisConnectionPool
from nexusflow.services.orchestrator.engine import OrchestratorEngine

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging("orchestrator", level=settings.log_level, json_output=settings.is_production)

    logger.info("Initializing orchestrator service...")
    await init_db()

    engine = OrchestratorEngine()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal():
        logger.info("Shutdown signal received — stopping gracefully")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    try:
        # Run engine and stop-event watch concurrently
        engine_task = asyncio.create_task(engine.start(), name="orchestrator-engine")
        await stop_event.wait()
        await engine.stop()
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
    finally:
        await RedisConnectionPool.close()
        await close_db()
        logger.info("Orchestrator shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
