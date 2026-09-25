#!/usr/bin/env python3
"""littlewing — session history archive CLI for flight-recorder.

Ingests Claude Code session JSONL logs, generates digested summaries,
and provides cross-project session search.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "raw"
DIGESTED_DIR = REPO_ROOT / "digested"
FORMATS_DIR = Path(__file__).resolve().parent / "formats"


def find_claude_projects_dir():
    """Locate the Claude Code projects directory."""
    candidates = [
        Path.home() / ".claude" / "projects",
        Path("/root/.claude/projects"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def project_key_from_cwd(jsonl_path):
    """Extract a project key by reading the cwd field from the JSONL data.

    The JSONL events carry the real working directory path unambiguously.
    Returns basename of cwd, e.g. '/home/user/my-cool-project' -> 'my-cool-project'.
    Falls back to directory-name heuristic if the JSONL can't be read.
    """
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    cwd = event.get("cwd")
                    if cwd:
                        return Path(cwd).name
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return _project_key_from_dirname(Path(jsonl_path).parent.name)


def _project_key_from_dirname(dirname):
    """Fallback: decode Claude's directory name encoding.

    Claude encodes absolute paths by replacing '/' with '-'.
    e.g. '-home-user-cbtdag' -> 'cbtdag'
         '-home-user-my-cool-project' -> 'my-cool-project'
    """
    stripped = dirname.lstrip("-")
    for prefix_pattern in ["home-"]:
        if stripped.startswith(prefix_pattern):
            after_home = stripped[len(prefix_pattern):]
            dash = after_home.find("-")
            if dash != -1:
                return after_home[dash + 1:]
            return after_home
    if stripped.startswith("root-"):
        return stripped[len("root-"):]
    return stripped or "unknown"


def cmd_ingest(args):
    """Ingest session logs into the archive."""
    if args.file:
        # Ingest a specific file
        src = Path(args.file)
        if not src.exists():
            print(f"Error: {src} does not exist", file=sys.stderr)
            return 1
        project = args.project or "unknown"
        dest_dir = RAW_DIR / project
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.exists() and not args.force:
            # Update if source is newer/larger
            if src.stat().st_size > dest.stat().st_size:
                shutil.copy2(src, dest)
                print(f"Updated {dest.name} ({dest.stat().st_size} bytes)")
            else:
                print(f"Skipped {dest.name} (already archived, use --force to overwrite)")
        else:
            shutil.copy2(src, dest)
            print(f"Archived {dest.name} ({dest.stat().st_size} bytes)")
        return 0

    if args.scan:
        # Scan Claude projects directory for all sessions
        proj_dir = find_claude_projects_dir()
        if not proj_dir:
            print("Error: cannot locate ~/.claude/projects/", file=sys.stderr)
            return 1

        count = 0
        for subdir in sorted(proj_dir.iterdir()):
            if not subdir.is_dir():
                continue
            # Derive project name from first JSONL's cwd field
            jsonl_files = sorted(subdir.glob("*.jsonl"))
            if not jsonl_files:
                continue
            project = args.project or project_key_from_cwd(jsonl_files[0])
            dest_dir = RAW_DIR / project
            dest_dir.mkdir(parents=True, exist_ok=True)

            for jsonl in jsonl_files:
                dest = dest_dir / jsonl.name
                if dest.exists() and not args.force:
                    if jsonl.stat().st_size > dest.stat().st_size:
                        shutil.copy2(jsonl, dest)
                        print(f"  Updated {project}/{jsonl.name}")
                        count += 1
                    # else skip silently
                else:
                    shutil.copy2(jsonl, dest)
                    print(f"  Archived {project}/{jsonl.name}")
                    count += 1

        print(f"\nIngested {count} session(s).")
        return 0

    print("Error: provide --file or --scan", file=sys.stderr)
    return 1


def extract_session_metadata(jsonl_path):
    """Extract key metadata from a session JSONL file."""
    meta = {
        "session_id": jsonl_path.stem,
        "project": jsonl_path.parent.name,
        "file": str(jsonl_path),
        "size_bytes": jsonl_path.stat().st_size,
        "events": 0,
        "first_ts": None,
        "last_ts": None,
        "user_messages": 0,
        "assistant_messages": 0,
        "first_user_text": None,
        "tool_calls": [],
        "files_touched": set(),
        "errors": [],
        "commits": [],
    }

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            meta["events"] += 1
            ts = event.get("timestamp")
            if ts:
                if meta["first_ts"] is None:
                    meta["first_ts"] = ts
                meta["last_ts"] = ts

            etype = event.get("type")
            if etype == "user":
                meta["user_messages"] += 1
                if meta["first_user_text"] is None:
                    text = _extract_text(event.get("message", {}))
                    if text.strip():
                        meta["first_user_text"] = text.strip()
            elif etype == "assistant":
                meta["assistant_messages"] += 1
                for block in event.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        meta["tool_calls"].append(tool_name)
                        inp = block.get("input", {})
                        for key in ("file_path", "path", "file"):
                            if key in inp and isinstance(inp[key], str):
                                meta["files_touched"].add(inp[key])
                        cmd = inp.get("command", "")
                        if isinstance(cmd, str) and "git commit" in cmd:
                            meta["commits"].append(cmd[:120])

    meta["files_touched"] = sorted(meta["files_touched"])

    tool_counts = {}
    for t in meta["tool_calls"]:
        tool_counts[t] = tool_counts.get(t, 0) + 1
    meta["tool_summary"] = dict(sorted(tool_counts.items(), key=lambda x: -x[1]))
    del meta["tool_calls"]

    return meta


def _parse_ts(ts_str):
    """Parse an ISO timestamp string to a datetime. Returns None on failure."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_date_filter(date_str):
    """Parse a date filter — ISO date, datetime, or relative like '3d', '1w'."""
    if not date_str:
        return None
    relative = re.match(r'^(\d+)([dhwm])$', date_str)
    if relative:
        from datetime import timedelta
        n = int(relative.group(1))
        unit = relative.group(2)
        deltas = {'d': timedelta(days=n), 'h': timedelta(hours=n),
                  'w': timedelta(weeks=n), 'm': timedelta(days=n * 30)}
        return datetime.now(timezone.utc) - deltas[unit]
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _format_duration(first_ts, last_ts):
    """Format duration between two ISO timestamps as human-readable."""
    start = _parse_ts(first_ts)
    end = _parse_ts(last_ts)
    if not start or not end:
        return "?"
    delta = end - start
    total_mins = int(delta.total_seconds() / 60)
    if total_mins < 60:
        return f"{total_mins}m"
    hours, mins = divmod(total_mins, 60)
    return f"{hours}h{mins:02d}m"


