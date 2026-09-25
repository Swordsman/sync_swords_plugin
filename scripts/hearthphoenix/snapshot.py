"""SnapshotManager with timestamped backups and .safe promotion."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import Contract, ContractViolationError, precondition, postcondition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    """Metadata describing a single snapshot."""

    name: str
    timestamp: str
    label: str | None
    source_path: Path
    snapshot_path: Path
    size: int
    created_at: float
    metadata: dict = field(default_factory=dict)

    @property
    def is_safe(self) -> bool:
        return self.metadata.get("safe", False)


class SnapshotManager(Contract):
    """Manages timestamped snapshots and a designated *safe* version."""

    SAFE_NAME = "safe"
    META_NAME = "snapshots.json"

    def __init__(self, snapshot_dir: str | Path, max_snapshots: int = 10) -> None:
        self.snapshot_dir = Path(snapshot_dir).expanduser().resolve()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.max_snapshots = max_snapshots
        self._meta_path = self.snapshot_dir / self.META_NAME
        self._lock = threading.RLock()
        self._meta: dict[str, dict] = self._load_meta()

    @precondition(lambda self, source_path, label=None: Path(source_path).exists())
    @postcondition(lambda result, self, source_path, label=None: result.snapshot_path.exists())
    def snapshot(self, source_path: str | Path, label: str | None = None) -> Snapshot:
        source_path = Path(source_path).expanduser().resolve()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{source_path.name}.{timestamp}"
        dest = self.snapshot_dir / name
        counter = 1
        while dest.exists():
            name = f"{source_path.name}.{timestamp}-{counter}"
            dest = self.snapshot_dir / name
            counter += 1

        if source_path.is_dir():
            shutil.copytree(source_path, dest)
        else:
            shutil.copy2(source_path, dest)

        info = Snapshot(
            name=name,
            timestamp=timestamp,
            label=label,
            source_path=source_path,
            snapshot_path=dest,
            size=dest.stat().st_size if dest.is_file() else self._dir_size(dest),
            created_at=time.time(),
            metadata={"label": label},
        )

        with self._lock:
            self._meta[name] = {
                "timestamp": info.timestamp,
                "label": info.label,
                "source": str(info.source_path),
                "size": info.size,
                "created_at": info.created_at,
                **info.metadata,
            }
            self._write_meta()
            self.prune(keep=self.max_snapshots)

        logger.info("Snapshot created: %s -> %s", source_path, dest)
        return info

    @precondition(lambda self, snapshot: snapshot.snapshot_path.exists())
    def promote(self, snapshot: Snapshot) -> None:
        with self._lock:
            safe = self.snapshot_dir / self.SAFE_NAME
            if safe.exists() or safe.is_symlink():
                if safe.is_dir() and not safe.is_symlink():
                    shutil.rmtree(safe)
                else:
                    safe.unlink()

            try:
                safe.symlink_to(
                    snapshot.snapshot_path.resolve(),
                    target_is_directory=snapshot.snapshot_path.is_dir(),
                )
            except OSError:
                # Fallback for Windows or when symlinks aren't supported
                if snapshot.snapshot_path.is_dir():
                    shutil.copytree(snapshot.snapshot_path, safe)
                else:
                    shutil.copy2(snapshot.snapshot_path, safe)

            self._meta[snapshot.name]["safe"] = True
            self._write_meta()
        logger.info("Promoted %s to safe slot", snapshot.name)

    @precondition(lambda self, target_path: self.get_safe_path() is not None)
    def restore(self, target_path: str | Path) -> Path:
        with self._lock:
            safe = self.get_safe_path()
            if safe is None:
                raise ContractViolationError("No safe snapshot available to restore")

            dest = Path(target_path).expanduser().resolve()
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()

            if safe.is_dir():
                shutil.copytree(safe, dest)
            else:
                shutil.copy2(safe, dest)

        logger.info("Restored %s -> %s", safe, dest)
        return dest

    def prune(self, keep: int = 5) -> None:
        with self._lock:
            safe = self.get_safe_path()
            safe_target = safe.resolve() if safe and safe.is_symlink() else None
            snaps = [
                p
                for p in self.snapshot_dir.iterdir()
                if p.name in self._meta
            ]
            snaps.sort(key=lambda p: self._meta[p.name].get("created_at", p.stat().st_mtime), reverse=True)
            for old in snaps[keep:]:
                # Protect the safe symlink target from pruning
                if safe_target is not None and old.resolve() == safe_target:
                    continue
                if old.is_dir():
                    shutil.rmtree(old)
                else:
                    old.unlink()
                self._meta.pop(old.name, None)
                logger.debug("Pruned old snapshot: %s", old.name)
            if len(snaps) > keep:
                self._write_meta()

    def get_safe_path(self) -> Path | None:
        with self._lock:
            safe = self.snapshot_dir / self.SAFE_NAME
            return safe if safe.exists() else None

    def list_snapshots(self) -> list[Snapshot]:
        with self._lock:
            infos: list[Snapshot] = []
            for entry in self.snapshot_dir.iterdir():
                if entry.name in (self.META_NAME, self.SAFE_NAME):
                    continue
                meta = self._meta.get(entry.name, {})
                infos.append(
                    Snapshot(
                        name=entry.name,
                        timestamp=meta.get("timestamp", entry.name.split(".")[-1]),
                        label=meta.get("label"),
                        source_path=Path(meta.get("source", "")),
                        snapshot_path=entry,
                        size=meta.get("size", entry.stat().st_size),
                        created_at=meta.get("created_at", entry.stat().st_mtime),
                        metadata=meta,
                    )
                )
            infos.sort(key=lambda i: i.created_at, reverse=True)
            return infos

    def _load_meta(self) -> dict[str, dict]:
        if self._meta_path.exists():
            try:
                with self._meta_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt snapshot metadata; rebuilding from filesystem.")
        return self._rebuild_meta()

    def _write_meta(self) -> None:
        with self._meta_path.open("w", encoding="utf-8") as fh:
            json.dump(self._meta, fh, indent=2, default=str)

    def _rebuild_meta(self) -> dict[str, dict]:
        """Rebuild metadata by scanning the snapshot directory."""
        rebuilt: dict[str, dict] = {}
        ts_pattern = re.compile(r"\.(\d{8}-\d{6})(?:-\d+)?$")
        for entry in self.snapshot_dir.iterdir():
            if entry.name in (self.META_NAME, self.SAFE_NAME):
                continue
            m = ts_pattern.search(entry.name)
            timestamp = m.group(1) if m else ""
            created_at = entry.stat().st_mtime
            size = entry.stat().st_size if entry.is_file() else self._dir_size(entry)
            rebuilt[entry.name] = {
                "timestamp": timestamp,
                "label": None,
                "source": "",
                "size": size,
                "created_at": created_at,
            }
        logger.warning("Rebuilt snapshot metadata from filesystem scan (%d entries).", len(rebuilt))
        return rebuilt

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total
