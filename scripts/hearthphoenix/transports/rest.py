"""REST transport — HTTP localhost polling."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from ..health import HealthResult, HealthStatus
from .base import Transport

logger = logging.getLogger(__name__)


class RestTransport(Transport):
    """Poll worker health via HTTP GET localhost:/health."""

    DEFAULT_PORT = 9876

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self._connected = False

    def configure(self) -> dict[str, str]:
        return {
            "HEARTH_PHOENIX_TRANSPORT": "rest",
            "HEARTH_PHOENIX_REST_PORT": str(self.port),
        }

    def on_supervisor_start(self) -> None:
        self._connected = True

    def health_check(self, timeout: float) -> HealthResult:
        url = f"http://127.0.0.1:{self.port}/health"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200:
                    self._connected = True
                    return HealthResult(status=HealthStatus.HEALTHY, message=body)
                else:
                    return HealthResult(
                        status=HealthStatus.UNHEALTHY,
                        message=f"HTTP {resp.status}",
                    )
        except urllib.error.URLError as exc:
            self._connected = False
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Connection error: {exc}",
            )
        except Exception as exc:
            self._connected = False
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Unexpected error: {exc}",
            )

    def shutdown(self, graceful: bool = True) -> None:
        url = f"http://127.0.0.1:{self.port}/shutdown"
        try:
            req = urllib.request.Request(url, method="POST", data=b"")
            urllib.request.urlopen(req, timeout=2.0)
        except Exception:
            pass
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def on_supervisor_stop(self) -> None:
        self._connected = False
