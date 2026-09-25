"""Signal handling utilities for workers."""

from __future__ import annotations

import logging
import signal
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)


def install_graceful_shutdown(handler: Callable[[], None]) -> None:
    """Install SIGTERM/SIGINT handlers that call *handler* before exiting."""

    def _on_signal(signum: int, frame: Any) -> None:
        logger.info("Caught signal %s", signum)
        try:
            handler()
        except Exception:
            logger.exception("Graceful shutdown handler failed")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
