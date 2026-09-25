"""Plain text conversation format."""

NAME = "plain"
DESCRIPTION = "Plain text with role labels"
EXT = ".txt"


def format_conversation(events, metadata):
    lines = []
    for ev in events:
        role = ev["role"].upper()
        lines.append(f"[{role}]")
        lines.append(ev["text"])
        lines.append("")
    return "\n".join(lines)
