"""Stdin/stdout JSON lines transport."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from typing import Any

from ..health import HealthResult, HealthStatus
from .base import Transport

logger = logging.getLogger(__name__)


class PipeTransport(Transport):
    """Communicate via stdin/stdout JSON lines with a worker subprocess."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._connected = False
        self._reader_thread: threading.Thread | None = None
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._stop_reader = threading.Event()

    def set_process(self, proc: subprocess.Popen) -> None:
        """Bind this transport to a worker subprocess."""
        self._proc = proc
        self._connected = proc.poll() is None
        self._start_reader()

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
                self._queue.put(line)
        except Exception:
            pass

    def _drain_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def configure(self) -> dict[str, str]:
        return {
            "HEARTH_PHOENIX_TRANSPORT": "pipe",
        }

    def on_supervisor_start(self) -> None:
        self._connected = self._proc is not None and self._proc.poll() is None

    def health_check(self, timeout: float) -> HealthResult:
        if not self.is_connected():
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message="Pipe not connected"
            )
        return self._send_recv({"action": "health"}, timeout)

    def shutdown(self, graceful: bool = True) -> None:
        if self.is_connected():
            try:
                self._send({"action": "shutdown"})
            except Exception:
                pass
        self._connected = False

    def is_connected(self) -> bool:
        if self._proc is None:
            return False
        if self._proc.poll() is not None:
            self._connected = False
            return False
        # Check if stdin/stdout pipes are still open
        if self._proc.stdin is None or self._proc.stdout is None:
            self._connected = False
            return False
        return self._connected

    def on_supervisor_stop(self) -> None:
        self.shutdown()
        self._stop_reader.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
            self._reader_thread = None
        self._proc = None

    def _send(self, msg: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise IOError("Pipe is not open for writing")
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        self._proc.stdin.flush()

    def _send_recv(self, msg: dict[str, Any], timeout: float) -> HealthResult:
        """Send a message and wait for a JSON-line response on stdout."""
        if self._proc is None or self._proc.stdout is None:
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message="Pipe is not open for reading"
            )

        try:
            self._send(msg)
        except Exception as exc:
            self._connected = False
            return HealthResult(
                status=HealthStatus.UNHEALTHY, message=f"Send error: {exc}"
            )

        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                line = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._proc.poll() is not None:
                    # Process died while waiting
                    break
                continue
            try:
                data = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Invalid JSON response: {exc}",
                )
            status = (
                HealthStatus.HEALTHY
                if data.get("status") == "healthy"
                else HealthStatus.UNHEALTHY
            )
            return HealthResult(status=status, message=str(data))

        return HealthResult(
            status=HealthStatus.UNHEALTHY,
            message="Timeout waiting for pipe response",
        )
