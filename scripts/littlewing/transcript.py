"""Session JSONL -> numbered conversation turns, as winnow reads them.

winnow expects each turn to open with a `[tN speaker]` header line. Claude
Code logs one event per content block, so consecutive events from the same
speaker merge into one turn. Only text blocks survive; everything else in
the log (ids, timestamps, cwd, thinking, tool calls and results) is
dropped. Dropped whole: injected skill and command text (`isMeta`),
subagent traffic (`isSidechain`), compaction summaries, and user-role
messages the person didn't write (`origin.kind` other than `human`, such
as background-task notifications), which would otherwise read as the
user talking.

Turn numbers count from the start of the session, so they stay stable as
the log grows and incremental winnow runs keep consistent `:src tN` ids.
"""

from __future__ import annotations

import json
import re


def _text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def events_from_lines(lines) -> list[dict]:
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        role = ev.get("type")
        if role not in ("user", "assistant"):
            continue
        if ev.get("isMeta") or ev.get("isSidechain") or ev.get("isCompactSummary"):
            continue
        origin = ev.get("origin")
        if isinstance(origin, dict) and origin.get("kind", "human") != "human":
            continue
        text = _text(ev.get("message") or {}).strip()
        if text:
            events.append({"role": role, "text": text,
                           "timestamp": ev.get("timestamp", "")})
    return events


def events_from_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return events_from_lines(f)


def number_turns(events: list[dict]) -> list[tuple[int, str, str]]:
    """Merge same-speaker runs; returns [(n, speaker, text)], n from 1."""
    turns: list[list] = []
    for ev in events:
        if turns and turns[-1][1] == ev["role"]:
            turns[-1][2] += "\n\n" + ev["text"]
        else:
            turns.append([len(turns) + 1, ev["role"], ev["text"]])
    return [tuple(t) for t in turns]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def closed_turns(turns, last_assistant_message: str | None = None, final: bool = False):
    """The prefix of `turns` that can't change any more, ending on a reply.

    A turn is closed once the other speaker has answered it. The last turn
    is closed too when the session is over (`final`), or when it is an
    assistant turn that ends with the Stop hook's `last_assistant_message`
    (the log can lag the reply, so that check proves it's all on disk).
    The result always ends with an assistant turn, so winnow never sees a
    question without its answer.
    """
    if not turns:
        return []
    k = len(turns)
    if not final:
        last = turns[-1]
        tail = _norm(last_assistant_message)
        done = last[1] == "assistant" and tail and _norm(last[2]).endswith(tail)
        if not done:
            k -= 1
    while k > 0 and turns[k - 1][1] != "assistant":
        k -= 1
    return list(turns[:k])


def render_winnow(turns) -> str:
    return "\n\n".join(f"[t{n} {who}]\n{text}" for n, who, text in turns) + "\n"
