"""Supervisor-side client for a bootstrap subreaper (bootstrap.py).

The fleet layer tracks bootstraps, not daemons — the bootstrap is the
stable identity (see design/bootstrap-subreaper-design.md). This module
gives the supervisor a typed handle over the bootstrap's FIFO command
channel and JSON state file:

    handle = BootstrapHandle.launch(["python", "my_daemon.py"], run_dir)
    pid = handle.wait_for_daemon(timeout=10)
    handle.restart()          # cycle the daemon; tree survives
    handle.spawn(["worker"])  # child owned by the bootstrap
    handle.stop()             # stop daemon, bootstrap exits
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .procid import same_process


class BootstrapError(RuntimeError):
    """The bootstrap process is gone or refusing commands."""


class BootstrapHandle:
    """Client for one bootstrap subreaper instance."""

    def __init__(self, fifo_path: Path, state_path: Path,
                 proc: subprocess.Popen | None = None) -> None:
        self.fifo_path = Path(fifo_path)
        self.state_path = Path(state_path)
        self.proc = proc  # set when this handle launched the bootstrap

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def launch(cls, daemon_cmd: list[str], run_dir: Path,
               graceful_timeout: float = 30.0) -> "BootstrapHandle":
        """Start a bootstrap subreaper for *daemon_cmd*.

        *run_dir* holds the control FIFO and state file; one directory
        per managed service.
        """
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        fifo = run_dir / "control.fifo"
        state = run_dir / "state.json"
        # Detach: the bootstrap (and its daemon) must not hold the
        # launcher's stdio pipes or die with the launcher's session —
        # a short-lived CLI invocation is a normal launcher.
        with open(run_dir / "bootstrap.log", "ab") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "hearthphoenix.bootstrap",
                 "--fifo", str(fifo), "--state", str(state),
                 "--graceful-timeout", str(graceful_timeout), "--", *daemon_cmd],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        return cls(fifo, state, proc)

    @classmethod
    def attach(cls, run_dir: Path) -> "BootstrapHandle":
        """Attach to an already-running bootstrap by its run directory."""
        run_dir = Path(run_dir)
        return cls(run_dir / "control.fifo", run_dir / "state.json")

    # -- state -----------------------------------------------------------

    def state(self) -> dict:
        """Latest bootstrap state (raises if never written)."""
        try:
            return json.loads(self.state_path.read_text())
        except FileNotFoundError:
            raise BootstrapError(f"no state file at {self.state_path}") from None

    @property
    def daemon_pid(self) -> int | None:
        try:
            return self.state().get("daemon_pid")
        except BootstrapError:
            return None

    def bootstrap_alive(self) -> bool:
        if self.proc is not None:
            return self.proc.poll() is None
        try:
            pid = self.state().get("bootstrap_pid")
        except BootstrapError:
            return False
        if not pid:
            return False
        return same_process(pid, None)

    def daemon_alive(self) -> bool:
        """Liveness with PID-reuse detection: the pid must exist AND match
        the start-time identity the bootstrap recorded at spawn."""
        try:
            st = self.state()
        except BootstrapError:
            return False
        pid = st.get("daemon_pid")
        if not pid:
            return False
        return same_process(pid, st.get("daemon_start"))

    def wait_for_daemon(self, timeout: float = 10.0,
                        exclude_pid: int | None = None) -> int:
        """Block until a daemon pid (different from *exclude_pid*) appears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pid = self.daemon_pid
            if pid and pid != exclude_pid:
                return pid
            time.sleep(0.05)
        raise BootstrapError(f"daemon not up within {timeout}s")

    # -- commands --------------------------------------------------------

    def send(self, msg: dict) -> None:
        """Write one command to the bootstrap's FIFO."""
        try:
            fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno in (errno.ENXIO, errno.ENOENT):
                raise BootstrapError("bootstrap is not listening") from e
            raise
        try:
            os.write(fd, (json.dumps(msg) + "\n").encode())
        finally:
            os.close(fd)

    def restart(self, wait: bool = True, timeout: float = 10.0) -> int | None:
        """Cycle the daemon. Returns the new daemon pid when *wait* is True."""
        old_pid = self.daemon_pid
        self.send({"cmd": "restart"})
        if wait:
            return self.wait_for_daemon(timeout, exclude_pid=old_pid)
        return None

    def spawn(self, argv: list[str]) -> None:
        """Fork+exec *argv* as a child owned by the bootstrap."""
        self.send({"cmd": "spawn", "argv": [str(a) for a in argv]})

    def stop(self, wait: bool = True, timeout: float = 15.0) -> None:
        """Stop the daemon and shut the bootstrap down."""
        self.send({"cmd": "stop"})
        if not wait:
            return
        if self.proc is not None:
            self.proc.wait(timeout=timeout)
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.bootstrap_alive():
                return
            time.sleep(0.05)
        raise BootstrapError(f"bootstrap did not exit within {timeout}s")