def _collect_sessions(project=None):
    """Collect all archived session paths, optionally filtered by project."""
    if not RAW_DIR.exists():
        return []
    dirs = [RAW_DIR / project] if project else sorted(RAW_DIR.iterdir())
    sessions = []
    for proj_dir in dirs:
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            sessions.append(jsonl)
    return sessions


def format_timestamp(ts_str):
    """Format an ISO timestamp to a readable form."""
    if not ts_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return str(ts_str)[:19]


def cmd_digest(args):
    """Generate a digest summary from a raw session log."""
    raw_file, project = _find_raw_session(args.session_id, args.project)
    if not raw_file:
        print(f"Error: session {args.session_id} not found in archive", file=sys.stderr)
        return 1

    meta = extract_session_metadata(raw_file)

    # Build the digest
    lines = [
        f"# Session {meta['session_id'][:8]}",
        f"",
        f"**Project:** {project}",
        f"**Period:** {format_timestamp(meta['first_ts'])} — {format_timestamp(meta['last_ts'])}",
        f"**Events:** {meta['events']} ({meta['user_messages']} user, {meta['assistant_messages']} assistant)",
        f"",
    ]

    if meta["tool_summary"]:
        lines.append("## Tool usage")
        lines.append("")
        for tool, count in list(meta["tool_summary"].items())[:15]:
            lines.append(f"- {tool}: {count}")
        lines.append("")

    if meta["files_touched"]:
        lines.append("## Files touched")
        lines.append("")
        for f in meta["files_touched"][:30]:
            lines.append(f"- `{f}`")
        lines.append("")

    if meta["commits"]:
        lines.append("## Git commits")
        lines.append("")
        for c in meta["commits"]:
            lines.append(f"- `{c}`")
        lines.append("")

    digest_text = "\n".join(lines) + "\n"

    # Write digest
    dest_dir = DIGESTED_DIR / project
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{meta['session_id']}.md"
    dest.write_text(digest_text)
    print(f"Digest written to {dest}")

    if args.stdout:
        print()
        print(digest_text)

    return 0


