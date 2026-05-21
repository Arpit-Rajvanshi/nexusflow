"""
Planner service entrypoint.

Listens on the task.created stream, decomposes tasks into subtasks,
persists the plan, and publishes to task.planned for the orchestrator.

This runs as a single process — task planning is CPU-light and doesn't
need horizontal scaling at our target load. If planning becomes a bottleneck
(e.g., LLM latency stacks up), run multiple planner instances. They share
the same consumer group so Redis distributes work automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.database import get_db, init_db, close_db
from nexusflow.shared.models.task import Task, TaskStatus
from nexusflow.shared.observability.logging import setup_logging
from nexusflow.shared.queue.redis_streams import (
    STREAM_TASK_CREATED,
    STREAM_TASK_PLANNED,
    RedisConnectionPool,
    RedisStreamConsumer,
    RedisStreamProducer,
)
from nexusflow.services.orchestrator.repository import TaskRepository
from nexusflow.services.orchestrator.state_machine import transition_task
from nexusflow.services.planner.planner import TaskPlanner

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging("planner", level=settings.log_level, json_output=settings.is_production)

    await init_db()
    redis = await RedisConnectionPool.get()

    worker_id = f"planner-{socket.gethostname()}-{os.getpid()}"
    producer = RedisStreamProducer(redis)
    consumer = RedisStreamConsumer(
        client=redis,
        group_name=f"{settings.redis.consumer_group}-planner",
        consumer_name=worker_id,
        streams=[STREAM_TASK_CREATED],
    )
    planner = TaskPlanner()
    running = True

    def _stop(*_):
        nonlocal running
        running = False
        consumer.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    logger.info("Planner service started: %s", worker_id)

    async for stream_name, msg_id, data in consumer.read_messages():
        if not running:
            break
        try:
            raw_task = data.get("task", data)
            if isinstance(raw_task, str):
                raw_task = json.loads(raw_task)

            task = Task.model_validate(raw_task)
            logger.info("Planning task %s: %s", task.id, task.title[:60])

            # Mark task as planning
            async with get_db() as session:
                repo = TaskRepository(session)
                await repo.update_status(task.id, TaskStatus.PLANNING)

            # Decompose into subtasks
            subtasks = await planner.plan(task)
            task.subtasks = subtasks

            # Persist subtasks
            async with get_db() as session:
                repo = TaskRepository(session)
                await repo.save_subtasks(subtasks)
                await repo.update_status(task.id, TaskStatus.PLANNED)

            # Publish planned task to orchestrator
            await producer.publish(
                STREAM_TASK_PLANNED,
                {"task": task.model_dump_json()},
            )

            await consumer.ack(stream_name, msg_id)
            logger.info(
                "Task %s planned → %d subtasks", task.id, len(subtasks)
            )

        except Exception as e:
            logger.error(
                "Planner failed on task: %s", str(e), exc_info=True
            )
            # Don't ACK — message will be reclaimed after idle timeout

    await RedisConnectionPool.close()
    await close_db()
    logger.info("Planner service shutdown")


if __name__ == "__main__":
    asyncio.run(main())
