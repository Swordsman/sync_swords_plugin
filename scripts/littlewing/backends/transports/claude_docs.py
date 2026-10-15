"""Claude Docs transport: an outbox that Claude drains.

A hook can't upload to Claude Docs; only Claude can, with its Artifact
tool. So `write` queues the file in a local outbox with a JSON manifest,
and the hook asks Claude to upload what's queued. After uploading, Claude
runs `littlewing.py outbox done <id> --asset <asset-id>`, which moves the
entry to `sent/`.

Uploads must be text, so files always end in `.txt`; pair this transport
with the base85 transform for anything binary.

Config example:
    {"transport": "claude-docs",
     "docs": ["https://claude.ai/code/artifact/<doc-id>"]}

`docs` is a list: upload to the first one with room, move to the next
when one is full (a doc holds 1 GiB and 5,000 uploads).
"""

import hashlib
import json
import os
import time
from pathlib import Path
from backends.transports import Transport


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Outbox:
    """Queued uploads: <root>/outbox/<id> + <id>.json, moved to sent/ when done."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.pending_dir = self.root / "outbox"
        self.sent_dir = self.root / "sent"

    def add(self, file_id: str, data: bytes, manifest: dict) -> Path:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        path = self.pending_dir / file_id
        tmp = path.with_name(path.name + ".partial")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        manifest = dict(manifest, id=file_id, file=str(path), bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest(), queued=_now())
        self._write_manifest(self.pending_dir / (file_id + ".json"), manifest)
        return path

    def pending(self) -> list[dict]:
        return self._manifests(self.pending_dir)

    def sent(self) -> list[dict]:
        return self._manifests(self.sent_dir)

    def get(self, file_id: str) -> dict | None:
        for m in self.pending() + self.sent():
            if m["id"] == file_id or m["id"].startswith(file_id):
                return m
        return None

    def mark_announced(self, file_ids: list[str]) -> None:
        for fid in file_ids:
            mp = self.pending_dir / (fid + ".json")
            if mp.exists():
                m = json.loads(mp.read_text())
                m["announced"] = _now()
                m["announced_epoch"] = time.time()
                self._write_manifest(mp, m)

    def done(self, file_id: str, asset: str, doc: str | None = None,
             keep_file: bool = True) -> dict:
        matches = [m for m in self.pending() if m["id"] == file_id] or \
                  [m for m in self.pending() if m["id"].startswith(file_id)]
        if len(matches) != 1:
            raise KeyError(f"{len(matches)} pending entries match {file_id!r}")
        m = matches[0]
        self.sent_dir.mkdir(parents=True, exist_ok=True)
        src = self.pending_dir / m["id"]
        dst = self.sent_dir / m["id"]
        if src.exists():
            if keep_file:
                os.replace(src, dst)
            else:
                src.unlink()
        m.update(asset=asset, doc=doc or (m.get("docs") or [None])[0],
                 uploaded=_now(), file=str(dst) if keep_file else None)
        self._write_manifest(self.sent_dir / (m["id"] + ".json"), m)
        (self.pending_dir / (m["id"] + ".json")).unlink(missing_ok=True)
        return m

    @staticmethod
    def _manifests(d: Path) -> list[dict]:
        if not d.is_dir():
            return []
        out = []
        for mp in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(mp.read_text()))
            except (OSError, ValueError):
                continue
        return out

    @staticmethod
    def _write_manifest(path: Path, m: dict) -> None:
        tmp = path.with_name(path.name + ".partial")
        tmp.write_text(json.dumps(m, indent=2) + "\n")
        os.replace(tmp, path)


class ClaudeDocsTransport(Transport):
    name = "claude-docs"
    agent_mediated = True   # the hook queues; Claude uploads
    text_only = True

    def __init__(self, docs, outbox: str, **_ignored):
        self.docs = [docs] if isinstance(docs, str) else list(docs or [])
        if not self.docs:
            raise ValueError("claude-docs transport needs at least one doc url in `docs`")
        self.outbox = Outbox(outbox)

    @staticmethod
    def file_id(key: str) -> str:
        fid = key.strip("/").replace("/", "--")
        return fid if fid.endswith(".txt") else fid + ".txt"

    def write(self, key: str, data: bytes, meta: dict | None = None) -> None:
        self.outbox.add(self.file_id(key), data,
                        dict(meta or {}, key=key, docs=self.docs))

    def read(self, key: str) -> bytes:
        fid = self.file_id(key)
        for d in (self.outbox.pending_dir, self.outbox.sent_dir):
            if (d / fid).exists():
                return (d / fid).read_bytes()
        raise KeyError(f"{key}: not on this machine; download it from Claude Docs "
                       f"with the Artifact tool (read, path=<asset id>)")

    def list(self) -> list[str]:
        return sorted(m["key"] for m in self.outbox.pending() + self.outbox.sent())

    def exists(self, key: str) -> bool:
        return key in self.list()

    def delete(self, key: str) -> None:
        fid = self.file_id(key)
        for d in (self.outbox.pending_dir, self.outbox.sent_dir):
            (d / fid).unlink(missing_ok=True)
            (d / (fid + ".json")).unlink(missing_ok=True)
