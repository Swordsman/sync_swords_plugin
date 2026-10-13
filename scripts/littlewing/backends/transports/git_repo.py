"""Git repo transport — commit and push to a remote repository.

Writes files into a local git checkout, commits, and optionally pushes.
Useful for keeping session logs in a version-controlled archive.

Config example:
    {"transport": "git", "root": "~/session-archive/raw", "auto_push": true,
     "url": "git@github.com:you/session-archive.git"}

`root` may be a subdirectory of the checkout. With `url` set, a missing
checkout is cloned on first write. Commits use your normal git identity;
set `author_name` / `author_email` to override it.
"""

import os
import subprocess
from pathlib import Path
from backends.transports import Transport


class GitTransport(Transport):
    name = "git"

    def __init__(self, root: str, auto_push: bool = False, url: str | None = None,
                 author_name: str | None = None, author_email: str | None = None,
                 timeout: int = 60):
        self.root = Path(root).expanduser()
        self.auto_push = auto_push
        self.url = url
        self.author_name = author_name
        self.author_email = author_email
        self.timeout = timeout
        if url and not self._git_root():
            self._clone()
        self.root.mkdir(parents=True, exist_ok=True)

    def _clone(self) -> None:
        """Clone `url` so that `root` falls inside the checkout.

        The checkout goes at the highest missing directory on root's path:
        root ~/archive/raw with ~/archive missing clones into ~/archive.
        """
        checkout = self.root
        while not checkout.parent.exists() and checkout.parent != checkout:
            checkout = checkout.parent
        checkout.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", self.url, str(checkout)],
                       capture_output=True, text=True, timeout=self.timeout)

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
        if self.author_name:
            env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = self.author_name
        if self.author_email:
            env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = self.author_email
        return subprocess.run(
            ["git"] + args,
            cwd=str(cwd or self._git_root() or self.root),
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout,
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
