#!/usr/bin/env python3
"""Turn maps and winnow logs for each segment. The spec comes first in every prompt so it caches across calls.

usage: pipeline.py STAGE [SEGMENT ...]   STAGE: turns | winnow | validate
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import dsx

ROOT = pathlib.Path(os.environ.get("SESSION_MAP_DIR", pathlib.Path.cwd()))
PLUGIN = pathlib.Path("/root/.claude/plugins/synced/4e1f6e64-6756-4984-94fd-86ae34254e88_af4d93d3-15ad-42a7-8c08-8f7e02e6f367/sync-swords-plugin")
SPEC = (PLUGIN / "skills/winnow/references/winnow-spec-v0.2.md").read_text()
FOLD = PLUGIN / "scripts/winnow/fold.py"
SEGMENTS = ("s1", "s2", "s3", "gemini")
OUT = ROOT / "out"

# Joe's request in the Gemini log, 10:12 PM, verbatim.
VERBATIM_TURNS = ("okay, first though, could you list out all the turns in this conversation, and give me a 2 sentence "
                  "summary for each? 1 sentence for each user turn, and one sentence for each assistant turn")
WINNOW_TASK = ("Using the winnow v0.2 specification at the top of this message, write the complete winnow log (.wno) for "
               "the conversation above. Follow the spec exactly: a meta header, then deltas keyed to the turn numbers in "
               "the turn list, using only the spec's frames, edges, annotations, statuses and normalization rules, with "
               ":src and :by on every node. Capture every decision, correction, requirement, idea, rejected idea, open "
               "thread and mistake. Output only the .wno log, nothing before or after it.")


def head(segment: str) -> str:
    """Shared prefix for every call on a segment: spec first (shared across segments), then the conversation."""
    conversation = (ROOT / "seg" / f"{segment}.txt").read_text()
    return ("<winnow-spec>\n" + SPEC + "\n</winnow-spec>\n\n(The spec above is for a later step. "
            "Use it only when a request asks for a winnow log.)\n\n<conversation>\n" + conversation + "\n</conversation>\n\n")


def turns(segment: str) -> None:
    for model in ("flash", "pro"):
        dsx.call(head(segment) + VERBATIM_TURNS, OUT / f"{segment}.turns.{model}.md", model=model)


def turn_list_for(segment: str) -> str:
    """The winnow and fix prompts must share this text exactly, or the fix call loses its cached prefix."""
    turns_file = OUT / f"{segment}.turns.pro.md"
    return ("Turn list for this conversation:\n" + turns_file.read_text() + "\n\n") if turns_file.exists() else ""


def winnow(segment: str) -> None:
    prompt = head(segment) + turn_list_for(segment) + WINNOW_TASK
    dsx.call(prompt, OUT / f"{segment}.wno", model="pro", thinking="max")


FRAMES = ("claim", "def", "question", "decision", "constraint", "action", "artifact", "edge")
TOP_LEVEL = ("delta", "meta")


def repair(text: str) -> tuple[str, dict[str, int]]:
    """Structural repair, one pass over the s-expression stream. Deltas and meta are top-level, so anything still
    open is closed before one starts; a stray ')' at top level is dropped; a frame directly inside a delta gets
    its missing (add ...). Strings and ; comments pass through untouched."""
    out, stack, report = [], [], {"closed": 0, "dropped": 0, "wrapped": 0}
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char == '"':
            end = index + 1
            while end < length and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[index:end + 1]); index = end + 1; continue
        if char == ";":
            end = text.find("\n", index); end = length if end < 0 else end
            out.append(text[index:end]); index = end; continue
        if char == "(":
            match = re.match(r"\(\s*([^\s()]+)", text[index:])
            head = match.group(1) if match else ""
            if head in TOP_LEVEL and stack:
                closers = sum(2 if wrapped else 1 for _, wrapped in stack)
                out.append(")" * closers); report["closed"] += 1; stack.clear()
            wrap = head in FRAMES and bool(stack) and stack[-1][0] == "delta"
            if wrap:
                out.append("(add "); report["wrapped"] += 1
            stack.append((head, wrap)); out.append(char); index += 1; continue
        if char == ")":
            if not stack:
                report["dropped"] += 1; index += 1; continue
            _, wrapped = stack.pop()
            out.append(")" + (")" if wrapped else "")); index += 1; continue
        out.append(char); index += 1
    if stack:
        out.append(")" * sum(2 if wrapped else 1 for _, wrapped in stack)); report["closed"] += 1
    return "".join(out), report


FIX_TASK = ("fold.py, the reference validator, reported the problems below for the log you wrote above. Output the "
            "corrected complete log, fixing every problem within the spec's closed sets. Output only the log.")


def fix(segment: str) -> None:
    """Send semantic validation problems back to the model; the original prompt is the cached prefix."""
    path = OUT / f"{segment}.wno"
    problems = subprocess.run([sys.executable, str(FOLD), str(path)], capture_output=True, text=True).stdout
    if "validation     : OK" in problems:
        return
    prompt = (head(segment) + turn_list_for(segment) + WINNOW_TASK
              + "\n\n<your-log>\n" + path.read_text() + "\n</your-log>\n\n" + problems[problems.find("validation"):]
              + "\n\n" + FIX_TASK)
    path.with_suffix(".wno.raw").unlink(missing_ok=True)
    dsx.call(prompt, path, model="pro", thinking="max")
    validate(segment)


def validate(segment: str) -> None:
    path = OUT / f"{segment}.wno"
    raw = path.with_suffix(".wno.raw")
    if not raw.exists():
        raw.write_text(path.read_text())
    fixed, report = repair(raw.read_text())
    path.write_text(fixed)
    print(f"== {segment}: repairs {report}")
    result = subprocess.run([sys.executable, str(FOLD), str(path)], capture_output=True, text=True)
    print((result.stdout + result.stderr)[-1500:])


def main() -> None:
    stage, *chosen = sys.argv[1:]
    OUT.mkdir(exist_ok=True)
    for segment in chosen or SEGMENTS:
        {"turns": turns, "winnow": winnow, "validate": validate, "fix": fix}[stage](segment)


if __name__ == "__main__":
    main()
