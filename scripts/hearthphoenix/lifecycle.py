"""WorkerLifecycle — spawn, kill, await health, rollback and restart."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .contracts import Contract, precondition
from .health import HealthResult, HealthStatus

logger = logging.getLogger(__name__)


class WorkerLifecycle(Contract):
    """Manages the lifecycle of a worker subprocess."""

    def __init__(self, log_mode: str = "devnull") -> None:
        """Initialize lifecycle manager.

        Args:
            log_mode: One of "devnull" (default), "inherit", or "file".
                "devnull" — redirect stdout/stderr to /dev/null.
                "inherit" — inherit parent's stdout/stderr.
                "file" — capture to rotating log files in .hearthphoenix/logs/.
        """
        self.log_mode = log_mode

    def spawn(self, cmd: list[str], config: dict[str, str]) -> subprocess.Popen:
        """Spawn a worker subprocess with the given config as environment variables."""
        env = os.environ.copy()
        env.update(config)
        logger.info("Spawning worker: %s", " ".join(cmd))

        stdout: int | Any = subprocess.DEVNULL
        stderr: int | Any = subprocess.DEVNULL

        if self.log_mode == "inherit":
            stdout = None
            stderr = None
        elif self.log_mode == "file":
            log_path = self._ensure_log_file()
            # Open in append mode; file handle will be inherited by child
            fh = open(log_path, "a", encoding="utf-8")
            stdout = fh
            stderr = fh

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
        return proc

    def _ensure_log_file(self) -> Path:
        """Return a rotating log file path, pruning old logs if needed."""
        log_dir = Path.home() / ".hearthphoenix" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        pid = os.getpid()
        log_path = log_dir / f"worker-{pid}-{timestamp}.log"

        existing = sorted(
            log_dir.glob("worker-*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if existing and existing[0].stat().st_size < 10 * 1024 * 1024:
            for old in existing[5:]:  # keep 5 most recent
                try:
                    old.unlink()
                except OSError:
                    pass
            return existing[0]
        else:
            for old in existing[4:]:  # make room for the new file
                try:
                    old.unlink()
                except OSError:
                    pass
            return log_path

    @precondition(lambda self, proc, graceful_timeout=5.0: proc.poll() is None)
    def kill(self, proc: subprocess.Popen, graceful_timeout: float = 5.0) -> bool:
        """Kill a worker process.

        Returns True if the process exited gracefully, False if SIGKILL was required.
        """
        logger.info("Sending SIGTERM to worker PID %s", proc.pid)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=graceful_timeout)
            return True
        except subprocess.TimeoutExpired:
            logger.warning(
                "Worker PID %s did not exit gracefully; sending SIGKILL", proc.pid
            )
            proc.kill()
            proc.wait()
            return False

    def await_healthy(
        self,
        health_check_fn: Callable[[], HealthResult],
        timeout: float = 10.0,
        retries: int = 5,
    ) -> HealthResult:
        """Poll a health check function until healthy or exhausted."""
        interval = timeout / max(retries, 1)
        for attempt in range(retries):
            try:
                result = health_check_fn()
                if result.status == HealthStatus.HEALTHY:
                    logger.info("Health check passed on attempt %d", attempt + 1)
                    return result
            except Exception as exc:
                logger.debug("Health check attempt %d raised: %s", attempt + 1, exc)
            time.sleep(interval)
        return HealthResult(
            status=HealthStatus.UNHEALTHY,
            message=f"Health check failed after {retries} retries over {timeout}s",
        )

    def rollback_and_restart(
        self,
        safe_path: Path,
        target_path: Path,
        cmd: list[str],
        config: dict[str, str],
    ) -> subprocess.Popen:
        """Restore safe version to target_path and spawn a new worker."""
        logger.info("Rolling back to safe version: %s -> %s", safe_path, target_path)
        if target_path.exists():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()

        if safe_path.is_dir():
            shutil.copytree(safe_path, target_path)
        else:
            shutil.copy2(safe_path, target_path)

        return self.spawn(cmd, config)
