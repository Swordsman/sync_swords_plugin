"""Pipe adapter — stdin/stdout JSON lines protocol."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from typing import Any

from ...health import HealthResult, HealthStatus
from ..protocol import InterfaceDirection, Message
from .base import InterfaceAdapter

logger = logging.getLogger(__name__)


class PipeAdapter(InterfaceAdapter):
    """Pipe-based frontend (stdin→read, stdout→write) and backend (connect to daemon stdin/stdout).

    Wire format: JSON lines (newline-delimited JSON objects).
    """

    def __init__(
        self,
        name: str,
        *,
        direction: InterfaceDirection = InterfaceDirection.BIDIRECTIONAL,
    ) -> None:
        super().__init__(name)
        self._direction = direction
        self._proc: subprocess.Popen | None = None
        self._connected = False
        self._reader_thread: threading.Thread | None = None
        self._response_queue: "queue.Queue[bytes]" = self._make_queue()
        self._stop_reader = threading.Event()
        self._request_handler: Any = None

    def _make_queue(self):
        import queue
        return queue.Queue()

    # ── InterfaceAdapter ──────────────────────────────────────────────

    def configure(self) -> dict[str, str]:
        return {
            "HEARTH_PHOENIX_TRANSPORT": "pipe_adapter",
        }

    def start(self) -> None:
        if self._direction in (InterfaceDirection.FRONTEND, InterfaceDirection.BIDIRECTIONAL):
            self._connected = True
        if self._direction in (InterfaceDirection.BACKEND, InterfaceDirection.BIDIRECTIONAL):
            pass  # Needs set_process() to bind to a daemon

    def stop(self) -> None:
        self._connected = False
        self._stop_reader.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
            self._reader_thread = None
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            self._proc = None

    def send(self, message: Message, timeout: float = 30.0) -> Message:
        if self._direction == InterfaceDirection.FRONTEND:
            raise RuntimeError("PipeAdapter in FRONTEND mode does not support send()")
        return self._send_recv(message, timeout)

    def health_check(self, timeout: float) -> HealthResult:
        if not self._connected:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message="Pipe not connected",
            )
        resp = self._send_recv(
            Message(action="health", payload={}),
            timeout,
        )
        if resp.action == "error":
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=resp.payload.get("reason", "pipe health check failed"),
            )
        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="Pipe backend healthy",
        )

    def is_connected(self) -> bool:
        return self._connected

    @property
    def direction(self) -> InterfaceDirection:
        return self._direction

    @property
    def supports_passthrough(self) -> bool:
        return True

    # ── Internal ──────────────────────────────────────────────────────

    def set_process(self, proc: subprocess.Popen) -> None:
        """Bind this adapter to a daemon subprocess (backend mode)."""
        self._proc = proc
        self._connected = proc.poll() is None
        self._start_reader()

    def set_request_handler(self, handler: Any) -> None:
        """Set the handler for incoming requests (frontend mode)."""
        self._request_handler = handler

    def _start_reader(self) -> None:
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            while not self._stop_reader.is_set():
                line = self._proc.stdout.readline()
                if not line:
                    break
                self._response_queue.put(line)
        except Exception:
            pass

    def _send_recv(self, message: Message, timeout: float) -> Message:
        """Send a message and wait for a JSON-line response."""
        if self._proc is None or self._proc.stdin is None:
            return Message(
                action="error",
                payload={"reason": "pipe_not_open"},
                metadata={"source": self.name, "error_code": "PIPE_NOT_OPEN"},
            )
        try:
            line = json.dumps({"action": message.action, "payload": message.payload}) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
        except Exception as exc:
            self._connected = False
            return Message(
                action="error",
                payload={"reason": f"send_error: {exc}"},
                metadata={"source": self.name, "error_code": "SEND_ERROR"},
            )

        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                resp_line = self._response_queue.get(timeout=0.1)
            except Exception:
                if self._proc.poll() is not None:
                    break
                continue
            try:
                data = json.loads(resp_line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                return Message(
                    action="error",
                    payload={"reason": f"invalid_json: {exc}"},
                    metadata={"source": self.name, "error_code": "INVALID_JSON"},
                )
            return Message(
                action=data.get("action", "response"),
                payload=data.get("payload", {}),
                metadata={"source": self.name},
            )

        return Message(
            action="error",
            payload={"reason": "timeout"},
            metadata={"source": self.name, "error_code": "TIMEOUT"},
        )
