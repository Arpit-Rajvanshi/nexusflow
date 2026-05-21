from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def setup_logging(service_name: str, level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog for the given service. Call once at application startup."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.CallsiteParameterAdder(
            [structlog.processors.CallsiteParameter.FILENAME,
             structlog.processors.CallsiteParameter.LINENO]
        ),
        _add_service_name(service_name),
    ]

    if json_output:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *shared_processors,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def _add_service_name(name: str):
    """Structlog processor that injects the service name into every log record."""
    def processor(logger, method, event_dict):  # noqa: ANN001
        event_dict["service"] = name
        return event_dict
    return processor


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_task_context(task_id: str, subtask_id: str | None = None) -> None:
    """Bind task context to the current async context."""
    ctx: dict[str, Any] = {"task_id": task_id}
    if subtask_id:
        ctx["subtask_id"] = subtask_id
    structlog.contextvars.bind_contextvars(**ctx)


def clear_task_context() -> None:
    structlog.contextvars.clear_contextvars()
