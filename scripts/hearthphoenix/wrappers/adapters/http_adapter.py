"""HTTP adapter — REST frontend/backend using stdlib only."""

from __future__ import annotations

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from collections.abc import Callable

from ...health import HealthResult, HealthStatus
from ..protocol import InterfaceDirection, Message
from .base import InterfaceAdapter

logger = logging.getLogger(__name__)


class _RequestHandler(BaseHTTPRequestHandler):
    """Per-request handler that delegates to the adapter's callback."""

    adapter: HttpAdapter  # set by HttpAdapter before server starts

    def do_GET(self) -> None:
        if self.path == "/health":
            result = self.adapter._backend_health_check(timeout=5.0)
            self._json_response(
                200 if result.status == HealthStatus.HEALTHY else 503,
                {"status": result.status.value, "message": result.message},
            )
        else:
            self._json_response(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/invoke":
            handler = self.adapter._request_handler
            if handler is None:
                self._json_response(503, {"error": "no_handler"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, ValueError) as exc:
                self._json_response(400, {"error": f"invalid_json: {exc}"})
                return

            request = Message(
                action=data.get("action", "invoke"),
                payload=data.get("payload", {}),
                metadata={"source": self.adapter.name},
            )
            response = handler(request)
            self._json_response(200, {"action": response.action, "payload": response.payload})
        else:
            self._json_response(404, {"error": "not_found"})

    def _json_response(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("HTTP %s", fmt % args)


class HttpAdapter(InterfaceAdapter):
    """HTTP frontend/backend adapter using stdlib only.

    Frontend: binds ``ThreadingHTTPServer`` on localhost to serve
    ``GET /health`` and ``POST /invoke``.

    Backend: sends ``GET /health`` and ``POST /invoke`` to a daemon's
    HTTP endpoint.
    """

    def __init__(
        self,
        name: str,
        *,
        port: int = 8080,
        host: str = "127.0.0.1",
        backend_url: str | None = None,
        direction: InterfaceDirection = InterfaceDirection.BIDIRECTIONAL,
    ) -> None:
        super().__init__(name)
        self.port = port
        self.host = host
        self.backend_url = backend_url
        self._direction = direction
        self._server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._running = False
        self._request_handler: Callable[[Message], Message] | None = None

    # ── InterfaceAdapter ──────────────────────────────────────────────

    def configure(self) -> dict[str, str]:
        cfg: dict[str, str] = {
            "HEARTH_PHOENIX_TRANSPORT": "http_adapter",
        }
        if self._direction in (InterfaceDirection.FRONTEND, InterfaceDirection.BIDIRECTIONAL):
            cfg["HEARTH_PHOENIX_HTTP_PORT"] = str(self.port)
            cfg["HEARTH_PHOENIX_HTTP_HOST"] = self.host
        if self.backend_url:
            cfg["HEARTH_PHOENIX_HTTP_BACKEND_URL"] = self.backend_url
        return cfg

    def start(self) -> None:
        if self._direction in (InterfaceDirection.FRONTEND, InterfaceDirection.BIDIRECTIONAL):
            self._start_frontend()
        if self._direction in (InterfaceDirection.BACKEND, InterfaceDirection.BIDIRECTIONAL):
            pass  # Backend has no persistent listener

    def stop(self) -> None:
        self._running = False
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=2.0)
            self._server_thread = None

    def send(self, message: Message, timeout: float = 30.0) -> Message:
        if self._direction == InterfaceDirection.FRONTEND:
            raise RuntimeError("HttpAdapter in FRONTEND mode does not support send()")
        if not self.backend_url:
            return Message(
                action="error",
                payload={"reason": "no_backend_url_configured"},
                metadata={"source": self.name, "error_code": "NO_BACKEND_URL"},
            )

        url = f"{self.backend_url.rstrip('/')}/invoke"
        body = json.dumps({"action": message.action, "payload": message.payload}).encode("utf-8")
        try:
            req = Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(resp_body)
                return Message(
                    action=data.get("action", "response"),
                    payload=data.get("payload", {}),
                    metadata={"source": self.name},
                )
        except URLError as exc:
            return Message(
                action="error",
                payload={"reason": f"backend_error: {exc.reason}"},
                metadata={"source": self.name, "error_code": "BACKEND_ERROR"},
            )
        except Exception as exc:
            return Message(
                action="error",
                payload={"reason": str(exc)},
                metadata={"source": self.name, "error_code": "SEND_ERROR"},
            )

    def health_check(self, timeout: float) -> HealthResult:
        if self._direction == InterfaceDirection.FRONTEND:
            return HealthResult(
                status=HealthStatus.HEALTHY if self._running else HealthStatus.UNHEALTHY,
                message=f"HTTP frontend {'running' if self._running else 'stopped'}",
            )
        return self._backend_health_check(timeout)

    def is_connected(self) -> bool:
        if self._direction == InterfaceDirection.FRONTEND:
            return self._running
        return False  # Backend connection is stateless

    @property
    def direction(self) -> InterfaceDirection:
        return self._direction

    @property
    def supports_passthrough(self) -> bool:
        return True

    # ── Internal helpers ──────────────────────────────────────────────

    def set_request_handler(self, handler: Callable[[Message], Message]) -> None:
        """Set the handler for incoming requests (frontend mode)."""
        self._request_handler = handler

    def _start_frontend(self) -> None:
        _RequestHandler.adapter = self  # type: ignore[attr-defined]
        self._server = HTTPServer((self.host, self.port), _RequestHandler)
        self._server.timeout = 0.5
        if self.port == 0:
            self.port = self._server.server_address[1]
        self._running = True
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        logger.info("HTTP frontend %s listening on %s:%s", self.name, self.host, self.port)

    def _backend_health_check(self, timeout: float) -> HealthResult:
        if not self.backend_url:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message="No backend URL configured",
            )
        url = f"{self.backend_url.rstrip('/')}/health"
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return HealthResult(status=HealthStatus.HEALTHY, message="HTTP backend healthy")
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"HTTP {resp.status}",
                )
        except Exception as exc:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Backend health check error: {exc}",
            )
