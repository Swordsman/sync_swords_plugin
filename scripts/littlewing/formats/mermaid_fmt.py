"""Mermaid sequence diagram format for conversations."""

NAME = "mermaid"
DESCRIPTION = "Mermaid sequence diagram"
EXT = ".mmd"


def _sanitize(s, max_len=72):
    """Sanitize text for mermaid labels: collapse whitespace, truncate, escape."""
    s = " ".join(s.split())
    if len(s) > max_len:
        s = s[:max_len] + "..."
    out = []
    for ch in s:
        if ch in "#;:{}()[]<>|&":
            out.append(" ")
        elif ch == '"':
            out.append("'")
        else:
            out.append(ch)
    return "".join(out).strip() or "..."


def format_conversation(events, metadata):
    sid = metadata.get("session_id", "?")[:8]
    project = metadata.get("project", "")

    lines = ["sequenceDiagram"]
    lines.append("    participant U as User")
    lines.append("    participant A as Assistant")

    if project:
        lines.append(f"    Note over U,A: {_sanitize(project)} / {sid}")

    prev_role = None
    for ev in events:
        role = ev["role"]
        text = _sanitize(ev.get("text", ""))
        ts = ev.get("timestamp", "")
        ts_note = ts[11:19] if len(ts) >= 19 else ""

        if role == "user":
            if ts_note and prev_role != "user":
                lines.append(f"    Note right of U: {ts_note}")
            lines.append(f"    U->>A: {text}")
        elif role == "assistant":
            lines.append(f"    A->>U: {text}")

        prev_role = role

    return "\n".join(lines) + "\n"
