import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inbox_hook  # noqa: E402

NOTE = {"id": "n1", "data": {"text": "hello", "createdAt": "2026-11-05T22:00:00Z", "status": "new"}}


def test_passes_each_note_once_and_throttles_prompts(monkeypatch):
    monkeypatch.setattr(inbox_hook, "new_notes", lambda url: [NOTE])
    start = {"session_id": "s", "hook_event_name": "SessionStart"}
    text, state = inbox_hook.run(start, "U", {}, 1000.0)
    assert "inbox/n1" in text and "hello" in text
    prompt = {"session_id": "s", "hook_event_name": "UserPromptSubmit"}
    assert inbox_hook.run(prompt, "U", state, 1001.0)[0] is None          # throttled
    assert inbox_hook.run(prompt, "U", state, 2000.0)[0] is None          # already passed this session
    assert "inbox/n1" in inbox_hook.run(start | {"session_id": "t"}, "U", state, 2001.0)[0]   # new session


def test_off_without_store(monkeypatch, capsys):
    monkeypatch.delenv(inbox_hook.STORE_ENV, raising=False)
    inbox_hook.main()
    assert capsys.readouterr().out == ""
