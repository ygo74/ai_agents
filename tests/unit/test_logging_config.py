from __future__ import annotations

import io
import logging

from ai_agent_lab.core.observability.logging_config import setup_logging


def test_setup_logging_uses_environment_and_is_idempotent(monkeypatch) -> None:
    root_logger = logging.getLogger()
    application_logger = logging.getLogger("ai_agent_lab")
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    output = io.StringIO()

    monkeypatch.setattr(root_logger, "handlers", [])
    monkeypatch.setattr(root_logger, "level", logging.WARNING)
    monkeypatch.setattr(application_logger, "level", logging.WARNING)
    monkeypatch.setattr(application_logger, "propagate", False)
    monkeypatch.setattr(httpx_logger, "level", logging.DEBUG)
    monkeypatch.setattr(httpcore_logger, "level", logging.DEBUG)
    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setenv("LOG_LEVEL", "debug")

    setup_logging(default_level="ERROR")
    setup_logging(default_level="ERROR")

    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0], logging.StreamHandler)
    assert root_logger.handlers[0].stream is output
    assert root_logger.handlers[0].level == logging.DEBUG
    assert root_logger.handlers[0].formatter is not None
    assert "%(asctime)s" in root_logger.handlers[0].formatter._fmt
    assert application_logger.level == logging.DEBUG
    assert application_logger.propagate is True
    assert httpx_logger.level == logging.INFO
    assert httpcore_logger.level == logging.INFO
    assert "Logging configured with level: DEBUG" in output.getvalue()


def test_setup_logging_updates_existing_handlers_without_adding_another(monkeypatch) -> None:
    root_logger = logging.getLogger()
    existing_handler = logging.StreamHandler(io.StringIO())

    monkeypatch.setattr(root_logger, "handlers", [existing_handler])
    monkeypatch.setattr(root_logger, "level", logging.WARNING)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    setup_logging(default_level="ERROR")

    assert root_logger.level == logging.ERROR
    assert root_logger.handlers == [existing_handler]
    assert existing_handler.level == logging.ERROR
