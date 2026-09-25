"""Rclone transport — Google Drive, OneDrive, S3, and 40+ other providers.

Requires rclone installed and a remote configured via `rclone config`.

Config example:
    {"name": "rclone", "remote": "gdrive", "path": "littlewing/raw"}

This maps to rclone paths like `gdrive:littlewing/raw/<key>`.
"""

import shutil
import subprocess
from backends.transports import Transport


class RcloneTransport(Transport):
    name = "rclone"

    def __init__(self, remote: str, path: str = ""):
        if not shutil.which("rclone"):
            raise RuntimeError("rclone not installed — apt-get install rclone")
        self.remote = remote
        self.base_path = path.rstrip("/")

    def _remote_path(self, key: str = "") -> str:
        parts = [self.remote + ":"]
        if self.base_path:
            parts.append(self.base_path)
        if key:
            parts.append(key)
        return "/".join(parts) if len(parts) > 1 else parts[0] + (self.base_path or "")

    def _run(self, args: list[str], input_data: bytes | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["rclone"] + args,
            input=input_data,
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"rclone {' '.join(args[:2])}: {result.stderr.decode(errors='replace').strip()}"
            )
        return result

    def write(self, key: str, data: bytes) -> None:
        dest = self._remote_path(key)
        self._run(["rcat", dest], input_data=data)

    def read(self, key: str) -> bytes:
        dest = self._remote_path(key)
        try:
            result = self._run(["cat", dest])
        except RuntimeError as e:
            if "not found" in str(e).lower() or "404" in str(e):
                raise KeyError(key) from e
            raise
        return result.stdout

    def list(self) -> list[str]:
        dest = self._remote_path()
        try:
            result = self._run(["lsf", "-R", dest])
        except RuntimeError:
            return []
        lines = result.stdout.decode(errors="replace").strip().splitlines()
        return sorted(l for l in lines if l and not l.endswith("/"))

    def exists(self, key: str) -> bool:
        dest = self._remote_path(key)
        result = subprocess.run(
            ["rclone", "lsf", dest],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0 and bool(result.stdout.strip())

    def delete(self, key: str) -> None:
        dest = self._remote_path(key)
        subprocess.run(
            ["rclone", "deletefile", dest],
            capture_output=True,
            timeout=30,
        )
