#!/usr/bin/env python3
"""littlewing hook: records the live session through the configured modes.

One script serves every hook event; hooks/hooks.json wires it up:

  event                         trigger        runs as
  PostToolUse Bash `git push`   push           background, may wake Claude
  PostToolUse create PR         pr             background, may wake Claude
  Stop (after each reply)       stop           background, may wake Claude
  PreCompact                    compact        background, never wakes
  SessionEnd                    session_end    detached child, never wakes
  SessionStart                  session_start  sync, prints queued uploads

With both modes off (the default) it exits at once.

Waking Claude: when records are queued for Claude Docs, the hook prints
upload instructions on stderr and exits 2. Under `asyncRewake` that wakes
Claude, even when the session is idle; under a plain Stop hook it keeps
Claude going; under PostToolUse it shows Claude the message. PreCompact
never exits 2, because a synchronous PreCompact hook that exits 2 blocks
compaction. The next trigger announces whatever it queued.

SAFETY INVARIANTS:
  1. Exit 0 unless deliberately asking Claude to upload (exit 2).
  2. stdlib only.
  3. Garbage or missing stdin is fine: no trigger, exit 0.
  4. No writes to the project repo; everything goes under littlewing's home
     or into the configured sinks.
  5. Idempotent: state records what each sink already has.

Manual use: `littlewing_hook.py --trigger manual < hook-input.json`, or
`littlewing.py record`.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

EVENTS = {"Stop": "stop", "PreCompact": "compact",
          "SessionEnd": "session_end", "SessionStart": "session_start"}
_PUSH = re.compile(r"\bgit\s+(?:-[Cc]\s+\S+\s+|--?[\w-]+(?:=\S+)?\s+)*push\b")
_GH_PR = re.compile(r"\bgh\s+pr\s+create\b")


def classify(hook: dict) -> str | None:
    """Map a hook payload to a littlewing trigger, or None to ignore it."""
    event = hook.get("hook_event_name", "")
    if event == "PostToolUse":
        tool = hook.get("tool_name", "")
        if tool == "Bash":
            cmd = (hook.get("tool_input") or {}).get("command", "")
            if _GH_PR.search(cmd):
                return "pr"
            if _PUSH.search(cmd):
                return "push"
            return None
        if tool.endswith("create_pull_request"):
            return "pr"
        return None
    return EVENTS.get(event)


def find_transcript(hook: dict) -> str | None:
    tp = hook.get("transcript_path")
    if tp and Path(tp).is_file():
        return tp
    sid = hook.get("session_id")
    projects = Path.home() / ".claude" / "projects"
    if sid and projects.is_dir():
        for p in projects.glob(f"*/{sid}.jsonl"):
            return str(p)
    return None


def _read_stdin() -> dict:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read(4 << 20)
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _detach(hook: dict) -> None:
    """Re-run as a detached child, so SessionEnd's 1.5 s budget isn't the limit."""
    fd, path = tempfile.mkstemp(prefix="littlewing-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(hook, f)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", path],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def main(argv: list[str]) -> int:
    hook, forced, child = {}, None, False
    if "--child" in argv:
        child = True
        path = argv[argv.index("--child") + 1]
        try:
            hook = json.loads(Path(path).read_text())
        finally:
            Path(path).unlink(missing_ok=True)
    else:
        hook = _read_stdin()
    if "--trigger" in argv:
        forced = argv[argv.index("--trigger") + 1]
    trigger = forced or classify(hook)
    if not trigger:
        return 0

    import lwconfig
    cfg = lwconfig.load(hook.get("cwd") or os.getcwd())
    if not lwconfig.any_enabled(cfg):
        return 0

    import recorder
    if trigger == "session_start":
        if cfg["triggers"].get("session_start", True):
            text, ids = recorder.notice(cfg, force=True)
            if text:
                print(text)        # SessionStart stdout becomes Claude's context
        return 0
    if trigger == "session_end" and not child:
        _detach(hook)
        return 0

    tp = find_transcript(hook)
    sid = hook.get("session_id") or (Path(tp).stem if tp else None)
    if not tp or not sid:
        return 0
    recorder.Recorder(cfg, sid, tp, hook.get("cwd") or os.getcwd()).run(trigger, hook)

    if trigger in ("compact", "session_end") or hook.get("stop_hook_active"):
        return 0
    text, ids = recorder.notice(cfg)
    if not text:
        return 0
    from backends.transports.claude_docs import Outbox
    Outbox(cfg["home"]).mark_announced(ids)
    print(text, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except SystemExit:
        raise
    except Exception:
        code = 0            # invariant 1: a broken recorder never breaks the session
    sys.exit(code)