def _resolve_session_anchor(anchor_id, project=None):
    """Look up a session's start timestamp by ID prefix. Returns datetime or None."""
    path, _ = _find_raw_session(anchor_id, project)
    if not path:
        return None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                ts = event.get("timestamp")
                if ts:
                    return _parse_ts(ts)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def cmd_list(args):
    """List archived sessions with metadata, sorted by date."""
    sessions = _collect_sessions(args.project)
    if not sessions:
        print("No sessions archived yet.")
        return 0

    since = _parse_date_filter(args.since) if args.since else None
    before = _parse_date_filter(args.before) if args.before else None

    anchor_id = None
    if args.after_session:
        anchor_id = args.after_session
        anchor_dt = _resolve_session_anchor(anchor_id, args.project)
        if not anchor_dt:
            print(f"Session '{anchor_id}' not found.", file=sys.stderr)
            return 1
        since = anchor_dt
    if args.before_session:
        anchor_id = args.before_session
        anchor_dt = _resolve_session_anchor(anchor_id, args.project)
        if not anchor_dt:
            print(f"Session '{anchor_id}' not found.", file=sys.stderr)
            return 1
        before = anchor_dt

    entries = []
    for s in sessions:
        if anchor_id and s.stem.startswith(anchor_id):
            continue
        meta = extract_session_metadata(s)
        start_dt = _parse_ts(meta["first_ts"])

        if since and start_dt and start_dt < since:
            continue
        if before and start_dt and start_dt > before:
            continue

        entries.append(meta)

    # after-session: oldest first (chronological after the anchor)
    # before-session: newest first (most recent before the anchor)
    # default: newest first, unless --oldest
    if args.after_session:
        entries.sort(key=lambda m: m.get("first_ts") or "")
    elif args.before_session:
        entries.sort(key=lambda m: m.get("first_ts") or "", reverse=True)
    else:
        entries.sort(key=lambda m: m.get("first_ts") or "", reverse=not args.oldest)

    if args.limit:
        entries = entries[:args.limit]

    if not entries:
        print("No sessions match the given filters.")
        return 0

    cur_project = None
    for meta in entries:
        proj = meta["project"]
        if proj != cur_project:
            cur_project = proj
            print(f"\n{proj}/")

        sid = meta["session_id"][:8]
        start = format_timestamp(meta["first_ts"])
        dur = _format_duration(meta["first_ts"], meta["last_ts"])
        turns = f"{meta['user_messages']}u/{meta['assistant_messages']}a"
        size_kb = meta["size_bytes"] / 1024
        preview = ""
        if meta["first_user_text"]:
            preview = meta["first_user_text"][:60].replace("\n", " ")
            if len(meta["first_user_text"]) > 60:
                preview += "..."

        print(f"  {sid}  {start}  {dur:>7s}  {turns:>7s}  {size_kb:5.0f}KB  {preview}")

    print(f"\n{len(entries)} session(s)")
    return 0


def cmd_digest_all(args):
    """Generate digests for all sessions that don't have one yet."""
    if not RAW_DIR.exists():
        print("No sessions archived yet.")
        return 0

    count = 0
    projects = sorted(RAW_DIR.iterdir()) if not args.project else [RAW_DIR / args.project]

    for proj_dir in projects:
        if not proj_dir.is_dir():
            continue
        for jsonl in sorted(proj_dir.glob("*.jsonl")):
            digest_path = DIGESTED_DIR / proj_dir.name / f"{jsonl.stem}.md"
            if digest_path.exists() and not args.force:
                continue
            args_copy = argparse.Namespace(
                session_id=jsonl.stem,
                project=proj_dir.name,
                stdout=False,
            )
            cmd_digest(args_copy)
            count += 1

    print(f"\nGenerated {count} digest(s).")
    return 0


def _load_formats():
    """Discover available output format plugins."""
    sys.path.insert(0, str(FORMATS_DIR.parent))
    from formats import discover
    return discover()


