"""Structured logging configuration for HearthPhoenix."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include extra fields passed via logging.info(..., extra={...})
        context: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
            ):
                context[key] = value
        if context:
            obj["context"] = context
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


def configure_logging(
    json_format: bool = False, level: str = "INFO"
) -> None:
    """Configure root logging for HearthPhoenix.

    Args:
        json_format: If True, use JSONFormatter for structured output.
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    handler = logging.StreamHandler(sys.stderr)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root = logging.getLogger("hearthphoenix")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def auto_configure() -> None:
    """Auto-configure logging from environment variables."""
    fmt = os.environ.get("HEARTH_PHOENIX_LOG_FORMAT", "text").lower()
    level = os.environ.get("HEARTH_PHOENIX_LOG_LEVEL", "INFO").upper()
    configure_logging(json_format=(fmt == "json"), level=level)
