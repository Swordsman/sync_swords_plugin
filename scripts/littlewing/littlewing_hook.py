#!/usr/bin/env python3
"""littlewing hook — session-end archival for flight-recorder.

Designed as a Stop hook for Claude Code. Copies the current session's
JSONL log to the flight-recorder archive and pushes it upstream.

SAFETY INVARIANTS:
  1. Exit 0 ALWAYS. A non-zero exit bricks the session with no recovery.
  2. No imports that might not exist. stdlib only.
  3. No stdin dependency. Hook may receive empty stdin, garbage, or nothing.
  4. Timeout: if anything takes >30s total, bail. (Raised from 5s to
     accommodate git push over network.)
  5. No writes to the project repo. Only writes to flight-recorder.
  6. Idempotent. Running twice on the same session is harmless.
  7. Git push failure is not an error — the archive is local-first,
     push is best-effort.

Hook type: Stop (fires when a session ends)

To connect:
  In ~/.claude/settings.json or .claude/settings.json:
  {
    "hooks": {
      "Stop": [
        {
          "matcher": "",
          "hooks": [
            {
              "type": "command",
              "command": "python3 /path/to/flight-recorder/scripts/littlewing_hook.py"
            }
          ]
        }
      ]
    }
  }
"""

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def timeout_handler(signum, frame):
    sys.exit(0)


def main():
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)
    except (AttributeError, OSError):
        pass

    try:
        _archive()
    except SystemExit:
        raise
    except Exception:
        pass

    return 0


def _archive():
    fr_root = _find_flight_recorder()
    if not fr_root:
        return

    try:
        raw = sys.stdin.read(65536)
    except Exception:
        raw = ""

    hook_data = None
    if raw.strip():
        try:
            hook_data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass

    session_file = _find_session_jsonl(hook_data)
    if not session_file or not session_file.exists():
        return

    project = _project_from_session_path(session_file)

    raw_dir = fr_root / "raw" / project
    try:
        raw_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    dest = raw_dir / session_file.name
    try:
        shutil.copy2(str(session_file), str(dest))
    except OSError:
        return

    # Write breadcrumb
    breadcrumb = fr_root / ".last_hook_fire"
    try:
        breadcrumb.write_text(json.dumps({
            "session": session_file.stem,
            "project": project,
            "archived_bytes": dest.stat().st_size,
            "timestamp": _now_iso(),
        }) + "\n")
    except OSError:
        pass

    # Auto-push: git add, commit, push — best effort, fail silently
    _git_push(fr_root, dest, session_file.stem, project)


def _git_push(fr_root, archived_file, session_id, project):
    """Commit and push the archived session. Best-effort, fail-open."""
    try:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = "littlewing"
        env["GIT_AUTHOR_EMAIL"] = "littlewing@flight-recorder"
        env["GIT_COMMITTER_NAME"] = "littlewing"
        env["GIT_COMMITTER_EMAIL"] = "littlewing@flight-recorder"

        run_opts = dict(cwd=str(fr_root), env=env, timeout=15,
                        capture_output=True, text=True)

        subprocess.run(["git", "add", str(archived_file)], **run_opts)

        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            **run_opts
        )
        if result.returncode == 0:
            return  # nothing to commit

        subprocess.run(
            ["git", "commit", "-m",
             f"archive {project}/{session_id[:8]}"],
            **run_opts
        )

        subprocess.run(
            ["git", "push"],
            cwd=str(fr_root), env=env, timeout=15,
            capture_output=True, text=True
        )
    except (subprocess.TimeoutExpired, OSError, Exception):
        pass  # push is best-effort


def _find_flight_recorder():
    candidates = [
        os.environ.get("FLIGHT_RECORDER_ROOT", ""),
        str(Path.home() / "flight-recorder"),
        str(Path.home() / "repos" / "flight-recorder"),
        str(Path.home() / "src" / "flight-recorder"),
        "/home/user/flight-recorder",
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.is_dir() and (p / "raw").is_dir():
            return p
    return None


def _find_session_jsonl(hook_data):
    session_id = None
    if hook_data and isinstance(hook_data, dict):
        session_id = hook_data.get("session_id") or hook_data.get("sessionId")

    claude_projects = None
    for candidate in [
        Path.home() / ".claude" / "projects",
        Path("/root/.claude/projects"),
    ]:
        if candidate.is_dir():
            claude_projects = candidate
            break

    if not claude_projects:
        return None

    if session_id:
        for proj_dir in claude_projects.iterdir():
            if not proj_dir.is_dir():
                continue
            candidate = proj_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate

    newest = None
    newest_mtime = 0
    for proj_dir in claude_projects.iterdir():
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            mtime = jsonl.stat().st_mtime
            if mtime > newest_mtime:
                newest = jsonl
                newest_mtime = mtime

    return newest


def _project_from_session_path(session_file):
    try:
        with open(session_file) as f:
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
    return _project_key_from_dirname(session_file.parent.name)


def _project_key_from_dirname(dirname):
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


def _now_iso():
    import time
    t = time.gmtime()
    return f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"


if __name__ == "__main__":
    sys.exit(main())