def _extract_text(message):
    """Extract text content from a user or assistant message object."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
    return str(content)


def extract_conversation(jsonl_path):
    """Extract user/assistant conversation turns from a JSONL file."""
    turns = []
    first_ts = None
    last_ts = None
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = event.get("timestamp", "")
            if ts:
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
            etype = event.get("type")
            if etype not in ("user", "assistant"):
                continue
            text = _extract_text(event.get("message", {}))
            if not text.strip():
                continue
            turns.append({
                "role": etype,
                "timestamp": ts,
                "text": text,
            })
    return turns, first_ts, last_ts


def _find_raw_session(session_id, project=None):
    """Locate a raw JSONL by session ID (or prefix). Returns (path, project)."""
    candidates = []
    search_dirs = [RAW_DIR / project] if project else sorted(RAW_DIR.iterdir())
    for proj_dir in search_dirs:
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            if jsonl.stem == session_id or jsonl.stem.startswith(session_id):
                candidates.append((jsonl, proj_dir.name))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print(f"Ambiguous prefix '{session_id}', matches:", file=sys.stderr)
        for c, p in candidates:
            print(f"  {p}/{c.stem}", file=sys.stderr)
        return None, None
    return None, None


def cmd_conversation(args):
    """Extract and format the conversation from a session."""
    formats = _load_formats()

    fmt_name = args.format
    if fmt_name not in formats:
        print(f"Unknown format '{fmt_name}'. Available: {', '.join(sorted(formats))}",
              file=sys.stderr)
        return 1

    raw_file, project = _find_raw_session(args.session_id, args.project)
    if not raw_file:
        print(f"Session '{args.session_id}' not found in archive", file=sys.stderr)
        return 1

    turns, first_ts, last_ts = extract_conversation(raw_file)
    if not turns:
        print("No conversation turns found.", file=sys.stderr)
        return 1

    metadata = {
        "session_id": raw_file.stem,
        "project": project,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }

    fmt_mod = formats[fmt_name]
    output = fmt_mod.format_conversation(turns, metadata)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}")
    else:
        print(output)

    return 0


def cmd_search(args):
    """Search across session conversations for a pattern."""
    sessions = _collect_sessions(args.project)
    if not sessions:
        print("No sessions archived yet.")
        return 0

    try:
        pattern = re.compile(args.query, re.IGNORECASE)
    except re.error as e:
        print(f"Invalid regex: {e}", file=sys.stderr)
        return 1

    hits = []
    for s in sessions:
        turns, first_ts, last_ts = extract_conversation(s)
        session_hits = []
        for i, turn in enumerate(turns):
            matches = list(pattern.finditer(turn["text"]))
            if matches:
                session_hits.append((i, turn, matches))

        if session_hits:
            meta = extract_session_metadata(s)
            hits.append((meta, session_hits))

    if not hits:
        print(f"No matches for '{args.query}'.")
        return 0

    hits.sort(key=lambda h: h[0].get("first_ts") or "", reverse=True)

    if args.limit:
        hits = hits[:args.limit]

    for meta, session_hits in hits:
        sid = meta["session_id"][:8]
        proj = meta["project"]
        start = format_timestamp(meta["first_ts"])
        dur = _format_duration(meta["first_ts"], meta["last_ts"])
        print(f"\n{proj}/{sid}  {start}  {dur}  ({len(session_hits)} matching turn(s))")

        shown = 0
        for turn_idx, turn, matches in session_hits:
            if shown >= args.context:
                remaining = len(session_hits) - shown
                if remaining > 0:
                    print(f"    ... {remaining} more matching turn(s)")
                break
            role = turn["role"].upper()
            text = turn["text"]
            for m in matches[:1]:
                start_pos = max(0, m.start() - 40)
                end_pos = min(len(text), m.end() + 40)
                snippet = text[start_pos:end_pos].replace("\n", " ")
                if start_pos > 0:
                    snippet = "..." + snippet
                if end_pos < len(text):
                    snippet = snippet + "..."
                print(f"    [{role} #{turn_idx + 1}] {snippet}")
            shown += 1

    print(f"\n{len(hits)} session(s) matched.")
    return 0


def _resolve_session(raw_dir, prefix):
    """Find a raw JSONL file matching a session ID prefix."""
    matches = [f for f in raw_dir.glob("*.jsonl") if f.stem.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact = [f for f in matches if f.stem == prefix]
        if len(exact) == 1:
            return exact[0]
    return None


def _load_session(raw_file, project):
    """Load turns and metadata from a raw session file."""
    turns, first_ts, last_ts = extract_conversation(raw_file)
    metadata = {
        "session_id": raw_file.stem,
        "project": project,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }
    return turns, metadata


def cmd_bridge(args):
    """Generate a context bridge file from the most recent prior session.

    Finds the latest archived session for a project, extracts the
    user/assistant conversation as markdown, and writes it to a file.
    Prints the file path, size, line count, and turn count to stdout
    so the calling agent can appraise token cost before reading.

    Designed for session-start context loading: generate first, check
    size, then decide whether to read all/tail/skip.
    """
    project = args.project
    if not project:
        project = Path.cwd().name

    sessions = _collect_sessions(project)
    if not sessions:
        print(f"No archived sessions for project '{project}'.")
        return 1

    # Find the most recent session by modification time, excluding the
    # current session if its ID was provided
    candidates = []
    for s in sessions:
        if args.exclude and s.stem.startswith(args.exclude):
            continue
        meta = extract_session_metadata(s)
        candidates.append((meta.get("first_ts") or "", s, meta))

    if not candidates:
        print(f"No prior sessions found for '{project}'.")
        return 1

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, raw_file, meta = candidates[0]

    turns, first_ts, last_ts = extract_conversation(raw_file)
    if not turns:
        print(f"Most recent session {raw_file.stem[:8]} has no conversation turns.")
        return 1

    metadata = {
        "session_id": raw_file.stem,
        "project": project,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }

    # Try semantic bridge overlay if --enhance requested or auto (large session)
    enhanced = False
    enhance = getattr(args, "enhance", False)
    if enhance:
        try:
            from overlays import get_overlay
            output, _ = get_overlay(
                raw_file.stem, project, "bridge", turns, metadata
            )
            enhanced = True
        except Exception as e:
            print(f"note: semantic overlay unavailable ({e}), using verbatim", file=sys.stderr)

    if not enhanced:
        formats = _load_formats()
        fmt_mod = formats["markdown"]
        output = fmt_mod.format_conversation(turns, metadata)

    # Write to file
    out_path = Path(args.output) if args.output else Path(f"/tmp/bridge-{project}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output)

    line_count = output.count("\n")
    size_bytes = len(output.encode("utf-8"))
    turn_count = len(turns)
    user_turns = sum(1 for t in turns if t["role"] == "user")
    asst_turns = sum(1 for t in turns if t["role"] == "assistant")
    duration = _format_duration(first_ts, last_ts)

    mode = "enhanced" if enhanced else "verbatim"
    print(f"bridge: {out_path}  ({mode})")
    print(f"session: {raw_file.stem[:8]}  {format_timestamp(first_ts)}  {duration}")
    print(f"size: {size_bytes} bytes  {line_count} lines  {turn_count} turns ({user_turns}u/{asst_turns}a)")

    if not enhanced and size_bytes > 50_000:
        print(f"warning: large bridge ({size_bytes // 1024}KB) — consider --enhance or reading only the tail")

    return 0


def cmd_overlay(args):
    """Generate or list semantic overlays for a session."""
    try:
        from overlays import get_overlay, list_types
    except ImportError as e:
        print(f"error: overlay system unavailable ({e})", file=sys.stderr)
        return 1

    if args.list_types:
        types = list_types()
        if not types:
            print("no overlay types registered")
        for name, desc in sorted(types.items()):
            print(f"  {name:12s}  {desc}")
        return 0

    if not args.session:
        print("error: session ID required (or use --list-types)", file=sys.stderr)
        return 1

    project = args.project or Path.cwd().name
    raw_dir = REPO_ROOT / "raw" / project
    if not raw_dir.exists():
        print(f"error: no raw data for project '{project}'", file=sys.stderr)
        return 1

    raw_file = _resolve_session(raw_dir, args.session)
    if not raw_file:
        print(f"error: no session matching '{args.session}' in {project}", file=sys.stderr)
        return 1

    turns, metadata = _load_session(raw_file, project)

    try:
        content, cache_path = get_overlay(
            raw_file.stem, project, args.type, turns, metadata,
            force=args.force, model=args.model,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: overlay generation failed: {e}", file=sys.stderr)
        return 1

    print(f"overlay: {cache_path}")
    print(f"session: {raw_file.stem[:8]}  type: {args.type}")
    size = len(content.encode("utf-8"))
    print(f"size: {size} bytes  {content.count(chr(10))} lines")

    if args.stdout:
        print("---")
        print(content)

    return 0


def cmd_formats(args):
    """List available output formats."""
    formats = _load_formats()
    for name in sorted(formats):
        mod = formats[name]
        desc = getattr(mod, "DESCRIPTION", "")
        ext = getattr(mod, "EXT", "")
        print(f"  {name:12s}  {ext:6s}  {desc}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="littlewing",
        description="Session history archive CLI for flight-recorder",
    )
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest session logs into the archive")
    p_ingest.add_argument("--file", help="Specific JSONL file to ingest")
    p_ingest.add_argument("--scan", action="store_true", help="Scan ~/.claude/projects/ for all sessions")
    p_ingest.add_argument("--project", help="Project name (default: derived from path)")
    p_ingest.add_argument("--force", action="store_true", help="Overwrite existing archives")

    # digest
    p_digest = sub.add_parser("digest", help="Generate a digest from a raw session log")
    p_digest.add_argument("session_id", help="Session UUID (or prefix)")
    p_digest.add_argument("--project", help="Project name")
    p_digest.add_argument("--stdout", action="store_true", help="Also print to stdout")

    # digest-all
    p_da = sub.add_parser("digest-all", help="Generate digests for all undigested sessions")
    p_da.add_argument("--project", help="Limit to one project")
    p_da.add_argument("--force", action="store_true", help="Regenerate existing digests")

    # list
    p_list = sub.add_parser("list", help="List archived sessions")
    p_list.add_argument("--project", help="Filter by project")
    p_list.add_argument("--since", help="Only sessions starting after (ISO date, or relative: 3d, 1w, 2m)")
    p_list.add_argument("--before", help="Only sessions starting before (ISO date, or relative)")
    p_list.add_argument("--after-session", help="Sessions starting after this session (ID or prefix)")
    p_list.add_argument("--before-session", help="Sessions starting before this session (ID or prefix)")
    p_list.add_argument("--limit", "-n", type=int, help="Max sessions to show")
    p_list.add_argument("--oldest", action="store_true", help="Sort oldest first (default: newest first)")

    # conversation
    p_conv = sub.add_parser("conversation", help="Extract conversation text from a session")
    p_conv.add_argument("session_id", help="Session UUID (or unique prefix)")
    p_conv.add_argument("--project", help="Project name")
    p_conv.add_argument("--format", default="plain",
                        help="Output format (default: plain). Use 'formats' command to list.")
    p_conv.add_argument("--output", "-o", help="Write to file instead of stdout")

    # search
    p_search = sub.add_parser("search", help="Search across sessions for a pattern")
    p_search.add_argument("query", help="Regex pattern to search for (case-insensitive)")
    p_search.add_argument("--project", help="Limit to one project")
    p_search.add_argument("--limit", "-n", type=int, help="Max sessions to show")
    p_search.add_argument("--context", "-c", type=int, default=5,
                          help="Max matching turns to show per session (default: 5)")

    # bridge
    p_bridge = sub.add_parser("bridge",
                              help="Generate context bridge from most recent prior session")
    p_bridge.add_argument("--project", help="Project name (default: cwd basename)")
    p_bridge.add_argument("--output", "-o", help="Output file path (default: /tmp/bridge-<project>.md)")
    p_bridge.add_argument("--exclude", help="Session ID (or prefix) to exclude (e.g. current session)")
    p_bridge.add_argument("--enhance", action="store_true",
                          help="Use LLM to generate a semantic bridge (requires DeepSeek or litellm)")

    # overlay
    p_overlay = sub.add_parser("overlay",
                               help="Generate or list semantic overlays for a session")
    p_overlay.add_argument("session", nargs="?", help="Session ID (or prefix)")
    p_overlay.add_argument("--type", "-t", default="summary",
                           help="Overlay type (default: summary)")
    p_overlay.add_argument("--project", help="Project name (default: cwd basename)")
    p_overlay.add_argument("--force", action="store_true",
                           help="Regenerate even if cached")
    p_overlay.add_argument("--model", help="Override LLM model")
    p_overlay.add_argument("--list-types", action="store_true",
                           help="List available overlay types and exit")
    p_overlay.add_argument("--stdout", action="store_true",
                           help="Print overlay to stdout instead of just caching")

    # formats
    sub.add_parser("formats", help="List available output formats")

    args = parser.parse_args()

    if args.command == "ingest":
        return cmd_ingest(args)
    elif args.command == "digest":
        return cmd_digest(args)
    elif args.command == "digest-all":
        return cmd_digest_all(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "conversation":
        return cmd_conversation(args)
    elif args.command == "search":
        return cmd_search(args)
    elif args.command == "bridge":
        return cmd_bridge(args)
    elif args.command == "overlay":
        return cmd_overlay(args)
    elif args.command == "formats":
        return cmd_formats(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
