"""SessionStart / UserPromptSubmit hook: hand Claude the new notes Joe left in the Data Store inbox.

Off unless CLAUDE_DATA_STORE names this account's store artifact. Each note is passed once per
session; prompts check at most every THROTTLE_S seconds. Never fails the hook: errors are dropped.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # the plugin's scripts/, for lsdb

STORE_ENV = "CLAUDE_DATA_STORE"
THROTTLE_S = 600
MAX_NOTES = 20
MAX_CHARS = 6000
STATE = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "sync-swords") / "inbox_hook.json"


def new_notes(url: str) -> list:
    import lsdb
    return lsdb.query(url, "inbox", where=[("status", "==", "new")], limit=MAX_NOTES)


def context_for(url: str, notes: list) -> str:
    lines = [f"Data Store inbox ({url}): {len(notes)} new note(s) Joe left on the store page."]
    lines += [f"- inbox/{note['id']} ({note['data'].get('createdAt', '?')}): {note['data'].get('text', '')}" for note in notes]
    lines.append("A note is closed with lsdb.update_doc(url, 'inbox/<id>', {'status': 'done', 'reply': '...'}); "
                 "the reply shows under the note on the page.")
    return "\n".join(lines)[:MAX_CHARS]


def run(event: dict, url: str, state: dict, now: float):
    """Return (additionalContext or None, new state)."""
    session = event.get("session_id", "")
    if state.get("session") != session:
        state = {"session": session, "passed": [], "checked": 0}
    if event.get("hook_event_name") == "UserPromptSubmit" and now - state["checked"] < THROTTLE_S:
        return None, state
    state["checked"] = now
    fresh = [note for note in new_notes(url) if note["id"] not in state["passed"]]
    if not fresh:
        return None, state
    state["passed"] += [note["id"] for note in fresh]
    return context_for(url, fresh), state


def main() -> None:
    url = os.environ.get(STORE_ENV, "").strip()
    if not url:
        return
    try:
        event = json.load(sys.stdin)
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        text, state = run(event, url, state, time.time())
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event["hook_event_name"], "additionalContext": text}}))
    except Exception:   # a hook must never break the session; the next check retries
        return


if __name__ == "__main__":
    main()
