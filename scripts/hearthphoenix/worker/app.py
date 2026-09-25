"""WorkerApp base class."""

from __future__ import annotations

import logging
import os
import signal
import sys
from typing import Any, Callable

from ..health import HealthResult, HealthStatus
from ..transports import (
    CliTransport,
    FileTransport,
    PipeTransport,
    RestTransport,
    SocketTransport,
)
from ..transports.base import Transport

logger = logging.getLogger(__name__)


class WorkerApp:
    """Base class for HearthPhoenix worker applications."""

    def __init__(self) -> None:
        self._health_fn: Callable[[], dict[str, Any]] | None = None
        self._run_fn: Callable[[], None] | None = None
        self._shutdown_fn: Callable[[], None] | None = None
        self._shutdown_requested = False

    def health_check(
        self, fn: Callable[[], dict[str, Any]]
    ) -> Callable[[], dict[str, Any]]:
        """Decorator to register a health check function."""
        self._health_fn = fn
        return fn

    def run(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Decorator to register the main entry point."""
        self._run_fn = fn
        return fn

    def shutdown(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Decorator to register a shutdown handler."""
        self._shutdown_fn = fn
        return fn

    def _discover_transport(self) -> Transport:
        ttype = os.environ.get("HEARTH_PHOENIX_TRANSPORT", "rest")
        if ttype == "rest":
            port = int(
                os.environ.get("HEARTH_PHOENIX_REST_PORT", RestTransport.DEFAULT_PORT)
            )
            return RestTransport(port=port)
        elif ttype == "socket":
            path = os.environ.get("HEARTH_PHOENIX_SOCKET_PATH")
            return SocketTransport(socket_path=path)
        elif ttype == "file":
            path = os.environ.get("HEARTH_PHOENIX_HEARTBEAT_PATH")
            return FileTransport(heartbeat_path=path)
        elif ttype == "pipe":
            return PipeTransport()
        elif ttype == "cli":
            return CliTransport()
        else:
            raise RuntimeError(f"Unknown transport type: {ttype}")

    def _setup_signals(self) -> None:
        def _handler(signum: int, frame: Any) -> None:
            logger.info("Received signal %s, shutting down gracefully", signum)
            self._shutdown_requested = True
            if self._shutdown_fn is not None:
                try:
                    self._shutdown_fn()
                except Exception:
                    logger.exception("Shutdown handler failed")

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    def start(self) -> None:
        """Bootstrap the worker: setup signals, discover transport, run business logic."""
        self._setup_signals()
        transport = self._discover_transport()

        if self._run_fn is None:
            raise RuntimeError("No @run decorated function registered")

        logger.info("Worker starting with transport %s", type(transport).__name__)
        self._run_fn()

        logger.info("Worker exiting")
        sys.exit(0)
