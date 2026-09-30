"""Shared logging configuration for the AI Agent Lab applications."""

from __future__ import annotations

import logging
import os
import sys

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_APPLICATION_LOGGERS = ("ai_agent_lab",)


def setup_logging(*, default_level: str = "INFO", level_name: str | None = None) -> None:
    """Configure application logging, honoring an explicit level then LOG_LEVEL.

    Existing root handlers are retained and updated. A stdout handler is added
    only when the host has not configured logging already.
    """
    configured_level = level_name or os.getenv("LOG_LEVEL") or default_level
    normalized_level = configured_level.strip().upper()
    numeric_level = getattr(logging, normalized_level, logging.INFO)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric_level)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(numeric_level)

    _configure_application_loggers(numeric_level)
    logging.info("Logging configured with level: %s", logging.getLevelName(numeric_level))


def _configure_application_loggers(level: int) -> None:
    """Apply the selected level to all AI Agent Lab modules."""
    for logger_name in _APPLICATION_LOGGERS:
        application_logger = logging.getLogger(logger_name)
        application_logger.setLevel(level)
        application_logger.propagate = True

    if level == logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.INFO)
        logging.getLogger("httpcore").setLevel(logging.INFO)
        logging.getLogger("httpcore2").setLevel(logging.INFO)
        logging.getLogger("openai").setLevel(logging.INFO)
