"""Explode a Claude Code session JSONL into a navigable directory tree.

Structure:
    <session-id>/
        meta.json                       # session metadata
        blobs/                          # content-addressed dedup store
            <sha256>.json               # unique large payloads (prompt snapshots)
        raw.jsonl.zst                   # compressed verbatim original
        seg-000/                        # segment 0 (initial context)
            segment.json                # segment metadata (boundary info)
            raw.jsonl                   # verbatim lines for this segment
            000-<type>-<short-id>/      # each message is a folder
                raw.json                # verbatim original JSON line
                envelope.json           # extracted envelope (for browsing)
                thinking.txt            # extracted thinking (if present)
                tool-calls/             # tool calls (if present)
                    <tool-name>-<id>.json
        seg-001/                        # after first compaction
            ...

Design:
    - raw.json in each message folder IS the verbatim original line
    - envelope.json, thinking.txt, tool-calls/ are derived views for navigation
    - blobs/ deduplicates large repeated payloads (prompt snapshots)
    - Per-segment raw.jsonl lets you reconstruct that segment's original lines
    - Top-level raw.jsonl.zst is the whole original, compressed
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _short_id(uuid_str: str) -> str:
    if not uuid_str:
        return "no-id"
    return uuid_str[:8]


def _safe_name(s: str) -> str:
    return s.replace("/", "-").replace("\\", "-").replace(" ", "-")[:40]


def _detect_segments(raw_lines: list[str]) -> list[int]:
    """Return line indices where new segments start (compaction boundaries)."""
    boundaries = [0]
    for i, line in enumerate(raw_lines):
        if i == 0:
            continue
        obj = json.loads(line)
        if (obj.get("type") == "attachment"
                and obj.get("attachment", {}).get("type") == "prompt_snapshot"):
            if i not in boundaries:
                boundaries.append(i)
    return sorted(set(boundaries))


def _extract_envelope(msg: dict, seq: int) -> dict:
    """Extract the envelope (metadata) from a message for browsing."""
    env = {
        "seq": seq,
        "type": msg.get("type", "unknown"),
        "uuid": msg.get("uuid", ""),
        "parentUuid": msg.get("parentUuid"),
        "timestamp": msg.get("timestamp"),
    }
    for k in ("sessionId", "cwd", "version", "gitBranch", "permissionMode",
              "isSidechain", "requestId", "promptId"):
        if k in msg:
            env[k] = msg[k]

    inner = msg.get("message", {})
    if inner.get("model"):
        env["model"] = inner["model"]
    if inner.get("stop_reason"):
        env["stop_reason"] = inner["stop_reason"]
    if msg.get("type") == "attachment":
        env["attachment_type"] = msg.get("attachment", {}).get("type", "")

    return env


def _extract_derived(msg: dict, msg_dir: Path):
    """Write derived views (thinking, tool-calls) alongside the raw."""
    inner = msg.get("message", {})
    content = inner.get("content")

    if not isinstance(content, list):
        return

    thinking_blocks = []
    tool_calls = []

    for p in content:
        if not isinstance(p, dict):
            continue
        pt = p.get("type", "")
        if pt in ("thinking", "think"):
            text = p.get("thinking") or p.get("think", "")
            if text and text.strip():
                thinking_blocks.append(text)
        elif pt == "tool_use":
            tool_calls.append(p)

    if thinking_blocks:
        with open(msg_dir / "thinking.txt", "w") as f:
            f.write("\n\n---\n\n".join(thinking_blocks))

    if tool_calls:
        tc_dir = msg_dir / "tool-calls"
        tc_dir.mkdir(exist_ok=True)
        for tc in tool_calls:
            tc_id = tc.get("id", "unknown")
            tc_name = tc.get("name", "unknown")
            fname = f"{_safe_name(tc_name)}-{_short_id(tc_id)}.json"
            with open(tc_dir / fname, "w") as f:
                json.dump(tc, f, indent=2)


def explode_session(jsonl_path: str, output_dir: str, session_id: str | None = None) -> dict:
    """Explode a session JSONL into a directory tree.

    Each message folder contains raw.json (verbatim original line) plus
    derived views for navigation. The whole original is also preserved
    compressed at the top level.
    """
    jsonl_path = Path(jsonl_path)
    if session_id is None:
        session_id = jsonl_path.stem

    out = Path(output_dir) / session_id
    blobs = out / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)

    with open(jsonl_path) as f:
        raw_lines = [line.rstrip("\n") for line in f if line.strip()]

    boundaries = _detect_segments(raw_lines)
    segments = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(raw_lines)
        segments.append((start, end))

    first_msg = json.loads(raw_lines[0])
    last_msg = json.loads(raw_lines[-1])
    session_meta = {
        "session_id": session_id,
        "source": str(jsonl_path),
        "total_lines": len(raw_lines),
        "total_segments": len(segments),
        "segment_boundaries": boundaries,
        "sessionId": first_msg.get("sessionId", ""),
        "first_timestamp": first_msg.get("timestamp", ""),
        "last_timestamp": last_msg.get("timestamp", ""),
    }

    stats = {
        "segments": len(segments),
        "messages": len(raw_lines),
        "blobs_deduped": 0,
        "blobs_written": 0,
        "bytes_saved": 0,
    }

    blob_hashes = {}

    for seg_idx, (start, end) in enumerate(segments):
        seg_dir = out / f"seg-{seg_idx:03d}"
        seg_dir.mkdir(parents=True, exist_ok=True)

        # Write per-segment raw.jsonl (verbatim lines for this segment)
        with open(seg_dir / "raw.jsonl", "w") as f:
            for line_idx in range(start, end):
                f.write(raw_lines[line_idx] + "\n")

        first_seg_msg = json.loads(raw_lines[start])
        last_seg_msg = json.loads(raw_lines[end - 1])
        seg_meta = {
            "segment": seg_idx,
            "line_range": [start, end],
            "message_count": end - start,
            "start_timestamp": first_seg_msg.get("timestamp", ""),
            "end_timestamp": last_seg_msg.get("timestamp", ""),
        }

        for seq, line_idx in enumerate(range(start, end)):
            raw_line = raw_lines[line_idx]
            msg = json.loads(raw_line)
            t = msg.get("type", "unknown")
            uid = _short_id(msg.get("uuid", ""))

            att_type = ""
            if t == "attachment":
                att_type = msg.get("attachment", {}).get("type", "")
                dirname = f"{seq:03d}-{_safe_name(t)}-{_safe_name(att_type)}-{uid}"
            else:
                dirname = f"{seq:03d}-{_safe_name(t)}-{uid}"

            msg_dir = seg_dir / dirname
            msg_dir.mkdir(parents=True, exist_ok=True)

            # Verbatim original line — the source of truth
            with open(msg_dir / "raw.json", "w") as f:
                f.write(raw_line + "\n")

            # Derived envelope for browsing
            envelope = _extract_envelope(msg, seq)
            with open(msg_dir / "envelope.json", "w") as f:
                json.dump(envelope, f, indent=2)

            # Derived thinking/tool-call views
            _extract_derived(msg, msg_dir)

            # Dedup large repeated content into blobs
            if att_type == "prompt_snapshot":
                payload = msg.get("attachment", {})
                payload_str = json.dumps(payload, sort_keys=True)
                h = _sha256(payload_str)
                blob_path = blobs / f"{h}.json"
                if h in blob_hashes:
                    stats["blobs_deduped"] += 1
                    stats["bytes_saved"] += len(payload_str)
                else:
                    blob_hashes[h] = blob_path
                    with open(blob_path, "w") as f:
                        f.write(payload_str)
                    stats["blobs_written"] += 1
                # Write a reference marker alongside the raw
                with open(msg_dir / "blob-ref.json", "w") as f:
                    json.dump({"$ref": f"../../blobs/{h}.json", "size": len(payload_str)}, f, indent=2)

        with open(seg_dir / "segment.json", "w") as f:
            json.dump(seg_meta, f, indent=2)

    with open(out / "meta.json", "w") as f:
        json.dump(session_meta, f, indent=2)

    # Compress the whole original
    has_zstd = subprocess.run(["which", "zstd"], capture_output=True).returncode == 0
    if has_zstd:
        subprocess.run(
            ["zstd", "-3", "-f", str(jsonl_path), "-o", str(out / "raw.jsonl.zst")],
            capture_output=True, timeout=60,
        )
    else:
        import gzip
        with open(jsonl_path, "rb") as fin, gzip.open(out / "raw.jsonl.gz", "wb") as fout:
            fout.write(fin.read())

    return stats


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <session.jsonl> <output-dir>")
        sys.exit(1)

    jsonl = sys.argv[1]
    outdir = sys.argv[2]
    sid = sys.argv[3] if len(sys.argv) > 3 else None

    stats = explode_session(jsonl, outdir, sid)
    print(json.dumps(stats, indent=2))
