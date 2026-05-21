import logging
import structlog
from unittest.mock import patch, MagicMock

from nexusflow.shared.observability.logging import (
    setup_logging,
    _add_service_name,
    bind_task_context,
    clear_task_context,
    get_logger
)


def test_add_service_name_processor():
    processor = _add_service_name("test-service")
    event_dict = {"event": "hello"}
    result = processor(None, None, event_dict)
    assert result["service"] == "test-service"


def test_bind_and_clear_task_context():
    clear_task_context()

    bind_task_context(task_id="task-123", subtask_id="subtask-456")

    import structlog.contextvars
    ctx = structlog.contextvars.get_contextvars()
    assert ctx["task_id"] == "task-123"
    assert ctx["subtask_id"] == "subtask-456"

    clear_task_context()
    assert structlog.contextvars.get_contextvars() == {}


def test_get_logger():
    logger = get_logger("my-test-logger")
    assert hasattr(logger, "info") or isinstance(logger, structlog.BoundLoggerLazyProxy)


def test_setup_logging():
    with patch("logging.getLogger") as mock_get_logger, \
         patch("logging.StreamHandler") as mock_stream_handler:

        loggers_dict = {}
        def get_logger_mock(name=None):
            if name not in loggers_dict:
                loggers_dict[name] = MagicMock()
            return loggers_dict[name]

        mock_get_logger.side_effect = get_logger_mock

        setup_logging("test-service", level="DEBUG", json_output=True)

        mock_get_logger.assert_any_call()
        assert get_logger_mock(None).setLevel.call_args_list[0][0][0] == logging.DEBUG
        assert get_logger_mock("uvicorn.access").setLevel.call_args_list[0][0][0] == logging.WARNING
        assert get_logger_mock("sqlalchemy.engine").setLevel.call_args_list[0][0][0] == logging.WARNING
