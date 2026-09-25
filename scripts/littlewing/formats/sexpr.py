"""S-expression conversation format."""

NAME = "sexpr"
DESCRIPTION = "S-expressions, Hy-compatible"
EXT = ".hy"


def _escape(s):
    """Escape a string for s-expression embedding."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _quote(s):
    return '"' + _escape(s) + '"'


def format_conversation(events, metadata):
    sid = _quote(metadata.get("session_id", ""))
    proj = _quote(metadata.get("project", ""))

    parts = ["(conversation"]
    meta_items = [
        f"    (session-id {sid})",
        f"    (project {proj})",
    ]
    if metadata.get("first_ts"):
        meta_items.append(f"    (first-ts {_quote(metadata['first_ts'])})")
    if metadata.get("last_ts"):
        meta_items.append(f"    (last-ts {_quote(metadata['last_ts'])})")

    parts.append("  (meta")
    parts.extend(meta_items)
    parts.append("  )")

    for ev in events:
        role = ev["role"]
        ts = ev.get("timestamp", "")
        text = _quote(ev["text"])
        turn_lines = [f"  (turn (role {role})"]
        if ts:
            turn_lines.append(f"    (ts {_quote(ts)})")
        turn_lines.append(f"    (text {text})")
        turn_lines.append("  )")
        parts.extend(turn_lines)

    parts.append(")")
    return "\n".join(parts) + "\n"
