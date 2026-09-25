"""CLI adapter — subprocess-per-request (CGI-like)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any

from ...health import HealthResult, HealthStatus
from ..protocol import InterfaceDirection, Message
from .base import InterfaceAdapter

logger = logging.getLogger(__name__)


class CliAdapter(InterfaceAdapter):
    """CLI interface adapter.

    BACKEND: Each ``send()`` spawns the daemon command as a subprocess, passes
    the Message as JSON via stdin, and captures stdout as the response.
    Stateless — one subprocess per request.

    FRONTEND: ``DaemonWrapper`` is invoked as a CLI subprocess by an external
    caller. ``argv[1]`` maps to ``Message.action``, stdin maps to
    ``Message.payload``, stdout carries the serialised response.
    A disabled CLI frontend raises ``SystemExit(1)``.
    """

    def __init__(
        self,
        name: str,
        *,
        cmd: list[str] | None = None,
        direction: InterfaceDirection = InterfaceDirection.BIDIRECTIONAL,
    ) -> None:
        super().__init__(name)
        self.cmd = cmd or []
        self._direction = direction
        self._enabled = True

    # ── InterfaceAdapter ──────────────────────────────────────────────

    def configure(self) -> dict[str, str]:
        return {
            "HEARTH_PHOENIX_TRANSPORT": "cli_adapter",
            "HEARTH_PHOENIX_CLI_CMD": " ".join(self.cmd),
        }

    def start(self) -> None:
        self._enabled = True

    def stop(self) -> None:
        self._enabled = False

    def send(self, message: Message, timeout: float = 30.0) -> Message:
        if self._direction == InterfaceDirection.FRONTEND:
            return self._frontend_send(message, timeout)
        return self._backend_send(message, timeout)

    def health_check(self, timeout: float) -> HealthResult:
        if not self._enabled:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message="CLI adapter disabled",
            )
        if not self.cmd:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message="No CLI command configured",
            )
        try:
            result = subprocess.run(
                self.cmd + ["--health"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return HealthResult(
                    status=HealthStatus.HEALTHY,
                    message=result.stdout.strip(),
                )
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Exit code {result.returncode}",
            )
        except Exception as exc:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check error: {exc}",
            )

    def is_connected(self) -> bool:
        return self._enabled

    @property
    def direction(self) -> InterfaceDirection:
        return self._direction

    @property
    def supports_passthrough(self) -> bool:
        return True

    # ── Internal ──────────────────────────────────────────────────────

    def _backend_send(self, message: Message, timeout: float) -> Message:
        """Backend mode: spawn daemon command per request."""
        if not self.cmd:
            return Message(
                action="error",
                payload={"reason": "no_command_configured"},
                metadata={"source": self.name, "error_code": "NO_CMD"},
            )

        input_data = json.dumps({"action": message.action, "payload": message.payload})
        try:
            result = subprocess.run(
                self.cmd,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout.strip())
                except json.JSONDecodeError:
                    return Message(
                        action="error",
                        payload={"reason": "invalid_json_response", "raw": result.stdout.strip()},
                        metadata={"source": self.name, "error_code": "INVALID_JSON"},
                    )
                return Message(
                    action=data.get("action", "response"),
                    payload=data.get("payload", {}),
                    metadata={"source": self.name},
                )
            return Message(
                action="error",
                payload={
                    "reason": "subprocess_failed",
                    "exit_code": result.returncode,
                    "stderr": result.stderr.strip(),
                },
                metadata={"source": self.name, "error_code": "SUBPROCESS_FAILED"},
            )
        except subprocess.TimeoutExpired:
            return Message(
                action="error",
                payload={"reason": "timeout"},
                metadata={"source": self.name, "error_code": "TIMEOUT"},
            )
        except Exception as exc:
            return Message(
                action="error",
                payload={"reason": str(exc)},
                metadata={"source": self.name, "error_code": "SEND_ERROR"},
            )

    def _frontend_send(self, message: Message, timeout: float) -> Message:
        """Frontend mode: one-shot invocation handled by the DaemonWrapper CLI."""
        # This is a placeholder — in real usage, the external caller invokes
        # the DaemonWrapper as a CLI.  The disabled state returns an error.
        if not self._enabled:
            raise SystemExit(1)
        return Message(
            action="error",
            payload={"reason": "cli_frontend_not_implemented"},
            metadata={"source": self.name, "error_code": "NOT_IMPLEMENTED"},
        )
