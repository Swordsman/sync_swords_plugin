"""Git repo transport — commit and push to a remote repository.

Writes files into a local git checkout, commits, and optionally pushes.
Useful for keeping session logs in a version-controlled archive.

Config example:
    {"name": "git", "root": "/home/user/flight-recorder/raw", "auto_push": true}
"""

import os
import subprocess
from pathlib import Path
from backends.transports import Transport


class GitTransport(Transport):
    name = "git"

    def __init__(self, root: str, auto_push: bool = False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.auto_push = auto_push

    def _path(self, key: str) -> Path:
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"invalid key: {key!r}")
        return self.root / safe

    def _git_root(self) -> Path | None:
        """Walk up from self.root to find the git repo root."""
        p = self.root
        while p != p.parent:
            if (p / ".git").exists():
                return p
            p = p.parent
        return None

    def _git(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.setdefault("GIT_AUTHOR_NAME", "littlewing")
        env.setdefault("GIT_AUTHOR_EMAIL", "littlewing@flight-recorder")
        env.setdefault("GIT_COMMITTER_NAME", "littlewing")
        env.setdefault("GIT_COMMITTER_EMAIL", "littlewing@flight-recorder")
        return subprocess.run(
            ["git"] + args,
            cwd=str(cwd or self._git_root() or self.root),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def write(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

        git_root = self._git_root()
        if not git_root:
            return

        self._git(["add", str(p)], cwd=git_root)
        diff = self._git(["diff", "--cached", "--quiet"], cwd=git_root)
        if diff.returncode != 0:
            self._git(
                ["commit", "-m", f"archive {key}"],
                cwd=git_root,
            )
            if self.auto_push:
                self._git(["push"], cwd=git_root)

    def read(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise KeyError(key)
        return p.read_bytes()

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*")
            if p.is_file()
        )

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()
            git_root = self._git_root()
            if git_root:
                self._git(["add", str(p)], cwd=git_root)
                self._git(
                    ["commit", "-m", f"remove {key}"],
                    cwd=git_root,
                )
                if self.auto_push:
                    self._git(["push"], cwd=git_root)
