"""DaemonWrapper — top-level orchestrator for interface translation layer."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from ..health import CrashLoopDetector, HealthResult, HealthStatus
from .interface_registry import InterfaceRegistry
from .translation_engine import TranslationEngine
from .protocol import InterfaceDirection

logger = logging.getLogger(__name__)


class DaemonWrapper:
    """Wraps an external daemon with multi-interface translation.

    Owns the daemon lifecycle (via WorkerLifecycle), the InterfaceRegistry,
    the TranslationEngine, and optionally a FileHealthMonitor.

    States: cold, running, degraded, unrecoverable.

    No ``reconfigure()`` hot-swap in v1 — adapter changes require
    ``stop()`` / ``start()`` cycle.
    """

    def __init__(
        self,
        daemon_cmd: list[str],
        backend: Any,
        frontends: list[Any],
        lifecycle: Any | None = None,
        health_check: Callable[[], HealthResult] | None = None,
        file_monitor: Any | None = None,
        crash_threshold: int = 3,
        crash_window: float = 30.0,
        max_restarts: int = 10,
        cooldown_seconds: float = 10.0,
    ) -> None:
        self.daemon_cmd = daemon_cmd
        self.lifecycle = lifecycle
        self._custom_health_check = health_check
        self.file_monitor = file_monitor
        self._proc: Any = None
        self._started = False
        self._state = "cold"
        self._lock = threading.Lock()

        # Build InterfaceRegistry, TranslationEngine
        self.registry = InterfaceRegistry(backend=backend)
        for fe in frontends:
            self.registry.register(fe)

        self.translation_engine = TranslationEngine(
            backend=backend,
            frontends=self.registry.frontends,
        )
        self.registry.set_translation_engine(self.translation_engine)

        # Crash loop detection
        self._crash_detector = CrashLoopDetector(
            threshold=crash_threshold,
            window_seconds=crash_window,
            max_restarts=max_restarts,
            restart_window_seconds=300.0,
        )
        self._cooldown_seconds = cooldown_seconds
        self._monitor_thread: Any = None
        self._stop_event = threading.Event()

    @property
    def state(self) -> str:
        """Return current wrapper state."""
        with self._lock:
            return self._state

    def _set_state(self, value: str) -> None:
        with self._lock:
            old = self._state
            self._state = value
            if old != value:
                logger.info("DaemonWrapper state: %s -> %s", old, value)

    # ── Public API ────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the daemon, start the backend adapter, start all enabled frontends."""
        logger.info("DaemonWrapper starting: %s", " ".join(self.daemon_cmd))

        # Spawn daemon
        if self.lifecycle:
            config = self.registry.backend.configure()
            self._proc = self.lifecycle.spawn(self.daemon_cmd, config)

        # Start backend and all enabled frontends via registry
        self.registry.start_all()

        self._started = True
        self._set_state("running")
        self._stop_event.clear()

        # Start monitor thread if we have lifecycle management
        if self.lifecycle:
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self._monitor_thread.start()

        logger.info("DaemonWrapper started")

    def stop(self) -> None:
        """Gracefully stop frontends, backend, and kill the daemon."""
        logger.info("DaemonWrapper stopping")
        self._stop_event.set()

        # Stop frontends first, then backend
        self.registry.stop_all()

        # Kill daemon
        if self.lifecycle and self._proc is not None:
            try:
                self.lifecycle.kill(self._proc, graceful_timeout=5.0)
            except Exception:
                logger.exception("Error killing daemon")
            self._proc = None

        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=3.0)
            self._monitor_thread = None

        self._started = False
        self._set_state("cold")
        logger.info("DaemonWrapper stopped")

    def status(self) -> dict[str, Any]:
        """Return wrapper status with health aggregation.

        Health aggregation policy (see design doc §6.4):
        - Backend health is canonical for state machine
        - Frontend health is advisory (reported, does not affect state)
        - FileHealthMonitor contributes to reporting only
        - Custom health_check (if provided) overrides backend health
        """
        proc_status = "not_running"
        if self._proc is not None:
            proc_status = (
                "running"
                if self._proc.poll() is None
                else f"exited({self._proc.returncode})"
            )

        # Backend health (canonical for state machine)
        backend_health = None
        if self._started:
            try:
                if self._custom_health_check:
                    backend_health = self._custom_health_check()
                else:
                    backend_health = self.registry.backend.health_check(timeout=5.0)
            except Exception as exc:
                backend_health = HealthResult(
                    status=HealthStatus.UNHEALTHY, message=str(exc)
                )

        # Frontend health (advisory)
        frontend_statuses: dict[str, Any] = {}
        for name in self.registry.list_frontends():
            adapter = self.registry.frontends.get(name)
            enabled = self.registry.list_frontends().get(name, False)
            frontend_statuses[name] = {
                "enabled": enabled,
                "connected": adapter.is_connected() if adapter else False,
            }
            if enabled and adapter:
                try:
                    fh = adapter.health_check(timeout=2.0)
                    frontend_statuses[name]["health"] = {
                        "status": fh.status.value,
                        "message": fh.message,
                    }
                except Exception as exc:
                    frontend_statuses[name]["health"] = {
                        "status": "unhealthy",
                        "message": str(exc),
                    }

        # File monitor health (advisory)
        file_monitor_health = None
        if self.file_monitor:
            try:
                fmh = self.file_monitor.health_check()
                file_monitor_health = {
                    "status": fmh.status.value,
                    "message": fmh.message,
                }
            except Exception as exc:
                file_monitor_health = {"status": "unhealthy", "message": str(exc)}

        result: dict[str, Any] = {
            "state": self._state,
            "started": self._started,
            "daemon_pid": self._proc.pid if self._proc else None,
            "daemon_status": proc_status,
            "frontends": frontend_statuses,
            "backend_health": {
                "status": backend_health.status.value,
                "message": backend_health.message,
            }
            if backend_health
            else None,
            "file_monitor": file_monitor_health,
            "crash_count": self._crash_detector.crash_count,
            "restart_count": self._crash_detector.restart_count,
        }
        return result

    def toggle_frontend(self, name: str, enabled: bool) -> None:
        """Enable or disable a frontend interface at runtime."""
        if name not in self.registry.frontends:
            raise KeyError(f"Unknown frontend: {name}")

        if enabled:
            self.registry.enable(name)
        else:
            self.registry.disable(name)

        logger.info("Frontend %s %s", name, "enabled" if enabled else "disabled")

    # ── Internal: crash loop monitoring ───────────────────────────────

    def _monitor_loop(self) -> None:
        """Watch for unexpected child death and crash loops.

        Implements crash loop detection and recovery using CrashLoopDetector
        and the lifecycle's restart/rollback capabilities.
        """
        while not self._stop_event.is_set():
            self._stop_event.wait(1.0)
            with self._lock:
                started = self._started
                proc = self._proc
                state = self._state

            if not started or state in ("unrecoverable",):
                continue

            if proc is not None and proc.poll() is not None:
                exit_code = proc.returncode
                logger.error("Daemon exited unexpectedly with code %s", exit_code)

                in_loop = self._crash_detector.record_crash()
                if in_loop:
                    logger.critical("Crash loop detected — entering cooldown")
                    time.sleep(self._cooldown_seconds)

                self._crash_detector.record_restart()
                if self._crash_detector.give_up():
                    logger.critical(
                        "Max restarts (%d) exceeded; entering UNRECOVERABLE state",
                        self._crash_detector.max_restarts,
                    )
                    self._set_state("unrecoverable")
                    continue

                # Attempt restart
                if self.lifecycle:
                    config = self.registry.backend.configure()
                    try:
                        new_proc = self.lifecycle.spawn(self.daemon_cmd, config)
                        with self._lock:
                            self._proc = new_proc
                            self._set_state("running")
                        logger.info("Daemon restarted after crash")
                    except Exception:
                        logger.exception("Failed to restart daemon")
                        self._set_state("degraded")
