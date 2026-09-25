"""Markdown conversation format with delta timestamps.

First timestamp is absolute (session start). All subsequent timestamps are
deltas from session start, e.g. +7h12m14s. This avoids repeating 28-byte
ISO strings on every turn — a 36-turn conversation saves ~750 bytes of
pure timestamp overhead, and the deltas are more readable (you see pacing
without mental date arithmetic).

Deltas are computed against the session start timestamp to avoid
cumulative drift from chained per-message deltas.
"""

from datetime import datetime, timezone

NAME = "markdown"
DESCRIPTION = "Markdown with headers and delta timestamps"
EXT = ".md"


def _parse_ts(ts_str):
    """Parse ISO timestamp to datetime. Returns None on failure."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _format_delta(seconds):
    """Format a duration in seconds as compact human-readable delta."""
    if seconds < 0:
        seconds = 0
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"+{h}h{m:02d}m{s:02d}s"
    if m > 0:
        return f"+{m}m{s:02d}s"
    return f"+{s}s"


def _format_abs(dt):
    """Format a datetime as a compact absolute timestamp."""
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_conversation(events, metadata):
    sid = metadata.get("session_id", "unknown")[:8]
    project = metadata.get("project", "unknown")
    first_ts = metadata.get("first_ts")
    last_ts = metadata.get("last_ts")

    start_dt = _parse_ts(first_ts)
    end_dt = _parse_ts(last_ts)

    duration = ""
    if start_dt and end_dt:
        dur_secs = (end_dt - start_dt).total_seconds()
        duration = f"  ({_format_delta(dur_secs).lstrip('+')})"

    lines = [
        f"# Conversation {sid}",
        "",
        f"**Project:** {project}",
        f"**Start:** {_format_abs(start_dt) if start_dt else '?'}{duration}",
        "",
        "---",
        "",
    ]

    turn = 0
    for ev in events:
        turn += 1
        role = "User" if ev["role"] == "user" else "Assistant"
        ts_str = ev.get("timestamp", "")
        ev_dt = _parse_ts(ts_str)

        if turn == 1 and ev_dt:
            ts_label = _format_abs(ev_dt)
        elif ev_dt and start_dt:
            delta = (ev_dt - start_dt).total_seconds()
            ts_label = _format_delta(delta)
        else:
            ts_label = ""

        header = f"### {role} #{turn}"
        if ts_label:
            header += f"  _{ts_label}_"
        lines.append(header)
        lines.append("")
        lines.append(ev["text"])
        lines.append("")
    return "\n".join(lines)
