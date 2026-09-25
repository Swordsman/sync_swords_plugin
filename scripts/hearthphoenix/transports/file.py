"""Shared file transport — worker writes heartbeat, parent polls."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid

from ..health import HealthResult, HealthStatus
from .base import Transport

logger = logging.getLogger(__name__)


class FileTransport(Transport):
    """Worker writes JSON heartbeat to a shared file; supervisor polls it."""

    HEARTBEAT_FILE = "hearthphoenix_heartbeat.json"

    def __init__(self, heartbeat_path: str | None = None) -> None:
        self.heartbeat_path = heartbeat_path or os.path.join(
            tempfile.gettempdir(), f"hearthphoenix_{uuid.uuid4().hex[:8]}_heartbeat.json"
        )

    def configure(self) -> dict[str, str]:
        return {
            "HEARTH_PHOENIX_TRANSPORT": "file",
            "HEARTH_PHOENIX_HEARTBEAT_PATH": self.heartbeat_path,
        }

    def on_supervisor_start(self) -> None:
        pass

    def health_check(self, timeout: float) -> HealthResult:
        try:
            if not os.path.exists(self.heartbeat_path):
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Heartbeat file not found",
                )
            mtime = os.path.getmtime(self.heartbeat_path)
            if time.time() - mtime > timeout:
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Heartbeat file is stale",
                )
            with open(self.heartbeat_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            status = (
                HealthStatus.HEALTHY
                if data.get("status") == "ok"
                else HealthStatus.UNHEALTHY
            )
            return HealthResult(status=status, message=str(data))
        except Exception as exc:
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message=f"File error: {exc}"
            )

    def shutdown(self, graceful: bool = True) -> None:
        pass

    def is_connected(self) -> bool:
        if not os.path.exists(self.heartbeat_path):
            return False
        mtime = os.path.getmtime(self.heartbeat_path)
        return time.time() - mtime < 10.0

    def on_supervisor_stop(self) -> None:
        if os.path.exists(self.heartbeat_path):
            try:
                os.unlink(self.heartbeat_path)
            except OSError:
                pass
