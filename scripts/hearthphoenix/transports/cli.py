"""CLI transport — invoke a command and check exit code for health."""

from __future__ import annotations

import logging
import subprocess

from ..health import HealthResult, HealthStatus
from .base import Transport

logger = logging.getLogger(__name__)


class CliTransport(Transport):
    """Run a command to check worker health (one-shot or polling)."""

    def __init__(self, health_cmd: list[str] | None = None) -> None:
        self.health_cmd = health_cmd or []

    def configure(self) -> dict[str, str]:
        return {
            "HEARTH_PHOENIX_TRANSPORT": "cli",
            "HEARTH_PHOENIX_CLI_HEALTH_CMD": " ".join(self.health_cmd),
        }

    def on_supervisor_start(self) -> None:
        pass

    def health_check(self, timeout: float) -> HealthResult:
        if not self.health_cmd:
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message="No health command configured"
            )
        try:
            result = subprocess.run(
                self.health_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return HealthResult(
                    status=HealthStatus.HEALTHY, message=result.stdout.strip()
                )
            else:
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Exit code {result.returncode}: {result.stderr.strip()}",
                )
        except Exception as exc:
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message=f"Command failed: {exc}"
            )

    def shutdown(self, graceful: bool = True) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def on_supervisor_stop(self) -> None:
        pass
