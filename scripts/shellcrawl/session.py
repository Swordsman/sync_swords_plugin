"""ShellCrawl session: ties VirtualFS + pisces evaluator + builtins together."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from pisces.eval import Evaluator

from .builtins import ShellCrawlRuntime
from .vfs import VirtualFS

_SHELL_DIR = Path(__file__).parent / "shell"
_WORLDS_DIR = Path(__file__).parent / "worlds"


class ShellCrawlSession:
    """A single shell session that an explorer interacts with."""

    def __init__(self, fs: Optional[VirtualFS] = None,
                 max_steps: int = 1_000_000,
                 timeout: float = 30.0) -> None:
        self.fs = fs or VirtualFS()
        self._ensure_base_dirs()
        self.runtime = ShellCrawlRuntime(self.fs)
        self.evaluator = self.runtime.create_evaluator(
            max_steps=max_steps, timeout=timeout,
        )
        self._load_shell_layer()

    def _ensure_base_dirs(self) -> None:
        for d in ("/home/user", "/tmp", "/var/log", "/etc", "/usr/bin",
                   "/usr/local/bin", "/root", "/opt", "/proc", "/dev"):
            if not self.fs.exists(d):
                self.fs.mkdir(d, parents=True)

    def _load_shell_layer(self) -> None:
        for name in ("core.psc", "commands.psc"):
            path = _SHELL_DIR / name
            if path.exists():
                self.evaluator.eval_string(path.read_text())

    def load_world(self, name: str) -> None:
        path = _WORLDS_DIR / f"{name}.psc"
        if path.exists():
            self.evaluator.eval_string(path.read_text())

    def execute(self, cmdline: str) -> Tuple[str, str, int]:
        """Run a command. Returns (stdout, stderr, exit_code)."""
        self.runtime.stdout_buf.clear()
        self.runtime.stderr_buf.clear()

        cmdline = cmdline.strip()
        if not cmdline:
            return "", "", 0

        try:
            self.evaluator._start_time = None
            exit_code = self.evaluator.eval_string(
                f'(dispatch-command "{_escape(cmdline)}")'
            )
        except Exception as e:
            self.runtime.stderr_buf.append(f"bash: internal error: {e}\n")
            exit_code = 1

        stdout = "".join(self.runtime.stdout_buf)
        stderr = "".join(self.runtime.stderr_buf)
        return stdout, stderr, int(exit_code) if isinstance(exit_code, (int, float)) else 1

    def prompt(self) -> str:
        cwd = self.runtime.state.get("cwd", "/")
        user = self.runtime.state.get("user", "user")
        hostname = self.runtime.state.get("hostname", "localhost")
        home = self.runtime.state.get("home", "/home/user")
        display = cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd
        return f"{user}@{hostname}:{display}$ "

    def inject_pisces(self, code: str) -> None:
        """Eval arbitrary pisces code (used by DM to extend the world)."""
        self.evaluator.eval_string(code)


def _escape(s: str) -> str:
    """Escape a string for embedding in a pisces double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
