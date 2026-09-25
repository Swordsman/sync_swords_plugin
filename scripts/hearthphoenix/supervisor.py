"""Supervisor orchestrator."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .capabilities import Capability, CapabilityScanner, CapabilityReport, GuaranteeLevel
from .contracts import (
    Contract,
    VerificationReport,
    precondition,
    run_contract_verification,
)
from .health import HealthCheck, HealthResult, HealthStatus, CrashLoopDetector
from .lifecycle import WorkerLifecycle
from .snapshot import SnapshotManager
from .transports.base import Transport

logger = logging.getLogger(__name__)


class Supervisor(Contract):
    """Owns transport, snapshot manager, and worker lifecycle."""

    def __init__(
        self,
        transport: Transport,
        snapshot_manager: SnapshotManager,
        lifecycle: WorkerLifecycle,
        health_check: Callable[[], HealthResult] | HealthCheck | None = None,
        *,
        worker_cmd: list[str] | None = None,
        worker_path: str | Path | None = None,
        crash_threshold: int = 3,
        crash_window: float = 30.0,
        cooldown_seconds: float = 10.0,
    ) -> None:
        self.transport = transport
        self.snapshots = snapshot_manager
        self.lifecycle = lifecycle
        self.health_check = health_check
        self.worker_cmd = worker_cmd or []
        self.worker_path = Path(worker_path) if worker_path else None

        self._proc: subprocess.Popen | None = None
        self._started = False
        self._state = "cold"
        self._lock = threading.Lock()
        self._crash_detector = CrashLoopDetector(
            threshold=crash_threshold, window_seconds=crash_window
        )
        self._cooldown_seconds = cooldown_seconds
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._capability_report: CapabilityReport | None = None
        self._verification_report: VerificationReport | None = None
        self._prior_verification_report: VerificationReport | None = None

    @property
    def state(self) -> str:
        """Return current supervisor state.

        States:
            cold          — no worker started
            running       — worker is up and healthy
            updated       — new version deployed, awaiting health confirmation
            rolling_back  — reverting to safe version
            degraded      — worker missing, attempting recovery
            unrecoverable — crash loop max exceeded, manual intervention required
        """
        with self._lock:
            return self._state

    def _set_state(self, value: str) -> None:
        with self._lock:
            old = self._state
            self._state = value
            if old != value:
                logger.info("Supervisor state: %s -> %s", old, value)

    def _invoke_health_check(self) -> HealthResult:
        """Dispatch to either a callable or a HealthCheck instance."""
        if self.health_check is None:
            raise RuntimeError("No health_check configured")
        if isinstance(self.health_check, HealthCheck):
            return self.health_check.check()
        return self.health_check()

    def _run_contract_verification_if_applicable(self) -> VerificationReport | None:
        """Run contract verification on the worker file if it supports WorkerContract.

        Returns the report, or ``None`` if the worker file is not a Python
        file or does not contain a WorkerContract subclass.
        """
        if (
            self.worker_path is None
            or not self.worker_path.exists()
            or self.worker_path.suffix != ".py"
        ):
            return None
        try:
            report = run_contract_verification(self.worker_path)
            # Only store if there are declared operations (WorkerContract detected)
            if report.verified:
                logger.info(
                    "Contract verification complete: %d verified, %d unverified",
                    sum(1 for v in report.verified.values() if v),
                    len(report.unverified_operations),
                )
                return report
            return None
        except Exception:
            logger.debug("Contract verification skipped (not a WorkerContract worker)", exc_info=True)
            return None

    @precondition(lambda self: not self._started)
    def start(self) -> None:
        """Start the supervisor and the initial worker."""
        self.transport.on_supervisor_start()
        if self.worker_path and self.worker_path.exists():
            safe = self.snapshots.get_safe_path()
            if safe is None:
                snap = self.snapshots.snapshot(self.worker_path, label="auto-start")
                self.snapshots.promote(snap)

        config = self.transport.configure()
        proc = self.lifecycle.spawn(self.worker_cmd, config)
        with self._lock:
            self._proc = proc
            self._started = True
            self._state = "running"
        self._stop_event.clear()

        # If transport supports process binding (e.g., PipeTransport), bind it now
        if hasattr(self.transport, "set_process"):
            self.transport.set_process(proc)

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        # Run contract verification on first start (backward compatible —
        # non-WorkerContract workers are silently skipped).
        self._verification_report = self._run_contract_verification_if_applicable()

        logger.info("Supervisor started with worker PID %s", proc.pid)

    def update(self, source_path: str | Path) -> dict[str, Any]:
        """Transactional update: validate, snapshot, swap, health-check, commit/rollback."""
        source_path = Path(source_path).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        # Validate
        self._validate_source(source_path)

        # Snapshot current
        if self.worker_path and self.worker_path.exists():
            self.snapshots.snapshot(self.worker_path, label="pre-update")

        # Save prior verification state for rollback
        self._prior_verification_report = self._verification_report

        with self._lock:
            # Stop old worker
            if self._proc is not None and self._proc.poll() is None:
                self.lifecycle.kill(self._proc, graceful_timeout=5.0)
            self._proc = None
            self._state = "updated"

        # Clear stale transport state so the health check validates the new worker
        self.transport.on_supervisor_stop()

        # File I/O happens outside the lock here. This is INTENTIONAL and safe:
        # the old worker is dead, so there is no race between the old worker
        # reading worker_path and us writing to it. The only potential race is
        # concurrent update() calls from multiple threads, which should be
        # serialized at a higher level if needed.
        if self.worker_path:
            tmp_path = self.worker_path.with_suffix('.tmp')
            try:
                if tmp_path.exists():
                    if tmp_path.is_dir():
                        shutil.rmtree(tmp_path)
                    else:
                        tmp_path.unlink()
                if source_path.is_dir():
                    shutil.copytree(source_path, tmp_path)
                else:
                    shutil.copy2(source_path, tmp_path)
                if tmp_path.is_dir():
                    # os.replace() cannot replace directories on Windows
                    if self.worker_path.exists():
                        if self.worker_path.is_dir():
                            shutil.rmtree(self.worker_path)
                        else:
                            self.worker_path.unlink()
                    shutil.copytree(tmp_path, self.worker_path)
                else:
                    os.replace(tmp_path, self.worker_path)
            finally:
                if tmp_path.exists():
                    if tmp_path.is_dir():
                        shutil.rmtree(tmp_path)
                    else:
                        tmp_path.unlink()

        with self._lock:
            config = self.transport.configure()
            new_proc = self.lifecycle.spawn(self.worker_cmd, config)
            self._proc = new_proc
            if hasattr(self.transport, "set_process"):
                self.transport.set_process(new_proc)

        # Health check
        if self.health_check is not None:
            result = self.lifecycle.await_healthy(
                self._invoke_health_check, timeout=5.0, retries=5
            )
        else:
            result = self.lifecycle.await_healthy(
                lambda: self.transport.health_check(timeout=5.0),
                timeout=5.0,
                retries=5,
            )

        if result.status == HealthStatus.HEALTHY:
            # Run contract verification on the new worker
            new_report = self._run_contract_verification_if_applicable()

            # Commit
            new_snap = (
                self.snapshots.snapshot(self.worker_path, label="post-update")
                if self.worker_path
                else None
            )
            if new_snap:
                self.snapshots.promote(new_snap)
            with self._lock:
                self._crash_detector.reset()
                self._state = "running"
                if new_report is not None:
                    self._verification_report = new_report
            logger.info("Update committed successfully")
            return {"success": True, "action": "commit", "state": "running", "health": result}
        else:
            # Rollback
            logger.warning("Update failed health check; rolling back")
            with self._lock:
                if self._proc is not None and self._proc.poll() is None:
                    self.lifecycle.kill(self._proc, graceful_timeout=3.0)
                self._proc = None
                self._state = "rolling_back"
                # Restore prior verification state
                self._verification_report = self._prior_verification_report

                safe = self.snapshots.get_safe_path()
                if safe and self.worker_path:
                    self._proc = self.lifecycle.rollback_and_restart(
                        safe, self.worker_path, self.worker_cmd, config
                    )
                rollback_proc = self._proc

            if rollback_proc:
                if hasattr(self.transport, "set_process"):
                    self.transport.set_process(rollback_proc)
                # Re-run health check on rolled-back version
                if self.health_check is not None:
                    rollback_result = self.lifecycle.await_healthy(
                        self._invoke_health_check, timeout=5.0, retries=5
                    )
                else:
                    rollback_result = self.lifecycle.await_healthy(
                        lambda: self.transport.health_check(timeout=5.0),
                        timeout=5.0,
                        retries=5,
                    )
                if rollback_result.status != HealthStatus.HEALTHY:
                    logger.critical("Rollback version failed health check; stopping worker")
                    with self._lock:
                        if self._proc is not None and self._proc.poll() is None:
                            self.lifecycle.kill(self._proc, graceful_timeout=3.0)
                        self._proc = None
                    # Gap 1.6: attempt cold restart as last resort
                    return self._attempt_recovery_after_rollback()
                with self._lock:
                    self._state = "running"
                logger.info("Rollback complete; worker restarted from safe version")
            return {"success": False, "action": "rollback", "state": "running", "health": result}

    def _attempt_recovery_after_rollback(self) -> dict[str, Any]:
        """Enter DEGRADED and attempt a cold restart from worker_cmd."""
        self._set_state("degraded")
        if self.worker_cmd:
            config = self.transport.configure()
            try:
                proc = self.lifecycle.spawn(self.worker_cmd, config)
                with self._lock:
                    self._proc = proc
                    self._state = "running"
                if hasattr(self.transport, "set_process"):
                    self.transport.set_process(proc)
                logger.info("Cold restart succeeded after rollback failure")
                return {"success": False, "action": "rollback-failed-recovered", "state": "running", "health": None}
            except Exception:
                logger.exception("Cold restart failed after rollback failure")
        with self._lock:
            self._started = False
            self._state = "degraded"
        return {"success": False, "action": "rollback-failed", "state": "degraded", "health": None}

    def stop(self) -> None:
        """Stop the supervisor and worker."""
        self._stop_event.set()
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self.lifecycle.kill(self._proc, graceful_timeout=5.0)
            self._proc = None
            self._started = False
            self._state = "cold"
        self.transport.on_supervisor_stop()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        logger.info("Supervisor stopped")

    @classmethod
    def wrap_worker(
        cls, script_path: str | Path, **kwargs: Any
    ) -> tuple[Supervisor, CapabilityReport]:
        """Auto-configure a Supervisor for a worker script (existing behavior)."""
        script_path = Path(script_path).expanduser().resolve()
        report = CapabilityScanner().scan_script(script_path)

        from .transports import FileTransport

        transport = kwargs.pop("transport", None)
        if transport is None:
            transport = FileTransport()

        health_check = kwargs.pop("health_check", None)
        snapshots = kwargs.pop(
            "snapshot_manager", None
        ) or SnapshotManager(kwargs.pop("snapshot_dir", ".snapshots"))
        lifecycle = kwargs.pop("lifecycle", None) or WorkerLifecycle()
        worker_cmd = kwargs.pop("worker_cmd", None) or ["python", str(script_path)]
        worker_path = kwargs.pop("worker_path", None) or script_path

        supervisor = cls(
            transport=transport,
            snapshot_manager=snapshots,
            lifecycle=lifecycle,
            health_check=health_check,
            worker_cmd=worker_cmd,
            worker_path=worker_path,
            **kwargs,
        )
        supervisor._capability_report = report
        return supervisor, report

    @classmethod
    def wrap(
        cls, script_path: str | Path, **kwargs: Any
    ) -> tuple[Supervisor, CapabilityReport]:
        """Auto-configure a Supervisor based on detected capabilities.

        .. deprecated::
            Use :meth:`wrap_worker` instead. This method will be removed in a
            future release.
        """
        import warnings

        warnings.warn(
            "Supervisor.wrap() is deprecated; use Supervisor.wrap_worker() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls.wrap_worker(script_path, **kwargs)

    @classmethod
    def wrap_daemon(
        cls,
        daemon_cmd: list[str],
        *,
        backend: Any,
        frontends: list[Any],
        **kwargs: Any,
    ) -> tuple[Any, CapabilityReport]:
        """Auto-configure a DaemonWrapper for an external daemon.

        Returns:
            A tuple of (DaemonWrapper, CapabilityReport).
        """
        from .wrappers import DaemonWrapper

        # An external daemon is not a Python script we can scan, so no
        # capabilities are detected and the guarantee level is the floor.
        report = CapabilityReport(
            detected=set(),
            missing=set(Capability),
            guarantee_level=GuaranteeLevel.BRUTE_FORCE,
            risks=[
                "Daemon mode wraps an external process; capabilities are not "
                "scanned. Hotswap and graceful shutdown are best-effort."
            ],
            recommendations=[
                "Provide a custom health_check or FileHealthMonitor for liveness.",
                "Ensure the daemon handles SIGTERM for graceful shutdown.",
            ],
        )

        wrapper = DaemonWrapper(
            daemon_cmd=daemon_cmd,
            backend=backend,
            frontends=frontends,
            **kwargs,
        )
        return wrapper, report

    def status(self) -> dict[str, Any]:
        """Return supervisor status."""
        with self._lock:
            proc = self._proc
            started = self._started
            state = self._state
        proc_status = "not_running"
        if proc is not None:
            proc_status = (
                "running"
                if proc.poll() is None
                else f"exited({proc.returncode})"
            )
        result: dict[str, Any] = {
            "started": started,
            "worker_pid": proc.pid if proc else None,
            "worker_status": proc_status,
            "state": state,
            "transport_connected": self.transport.is_connected(),
            "crash_count": self._crash_detector.crash_count,
            "restart_count": self._crash_detector.restart_count,
            "snapshots": len(self.snapshots.list_snapshots()),
            "safe_version_exists": self.snapshots.get_safe_path() is not None,
        }
        report = getattr(self, "_capability_report", None)
        if report is not None:
            result["guarantee_level"] = report.guarantee_level.name
            result["detected_capabilities"] = [c.value for c in report.detected]
            result["missing_capabilities"] = [c.value for c in report.missing]
            result["hotswap_risk"] = (
                "; ".join(report.risks) if report.risks else "none"
            )
        else:
            result["guarantee_level"] = GuaranteeLevel.BRUTE_FORCE.name
            result["detected_capabilities"] = []
            result["missing_capabilities"] = [c.value for c in Capability]
            result["hotswap_risk"] = (
                "Capabilities not scanned; assume lowest guarantee."
            )

        # Per-operation guarantee matrix from verified contracts
        vreport = getattr(self, "_verification_report", None)
        if vreport is not None and vreport.matrix:
            result["per_operation_guarantees"] = vreport.matrix
            result["verification_status"] = (
                "all_verified" if vreport.all_verified else "partial"
            )
            result["contracts_verified"] = sum(
                1 for v in vreport.verified.values() if v
            )
            result["contracts_unverified"] = len(vreport.unverified_operations)
        else:
            result["per_operation_guarantees"] = {
                op: "UNKNOWN"
                for op in (
                    "start", "stop", "restart", "health_check",
                    "hotswap", "rollback", "state_transfer",
                )
            }
            result["verification_status"] = "not_run"
            result["contracts_verified"] = 0
            result["contracts_unverified"] = 0

        return result

    def reconfigure(
        self,
        transport: Transport | None = None,
        snapshot_manager: SnapshotManager | None = None,
        lifecycle: WorkerLifecycle | None = None,
        health_check: Callable[[], HealthResult] | HealthCheck | None = None,
    ) -> None:
        """Swap injected dependencies without restarting the supervisor process."""
        # Gap 1.8: validate new transport before swapping, release lock during hooks
        if transport is not None:
            # Validate before any swap
            transport.configure()
            with self._lock:
                old = self.transport
                self.transport = transport
            # Release lock while calling external hooks
            old.on_supervisor_stop()
            self.transport.on_supervisor_start()

        with self._lock:
            if snapshot_manager is not None:
                self.snapshots = snapshot_manager
            if lifecycle is not None:
                self.lifecycle = lifecycle
            if health_check is not None:
                self.health_check = health_check
        logger.info("Supervisor reconfigured")

    def _validate_source(
        self, source_path: Path, import_check: bool = False
    ) -> None:
        """Basic validation of source code."""
        if source_path.is_dir():
            py_files = list(source_path.rglob("*.py"))
            if not py_files:
                raise ValueError("Source directory contains no Python files")
            if import_check:
                # Find the first non-__init__.py file to import-check
                for py_file in py_files:
                    if py_file.name == "__init__.py":
                        continue
                    self._import_check_source(py_file)
                    break
        elif source_path.suffix == ".py":
            # Syntax check
            compile(source_path.read_text(encoding="utf-8"), str(source_path), "exec")
            if import_check:
                self._import_check_source(source_path)
        else:
            # Non-Python files are allowed but not validated
            pass

    def _import_check_source(self, source_path: Path) -> None:
        """Attempt to import the module in a subprocess to verify dependencies."""
        cmd = [sys.executable, "-c", f"import importlib.util; spec = importlib.util.spec_from_file_location('__hp_check', {str(source_path)!r}); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30.0)
            if proc.returncode != 0:
                raise ValueError(
                    f"Import check failed for {source_path}: {proc.stderr.strip()}"
                )
        except subprocess.TimeoutExpired:
            raise ValueError(f"Import check timed out for {source_path}")

    def _monitor_loop(self) -> None:
        """Watch for unexpected child death and crash loops."""
        while not self._stop_event.is_set():
            self._stop_event.wait(1.0)
            with self._lock:
                started = self._started
                proc = self._proc
                state = self._state
            if not started:
                continue

            if state in ("unrecoverable", "updated", "rolling_back"):
                continue

            if proc is not None and proc.poll() is not None:
                # Child died unexpectedly
                exit_code = proc.returncode
                logger.error("Worker exited unexpectedly with code %s", exit_code)
                in_loop = self._crash_detector.record_crash()
                if in_loop:
                    logger.critical("Crash loop detected — entering cooldown")
                    time.sleep(self._cooldown_seconds)

                # Gap 1.5: check if we should give up
                self._crash_detector.record_restart()
                if self._crash_detector.give_up():
                    logger.critical(
                        "Max restarts (%d) exceeded within window; entering UNRECOVERABLE state",
                        self._crash_detector.max_restarts,
                    )
                    self._set_state("unrecoverable")
                    continue

                safe = self.snapshots.get_safe_path()
                if safe and self.worker_path:
                    config = self.transport.configure()
                    try:
                        new_proc = self.lifecycle.rollback_and_restart(
                            safe, self.worker_path, self.worker_cmd, config
                        )
                        with self._lock:
                            self._proc = new_proc
                            if self._state != "rolling_back":
                                self._state = "running"
                        if hasattr(self.transport, "set_process"):
                            self.transport.set_process(new_proc)
                        logger.info("Restarted worker from safe version after crash")
                    except Exception:
                        logger.exception("Failed to restart worker after crash")
                        self._set_state("degraded")
                elif self.worker_cmd:
                    config = self.transport.configure()
                    try:
                        new_proc = self.lifecycle.spawn(self.worker_cmd, config)
                        with self._lock:
                            self._proc = new_proc
                            if self._state != "rolling_back":
                                self._state = "running"
                        if hasattr(self.transport, "set_process"):
                            self.transport.set_process(new_proc)
                        logger.info("Restarted worker without safe version")
                    except Exception:
                        logger.exception("Failed to restart worker")
                        self._set_state("degraded")
