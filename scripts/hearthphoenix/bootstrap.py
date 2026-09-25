"""Bootstrap subreaper — immortal parent for self-restartable daemons.

Implements design/bootstrap-subreaper-design.md: a trivial, immortal
process that spawns the real daemon, relays commands via a named pipe,
and reaps orphaned descendants using ``PR_SET_CHILD_SUBREAPER`` so the
daemon can be killed and replaced without collapsing its process tree.

Run as: ``python -m hearthphoenix.bootstrap --fifo PATH --state PATH -- CMD...``

Commands (newline-delimited JSON written to the FIFO):
    {"cmd": "restart"}                — cycle the daemon (SIGTERM → SIGKILL)
    {"cmd": "stop"}                   — stop daemon and exit the bootstrap
    {"cmd": "spawn", "argv": [...]}   — fork+exec a child owned by the bootstrap
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import logging
import os
import select
import signal
import sys
import time
from pathlib import Path

from .procid import proc_start_jiffies

logger = logging.getLogger(__name__)

PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37


def set_child_subreaper() -> bool:
    """Mark this process as a child subreaper. Returns True on success."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            return False
        flag = ctypes.c_int(0)
        libc.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(flag), 0, 0, 0)
        return flag.value == 1
    except (OSError, AttributeError):
        return False


class Bootstrap:
    """Immortal parent: spawn daemon, relay commands, reap descendants."""

    def __init__(self, daemon_cmd: list[str], fifo_path: Path, state_path: Path,
                 graceful_timeout: float = 30.0) -> None:
        self.daemon_cmd = daemon_cmd
        self.fifo_path = Path(fifo_path)
        self.state_path = Path(state_path)
        self.graceful_timeout = graceful_timeout
        self.daemon_pid: int | None = None
        self.restarts = 0
        self.reaped: list[int] = []
        self.spawned: list[int] = []
        self._stopping = False
        self._sig_r, self._sig_w = os.pipe()
        for fd in (self._sig_r, self._sig_w):
            os.set_blocking(fd, False)
            os.set_inheritable(fd, False)

    # -- state ----------------------------------------------------------

    def _write_state(self) -> None:
        state = {"bootstrap_pid": os.getpid(), "daemon_pid": self.daemon_pid,
                 "daemon_start": (proc_start_jiffies(self.daemon_pid)
                                  if self.daemon_pid else None),
                 "restarts": self.restarts, "reaped": self.reaped,
                 "spawned": self.spawned, "stopping": self._stopping}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(self.state_path)

    # -- process management ---------------------------------------------

    def _fork_exec(self, argv: list[str]) -> int:
        pid = os.fork()
        if pid == 0:  # child
            try:
                os.execvp(argv[0], argv)
            except OSError:
                os._exit(127)
        return pid

    def _spawn_daemon(self) -> None:
        self.daemon_pid = self._fork_exec(self.daemon_cmd)
        logger.info("daemon spawned: pid=%d", self.daemon_pid)
        self._write_state()

    def _kill_daemon(self) -> None:
        if self.daemon_pid is None:
            return
        pid = self.daemon_pid
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self.daemon_pid = None
            return
        deadline = time.monotonic() + self.graceful_timeout
        while time.monotonic() < deadline:
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                self.daemon_pid = None
                return
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        self.daemon_pid = None

    def _reap(self) -> None:
        """Reap all exited children; respawn the daemon if it died on us."""
        while True:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return
            if pid == self.daemon_pid:
                self.daemon_pid = None
                if not self._stopping:
                    logger.warning("daemon died; respawning")
                    self.restarts += 1
                    self._spawn_daemon()
            else:
                self.reaped.append(pid)
            self._write_state()

    # -- command handling ------------------------------------------------

    def _handle(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("bad command: %r", line)
            return
        cmd = msg.get("cmd")
        if cmd == "restart":
            self.restarts += 1
            self._kill_daemon()
            self._spawn_daemon()
        elif cmd == "stop":
            self._stopping = True
        elif cmd == "spawn" and isinstance(msg.get("argv"), list):
            self.spawned.append(self._fork_exec([str(a) for a in msg["argv"]]))
            self._write_state()
        else:
            logger.warning("unknown command: %r", msg)

    # -- main loop --------------------------------------------------------

    def run(self) -> None:
        set_child_subreaper()
        signal.signal(signal.SIGCHLD, lambda s, f: os.write(self._sig_w, b"c"))
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: setattr(self, "_stopping", True))
        if not self.fifo_path.exists():
            os.mkfifo(self.fifo_path)
        # O_RDWR keeps the FIFO open even with no writers (no EOF spin).
        fifo_fd = os.open(self.fifo_path, os.O_RDWR | os.O_NONBLOCK)
        os.set_inheritable(fifo_fd, False)
        self._spawn_daemon()
        buf = b""
        while not self._stopping:
            try:
                ready, _, _ = select.select([fifo_fd, self._sig_r], [], [], 1.0)
            except InterruptedError:
                ready = []
            for fd in ready:
                try:
                    data = os.read(fd, 4096)
                except OSError as e:
                    if e.errno != errno.EAGAIN:
                        raise
                    continue
                if fd == self._sig_r:
                    self._reap()
                else:
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            self._handle(line.decode())
            self._reap()
        self._kill_daemon()
        self._write_state()
        os.close(fifo_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fifo", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--graceful-timeout", type=float, default=30.0)
    parser.add_argument("cmd", nargs="+", help="daemon command")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    Bootstrap(args.cmd, args.fifo, args.state, args.graceful_timeout).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
