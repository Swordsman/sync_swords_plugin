"""JSONL conversation format — one turn per line, pipeable."""

import json as _json

NAME = "jsonl"
DESCRIPTION = "One JSON object per turn, pipe-friendly"
EXT = ".jsonl"


def format_conversation(events, metadata):
    lines = []
    for ev in events:
        lines.append(_json.dumps(ev, ensure_ascii=False))
    return "\n".join(lines) + "\n"
