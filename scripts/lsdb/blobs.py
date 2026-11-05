"""Large text as blobs: parts at blobs/<key>/parts/<nnnn>, a manifest at blobs/<key> written last.

A reader that finds the manifest finds every part. Part sizes are measured as ASCII-escaped JSON,
an upper bound of the UTF-8 size, so a part is under the doc limit however the server counts.
"""

import hashlib
import json
import re
from datetime import datetime, timezone

from . import catalog, reads, writes
from .transport import LsdbError, call

COLLECTION = "blobs"
DESCRIPTION = "Large text split into parts: blobs/<key> is the manifest, blobs/<key>/parts/<nnnn> the text"
PART_BYTES = 200_000       # doc limit is 256 KiB (262,144)
REQUEST_BYTES = 900_000    # request limit is 1 MiB
MAX_PARTS = 10_000
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def put_blob(url, key: str, text: str, meta=None) -> dict:
    """Store `text` under `key`, replacing any earlier blob; returns the manifest."""
    _check_key(key)
    pieces = list(split_text(text))
    if len(pieces) > MAX_PARTS:
        raise ValueError(f"blob needs {len(pieces)} parts; at most {MAX_PARTS}")
    old = _manifest(url, key)
    data = text.encode("utf-8")
    manifest = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "parts": len(pieces),
                "meta": meta or {}, "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write_ops(url, [writes.write_op("set", _part_path(key, i), {"text": piece}) for i, piece in enumerate(pieces)])
    writes.set_doc(url, f"{COLLECTION}/{key}", manifest)
    catalog.register(url, COLLECTION, DESCRIPTION)
    if old:
        _delete_parts(url, key, range(len(pieces), old["parts"]))
    return manifest


def get_blob(url, key: str) -> str:
    """The text stored under `key`; KeyError if absent, LsdbError if parts are missing or corrupt."""
    manifest = _manifest(url, key)
    if manifest is None:
        raise KeyError(f"no blob {key!r}")
    docs = {doc["id"]: doc["data"]["text"] for doc in reads.list_all(url, f"{COLLECTION}/{key}/parts")}
    ids = [f"{i:04d}" for i in range(manifest["parts"])]
    if [i for i in ids if i not in docs]:
        raise LsdbError(f"blob {key!r}: parts missing (manifest says {manifest['parts']}, found {len(docs)})")
    data = "".join(docs[i] for i in ids).encode("utf-8")
    if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise LsdbError(f"blob {key!r}: sha256 mismatch (changed while reading, or corrupt)")
    return data.decode("utf-8")


def delete_blob(url, key: str) -> None:
    """Remove the manifest first, then every part (also strays left by an interrupted put)."""
    _check_key(key)
    writes.delete_doc(url, f"{COLLECTION}/{key}")
    stray = [doc["id"] for doc in reads.list_all(url, f"{COLLECTION}/{key}/parts")]
    _delete_parts(url, key, stray)


def split_text(text: str, limit: int = PART_BYTES):
    """Yield pieces whose JSON size is at most `limit`; empty text yields one empty piece."""
    pos = 0
    while pos < len(text) or not pos:
        count = limit - 2
        while (size := len(json.dumps(piece := text[pos:pos + count]))) > limit:
            count = max(1, count * (limit - 64) // size)
        yield piece
        if not text:
            return
        pos += len(piece)


def _manifest(url, key):
    reply = reads.get(url, f"{COLLECTION}/{key}")
    return reply["data"] if reply.get("exists") else None


def _part_path(key, index) -> str:
    return f"{COLLECTION}/{key}/parts/{index:04d}"


def _check_key(key) -> None:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ValueError(f"blob key must match {_KEY_RE.pattern}, not {key!r}")


def _delete_parts(url, key, indexes_or_ids) -> None:
    paths = [_part_path(key, i) if isinstance(i, int) else f"{COLLECTION}/{key}/parts/{i}" for i in indexes_or_ids]
    _write_ops(url, [writes.write_op("delete", path) for path in paths])


def _write_ops(url, entries: list) -> None:
    """Batch entries in requests of at most 50 ops and REQUEST_BYTES (bypasses per-blob catalog entries)."""
    group, size = [], 0
    for entry in entries:
        cost = len(json.dumps(entry))
        if group and (len(group) == writes.MAX_BATCH_OPS or size + cost > REQUEST_BYTES):
            call(url, "batch", {"ops": group})
            group, size = [], 0
        group.append(entry)
        size += cost
    if group:
        call(url, "batch", {"ops": group})
