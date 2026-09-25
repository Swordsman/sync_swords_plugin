"""Socket adapter — Unix domain / TCP, JSON lines protocol."""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from ...health import HealthResult, HealthStatus
from ..protocol import InterfaceDirection, Message
from .base import InterfaceAdapter

logger = logging.getLogger(__name__)


class SocketAdapter(InterfaceAdapter):
    """Socket-based frontend (listen+accept) and backend (connect+send).

    Uses Unix domain sockets on Linux/macOS and TCP on Windows (fallback).
    Wire format: JSON lines (newline-delimited JSON objects).
    """

    def __init__(
        self,
        name: str,
        *,
        socket_path: str | None = None,
        port: int | None = None,
        host: str = "127.0.0.1",
        direction: InterfaceDirection = InterfaceDirection.BIDIRECTIONAL,
    ) -> None:
        super().__init__(name)
        self._use_unix = hasattr(socket, "AF_UNIX")
        if self._use_unix:
            self.socket_path = socket_path or os.path.join(
                tempfile.gettempdir(), f"hp_{uuid.uuid4().hex[:8]}.sock"
            )
            self.port = port
        else:
            self.socket_path = ""
            self.port = port or 0
        self.host = host
        self._direction = direction
        self._sock: socket.socket | None = None
        self._server_sock: socket.socket | None = None
        self._connected = False
        self._running = False
        self._lock = threading.Lock()
        self._accept_thread: threading.Thread | None = None
        self._connection_handler: Callable[[Message], Message] | None = None

    # ── InterfaceAdapter ──────────────────────────────────────────────

    def configure(self) -> dict[str, str]:
        cfg: dict[str, str] = {
            "HEARTH_PHOENIX_TRANSPORT": "socket_adapter",
        }
        if self._use_unix:
            cfg["HEARTH_PHOENIX_SOCKET_PATH"] = self.socket_path
        else:
            cfg["HEARTH_PHOENIX_SOCKET_PORT"] = str(self.port or 9877)
            cfg["HEARTH_PHOENIX_SOCKET_HOST"] = self.host
        return cfg

    def start(self) -> None:
        if self._direction in (InterfaceDirection.FRONTEND, InterfaceDirection.BIDIRECTIONAL):
            self._start_frontend()
        if self._direction in (InterfaceDirection.BACKEND, InterfaceDirection.BIDIRECTIONAL):
            self._start_backend()

    def stop(self) -> None:
        self._running = False
        # Close the server socket to unblock accept()
        with self._lock:
            if self._server_sock is not None:
                try:
                    self._server_sock.close()
                except Exception:
                    pass
                self._server_sock = None
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            self._connected = False
        # Clean up Unix socket file
        if self._use_unix and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    def send(self, message: Message, timeout: float = 30.0) -> Message:
        if self._direction == InterfaceDirection.FRONTEND:
            raise RuntimeError("SocketAdapter in FRONTEND mode does not support send()")
        s = self._ensure_connected()
        if s is None:
            return Message(
                action="error",
                payload={"reason": "not_connected"},
                metadata={"source": self.name, "error_code": "NOT_CONNECTED"},
            )
        try:
            s.settimeout(timeout)
            req = json.dumps({"action": message.action, "payload": message.payload}).encode("utf-8")
            s.sendall(req + b"\n")
            resp_data = s.recv(65536)
            if not resp_data:
                return Message(
                    action="error",
                    payload={"reason": "empty_response"},
                    metadata={"source": self.name, "error_code": "EMPTY_RESPONSE"},
                )
            parsed = json.loads(resp_data.decode("utf-8"))
            return Message(
                action=parsed.get("action", "response"),
                payload=parsed.get("payload", {}),
                metadata={"source": self.name, "correlation_id": message.metadata.get("correlation_id", "")},
            )
        except socket.timeout:
            return Message(
                action="error",
                payload={"reason": "timeout"},
                metadata={"source": self.name, "error_code": "TIMEOUT"},
            )
        except Exception as exc:
            self._connected = False
            return Message(
                action="error",
                payload={"reason": str(exc)},
                metadata={"source": self.name, "error_code": "SEND_ERROR"},
            )

    def health_check(self, timeout: float) -> HealthResult:
        if self._direction == InterfaceDirection.FRONTEND:
            return HealthResult(
                status=HealthStatus.HEALTHY if self._running else HealthStatus.UNHEALTHY,
                message=f"Socket frontend {'running' if self._running else 'stopped'}",
            )
        s = self._ensure_connected()
        if s is None:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message="Cannot connect to socket",
            )
        try:
            s.settimeout(timeout)
            req = json.dumps({"action": "health"}).encode("utf-8")
            s.sendall(req + b"\n")
            resp = s.recv(4096)
            data = json.loads(resp.decode("utf-8"))
            status = (
                HealthStatus.HEALTHY
                if data.get("status") == "healthy"
                else HealthStatus.UNHEALTHY
            )
            return HealthResult(status=status, message=str(data))
        except Exception as exc:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Socket error: {exc}",
            )

    def is_connected(self) -> bool:
        if self._direction in (InterfaceDirection.FRONTEND, InterfaceDirection.BIDIRECTIONAL):
            return self._running
        return self._connected

    @property
    def direction(self) -> InterfaceDirection:
        return self._direction

    @property
    def supports_passthrough(self) -> bool:
        return True

    # ── Internal helpers ──────────────────────────────────────────────

    def set_request_handler(self, handler: Callable[[Message], Message]) -> None:
        """Set the handler that processes incoming requests (frontend mode)."""
        self._connection_handler = handler

    def _start_frontend(self) -> None:
        """Listen and accept connections in a background thread."""
        try:
            if self._use_unix:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                if os.path.exists(self.socket_path):
                    os.unlink(self.socket_path)
                s.bind(self.socket_path)
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.host, self.port or 0))
                if self.port == 0 or self.port is None:
                    self.port = s.getsockname()[1]
            s.listen(5)
            s.settimeout(1.0)
            self._server_sock = s
            self._running = True
            self._connected = True
            self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._accept_thread.start()
            logger.info("Socket frontend %s listening on %s", self.name, self.socket_path if self._use_unix else f"{self.host}:{self.port}")
        except Exception as exc:
            logger.error("Socket frontend %s failed to start: %s", self.name, exc)
            raise

    def _start_backend(self) -> None:
        """Connect to the daemon socket lazily on first send()."""
        pass  # Connection happens in _ensure_connected()

    def _ensure_connected(self) -> socket.socket | None:
        if self._sock is not None:
            return self._sock
        try:
            if self._use_unix:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect(self.socket_path)
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect((self.host, self.port or 9877))
            self._sock = s
            self._connected = True
            return s
        except Exception:
            self._connected = False
            return None

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._server_sock.accept()  # type: ignore[union-attr]
                handler = self._connection_handler
                if handler:
                    t = threading.Thread(
                        target=self._handle_connection,
                        args=(conn, handler),
                        daemon=True,
                    )
                    t.start()
                else:
                    conn.close()
            except socket.timeout:
                continue
            except Exception:
                if self._running:
                    logger.exception("Accept error")

    def _handle_connection(self, conn: socket.socket, handler: Callable[[Message], Message]) -> None:
        try:
            conn.settimeout(30.0)
            data = conn.recv(65536)
            if not data:
                return
            raw = json.loads(data.decode("utf-8"))
            request = Message(
                action=raw.get("action", ""),
                payload=raw.get("payload", {}),
                metadata={"source": self.name},
            )
            response = handler(request)
            resp_bytes = json.dumps({"action": response.action, "payload": response.payload}).encode("utf-8")
            conn.sendall(resp_bytes + b"\n")
        except Exception:
            logger.exception("Error handling socket connection")
        finally:
            try:
                conn.close()
            except Exception:
                pass


