"""FileHealthMonitor — polls a daemon heartbeat file for health (NOT an InterfaceAdapter)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ..health import HealthResult, HealthStatus

logger = logging.getLogger(__name__)


class FileHealthMonitor:
    """Polls a heartbeat file written by the wrapped daemon.

    This is a non-adapter component — it does NOT implement InterfaceAdapter.
    It cannot carry requests, so it does not participate in the
    frontend→backend→response data flow.  Its results appear in
    ``DaemonWrapper.status()["file_monitor"]`` but do NOT affect the
    DaemonWrapper state machine (backend health is canonical).
    """

    def __init__(self, path: str, stale_timeout: float = 30.0) -> None:
        self.path = path
        self.stale_timeout = stale_timeout

    def health_check(self) -> HealthResult:
        """Return HEALTHY if file exists and mtime is within stale_timeout.

        Returns:
            HEALTHY — file exists and was modified within stale_timeout.
            DEGRADED — file exists but is stale (mtime > stale_timeout).
            UNHEALTHY — file does not exist.
        """
        try:
            if not os.path.exists(self.path):
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Heartbeat file not found: {self.path}",
                )

            mtime = os.path.getmtime(self.path)
            age = time.time() - mtime

            if age > self.stale_timeout:
                return HealthResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Heartbeat file stale: {age:.1f}s since last update",
                )

            return HealthResult(
                status=HealthStatus.HEALTHY,
                message=f"Heartbeat file fresh ({age:.1f}s old)",
            )
        except Exception as exc:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Error reading heartbeat file: {exc}",
            )

    def read_status(self) -> dict[str, Any] | None:
        """Read and parse the heartbeat file contents as JSON.

        Returns:
            Parsed JSON dict, or None if the file cannot be read/parsed.
        """
        try:
            if not os.path.exists(self.path):
                return None
            with open(self.path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to read heartbeat file %s: %s", self.path, exc)
            return None
