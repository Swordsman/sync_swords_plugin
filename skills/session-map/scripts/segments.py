#!/usr/bin/env python3
"""Build seg/s1..s3 and seg/whole from the pasted transcript (segments 1-2) and the live session JSONL (segment 3)."""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
TRANSCRIPTS = pathlib.Path("/home/claude/transcripts")
LIVE = pathlib.Path("/root/.claude/projects/-home-claude/32131678-4e5c-59de-b291-ee9da0c968cc.jsonl")
LOST_SUMMARY_NOTE = (
    "[Context: this segment began right after a context compaction. The compaction summary handed to the assistant at "
    "that point is lost. The earlier segment covered: getting TypeSafe Jev and Playwright working (scout), a general Jev "
    "tool (jevask), building the question library, and turning everything into skills with status markers.]\n\n")


def live_segment() -> str:
    summary, turns = "", []
    for record in map(json.loads, filter(str.strip, LIVE.read_text().splitlines())):
        content = (record.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        text = "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S).strip()
        if record.get("isCompactSummary"):
            summary = text
        elif record.get("type") in ("user", "assistant") and text and not text.startswith("<task-notification>"):
            speaker = record["type"]
            if turns and turns[-1][0] == speaker:
                turns[-1][1] += "\n\n" + text
            else:
                turns.append([speaker, text])
    body = "".join(f"[t{n} {speaker}]\n{text}\n\n" for n, (speaker, text) in enumerate(turns, 1))
    return ("[Context: the compaction summary handed to the assistant at the start of this segment]\n" + summary
            + "\n\n[Transcript of the segment]\n" + body)


def main() -> None:
    paste = (TRANSCRIPTS / "paste2.20261101.txt").read_text().splitlines(keepends=True)
    assert paste[1003].startswith("another thing I noticed: if you look at the questions"), "segment 2 anchor moved"
    assert paste[2495].strip() == "why does it crash?", "segment 3 anchor moved"
    segments = {"s1": "".join(paste[:1003]), "s2": LOST_SUMMARY_NOTE + "".join(paste[1003:2496]), "s3": live_segment()}
    (ROOT / "seg").mkdir(exist_ok=True)
    for name, text in segments.items():
        (ROOT / "seg" / f"{name}.txt").write_text(text)
    whole = "".join(f"<segment {n} of 3>\n{segments[f's{n}']}\n</segment {n} of 3>\n\n" for n in (1, 2, 3))
    (ROOT / "seg" / "whole.txt").write_text(whole)
    print({name: len(text) for name, text in {**segments, "whole": whole}.items()})


if __name__ == "__main__":
    main()
