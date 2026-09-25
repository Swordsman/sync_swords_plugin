"""Socket transport — Unix domain socket with TCP fallback."""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import uuid

from ..health import HealthResult, HealthStatus
from .base import Transport

logger = logging.getLogger(__name__)


class SocketTransport(Transport):
    """Communicate with worker over a Unix domain socket (or TCP on Windows)."""

    def __init__(self, socket_path: str | None = None, port: int | None = None) -> None:
        self._use_unix = hasattr(socket, "AF_UNIX")
        if self._use_unix:
            self.socket_path = socket_path or os.path.join(
                tempfile.gettempdir(), f"hearthphoenix_{uuid.uuid4().hex[:8]}.sock"
            )
            self.port = port
        else:
            # Windows fallback: use TCP on localhost with auto-assigned port
            self.socket_path = ""
            self.port = port or 0
        self._sock: socket.socket | None = None
        self._connected = False

    def configure(self) -> dict[str, str]:
        cfg: dict[str, str] = {
            "HEARTH_PHOENIX_TRANSPORT": "socket",
        }
        if self._use_unix:
            cfg["HEARTH_PHOENIX_SOCKET_PATH"] = self.socket_path
        else:
            # If port is 0, worker will need to coordinate; use a fixed fallback
            cfg["HEARTH_PHOENIX_SOCKET_PORT"] = str(self.port or 9877)
        return cfg

    def on_supervisor_start(self) -> None:
        pass

    def _connect(self) -> socket.socket | None:
        if self._sock is not None:
            return self._sock
        try:
            if self._use_unix:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect(self.socket_path)
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect(("127.0.0.1", self.port or 9877))
            self._sock = s
            self._connected = True
            return s
        except Exception:
            self._connected = False
            return None

    def health_check(self, timeout: float) -> HealthResult:
        s = self._connect()
        if s is None:
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message="Cannot connect to socket"
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
            self._connected = False
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message=f"Socket error: {exc}"
            )

    def shutdown(self, graceful: bool = True) -> None:
        s = self._connect()
        if s is not None:
            try:
                req = json.dumps({"action": "shutdown"}).encode("utf-8")
                s.sendall(req + b"\n")
            except Exception:
                pass
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def is_connected(self) -> bool:
        return self._connected

    def on_supervisor_stop(self) -> None:
        self.shutdown()
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
