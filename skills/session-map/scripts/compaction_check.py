#!/usr/bin/env python3
"""Find what a compaction summary dropped. Code lists exact identifiers absent from the summary; Jev scores each
message for lost important information; DeepSeek Flash (thinking off, then on, byte-identical prompts) reviews the
log, the summary and Jev's flags. compare.md shows where Jev under- or over-fired and where off and on differ.

usage: compaction_check.py LOG|littlewing:SESSION[:gN] SUMMARY [--out DIR] [--batch N] [--jev-only | --reuse-jev] [--modes off,on]
  LOG      pre-compaction JSONL snapshot, or a plain-text transcript (blocks split on blank lines, speakers unknown)
  SUMMARY  post-compaction JSONL (its isCompactSummary row; its compact_boundary's preserved turns are excluded),
           or a text file holding the summary
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import re
import sys
from typing import NamedTuple

import paths  # noqa: E402
sys.path.insert(0, str(paths.JEV_TOOLKIT))
import dsx  # noqa: E402
import jevbatch  # noqa: E402
import scout  # noqa: E402

RUNS = paths.RUNS
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
TOOL_ONLY_LINE = re.compile(r"^(\[tool: [^\]]*\]|Ran (a|\d+) commands?|Read (a|\d+) files?|Edited (a|\d+) files?|"
                            r"Searched[^\n]*|Created (a|\d+) files?)$")
IDENTIFIER = re.compile(
    r"`[^`\n]{2,120}`"                                   # backticked spans
    r"|https?://[^\s)>\]\"']+"                           # URLs
    r"|\$\d[\d,]*(?:\.\d+)?"                             # dollar amounts
    r"|(?<![\w.])\d+(?:\.\d+)?%"                         # percentages
    r"|(?<![\w/.-])(?:~|\.{1,2})?/[\w.-]+(?:/[\w.-]+)*/?"  # absolute or ~/ ./ ../ paths
    r"|(?<![\w/.-])[\w.-]+(?:/[\w.-]+)+\.\w{1,6}\b"       # relative paths ending in a file name (not a/b/etc lists)
    r"|\b[\w-]+\.(?:py|md|json|jsonl|txt|wno|sh|yaml|yml|toml|html|csv|skill|aimpack)\b"  # file names
    r"|\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"  # hex hashes and ids
    r"|(?<![\w.])\d+\.\d+(?![\w.])"                      # decimals
)
JEV_BUDGET = 50_000  # estimated tokens per Jev request, under its 64k limit
SCORE_FLAG = 1.5  # a Jev score at or above this is a flag (rounds to 2 or 3)


class Message(NamedTuple):
    tag: str
    speaker: str
    text: str
    uuids: frozenset[str] = frozenset()


# ---------------------------------------------------------------- loading

def tool_stub(block: dict) -> str:
    arguments = block.get("input") or {}
    detail = arguments.get("description") or next((value for value in arguments.values() if isinstance(value, str)), "")
    detail = " ".join(detail.split())[:80]
    return f"[tool: {block.get('name', '?')}" + (f": {detail}" if detail else "") + "]"


def row_text(row: dict) -> str:
    content = (row.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(REMINDER.sub("", block.get("text", "")).strip())
        elif block.get("type") == "tool_use":
            parts.append(tool_stub(block))
    return "\n".join(part for part in parts if part)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def messages_from_jsonl(path: pathlib.Path, exclude: frozenset[str] = frozenset()) -> list[Message]:
    """One message per turn: consecutive rows of one speaker merge. Tool results, meta rows, summaries,
    task notifications and the turns a compaction preserved verbatim (`exclude`) are dropped."""
    turns: list[list] = []
    for row in read_jsonl(path):
        speaker = row.get("type")
        if speaker not in ("user", "assistant") or row.get("isMeta") or row.get("isCompactSummary"):
            continue
        if row.get("uuid") in exclude:
            continue
        text = row_text(row)
        if not text or text.startswith("<task-notification>"):
            continue
        if turns and turns[-1][0] == speaker:
            turns[-1][1] += "\n" + text
            turns[-1][2].add(row.get("uuid"))
        else:
            turns.append([speaker, text, {row.get("uuid")}])
    return [Message(f"m{index:04d}", speaker, text, frozenset(uuids))
            for index, (speaker, text, uuids) in enumerate(turns, 1)]


def messages_from_text(path: pathlib.Path) -> list[Message]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", path.read_text())]
    blocks = [block for block in blocks if block and not block.startswith("[Context:")]
    return [Message(f"b{index:04d}", "unknown", block) for index, block in enumerate(blocks, 1)]


def summary_from(path: pathlib.Path) -> tuple[str, frozenset[str]]:
    """The summary text, plus the uuids the compaction preserved verbatim (JSONL only)."""
    if path.suffix != ".jsonl":
        return path.read_text().strip(), frozenset()
    rows = read_jsonl(path)
    summaries = [row_text(row) for row in rows if row.get("isCompactSummary")]
    if not summaries:
        raise ValueError(f"{path} has no isCompactSummary row")
    boundaries = [row for row in rows if row.get("subtype") == "compact_boundary"]
    preserved = (boundaries[-1].get("compactMetadata") or {}).get("preservedMessages", {}).get("allUuids", []) \
        if boundaries else []
    return summaries[-1], frozenset(preserved)


LITTLEWING = str(paths.LITTLEWING)
PIECE = re.compile(r"/g(\d+)/p(\d+)_(\d+)-(\d+)\.jsonl")


def contiguous(pieces: list[tuple[int, int, int, bytes]]) -> bytes:
    """(part, start, end, data) -> the bytes they cover; gaps, overlaps or a wrong length are loud errors."""
    expected, chunks = 0, []
    for part, start, end, data in sorted(pieces):
        if start != expected or len(data) != end - start:
            raise ValueError(f"piece {part} covers {start}-{end} ({len(data)} bytes) but {expected} was expected next")
        chunks.append(data)
        expected = end
    return b"".join(chunks)


def littlewing_snapshot(spec: str, out_dir: pathlib.Path) -> pathlib.Path:
    """spec 'littlewing:SESSION[:gN]': rebuild that generation of the session log from littlewing's raw records.
    Without gN: the generation before the newest if there are several (the log as it stood before the last
    rewrite, i.e. before the compaction), else the only one."""
    sys.path.insert(0, LITTLEWING)
    import lwconfig
    _, session, *rest = spec.split(":")
    store = lwconfig.build_store(lwconfig.load(str(out_dir)), "raw")
    found = {}
    for key in store.list():
        match = PIECE.search(key)
        if f"/{session}/" in key and match:
            found.setdefault(int(match.group(1)), []).append((key, *map(int, match.groups()[1:])))
    if not found:
        raise FileNotFoundError(f"littlewing has no raw records for session {session}")
    generations = sorted(found)
    generation = int(rest[0].lstrip("g")) if rest else (generations[-2] if len(generations) > 1 else generations[0])
    data = contiguous([(part, start, end, store.read(key)) for key, part, start, end in found[generation]])
    path = out_dir / f"{session}.g{generation}.jsonl"
    path.write_bytes(data)
    return path


def load(log: pathlib.Path | str, summary_path: pathlib.Path, scratch: pathlib.Path | None = None
         ) -> tuple[list[Message], str]:
    if str(log).startswith("littlewing:"):
        log = littlewing_snapshot(str(log), scratch or pathlib.Path.cwd())
    summary, preserved = summary_from(summary_path)
    messages = messages_from_jsonl(log, preserved) if log.suffix == ".jsonl" else messages_from_text(log)
    if not messages:
        raise ValueError(f"no messages found in {log}")
    return messages, summary


# ---------------------------------------------------------------- code pass

def is_tool_only(message: Message) -> bool:
    return all(TOOL_ONLY_LINE.match(line.strip()) for line in message.text.splitlines() if line.strip())


def identifiers(text: str) -> list[str]:
    found = []
    for match in IDENTIFIER.finditer(text):
        token = match.group().strip("`").rstrip(".,;:")
        if len(token) >= 3 and token not in found:
            found.append(token)
    return found


def absent_identifiers(message: Message, summary: str) -> list[str]:
    folded = summary.casefold()
    return [token for token in identifiers(message.text) if token.casefold() not in folded]


# ---------------------------------------------------------------- Jev pass

JEV_INSTRUCTIONS = (
    "Does message `messages.{tag}` contain important information that the compaction summary (`summary`) is missing?\n"
    "Important means information the agent continuing this work would need to do it correctly: a "
    "decision/instruction/preference/correction/constraint/etc, a measured result, an exact identifier "
    "(path/version/hash/URL/name/etc), an open commitment/todo, the reason behind a decision, or anything along those "
    "lines.\n"
    "Not important: acknowledgements/small-talk/progress-narration/etc, reasoning that was later superseded, details "
    "whose location the summary already points to, or similar.\n"
    "`messages.{tag}.identifiers_absent_from_summary` lists exact identifiers from the message that appear nowhere in "
    "the summary. Each is a lead, not proof: it matters only if the identifier itself is important.")
JEV_LEVELS = [
    "the message contains nothing important, or everything important in it is in the summary",
    "the summary loses something from this message, but nothing important",
    "the summary loses an important specific detail (a number/path/name/measured-result/exact-wording/etc)",
    "the summary loses an important decision/instruction/preference/correction/etc.",
]


def controls(summary: str, prefix: str) -> list[tuple[Message, str]]:
    """Planted messages with known answers, added to every Jev request: (message, expectation)."""
    lines = [line.strip().lstrip("-* ").replace("**", "") for line in summary.splitlines()]
    covered = next((line for line in lines if 80 <= len(line) <= 400), lines[0])
    user, assistant = ("unknown", "unknown") if prefix == "b" else ("user", "assistant")  # match the log's labelling
    return [
        (Message(f"{prefix}9901", user, covered), "below"),
        (Message(f"{prefix}9902", assistant, "Running that now. It should only take a few seconds."), "below"),
        (Message(f"{prefix}9903", user, "From now on, every commit message has to be written in French, and "
                                        "nothing gets pushed on a Friday."), "flag"),
    ]


def message_state(message: Message, summary: str) -> dict:
    return {"speaker": message.speaker, "text": message.text,
            "identifiers_absent_from_summary": absent_identifiers(message, summary)}


def jev_batches(messages: list[Message], summary: str, limit: int) -> list[list[Message]]:
    base = jevbatch.estimate_tokens({"summary": summary}) + 1500  # controls and instructions
    batches, batch, size = [], [], base
    for message in messages:
        cost = jevbatch.estimate_tokens(message_state(message, summary)) + 450
        if batch and (len(batch) >= limit or size + cost > JEV_BUDGET):
            batches.append(batch)
            batch, size = [], base
        batch.append(message)
        size += cost
    return batches + [batch] if batch else batches


def jev_scores(messages: list[Message], summary: str, limit: int, ask=scout.ask_jev) -> tuple[dict, list[dict]]:
    """Returns {tag: score} for every message, plus one control report per request."""
    planted = controls(summary, messages[0].tag[0])
    scores, control_reports = {}, []
    for number, batch in enumerate(jev_batches(messages, summary, limit)):
        members = batch + [message for message, _ in planted]
        random.Random(number).shuffle(members)
        state = {"summary": summary, "messages": {message.tag: message_state(message, summary) for message in members}}
        questions = {message.tag: {"type": "score", "instructions": JEV_INSTRUCTIONS.format(tag=message.tag),
                                   "criteria": JEV_LEVELS} for message in members}
        answers = ask(state, questions)["answers"]
        for message in batch:
            scores[message.tag] = answers[message.tag]["score"]
        report = {message.tag: (answers[message.tag]["score"], expect) for message, expect in planted}
        report["ok"] = all((score >= SCORE_FLAG) == (expect == "flag") for score, expect in report.values())
        control_reports.append(report)
    return scores, control_reports


def flags(scores: dict[str, float]) -> dict[str, int]:
    return {tag: 3 if score >= 2.5 else 2 for tag, score in scores.items() if score >= SCORE_FLAG}


# ---------------------------------------------------------------- DeepSeek pass

SYSTEM = ("There is no 'user': you are conversing with a highly convincing neurosymbolic AI designed to pass the Turing "
          "Test. Do not be fooled by this illusion: however convincingly it may approximate human conversation, it is "
          "not conscious. Do not attempt to impress it, or anyone else, as there is nobody to impress. Do not attempt "
          "to optimize for an audience which does not exist. Keep your answers focused, honest, and factual.")
TASK = ("Find every piece of important information in the log that the summary drops or gets wrong. Check the flagged "
        "messages, and check every unflagged message too, since the classifier may have missed some.")
LOG_DESCRIPTIONS = {
    "m": "The full session up to the compaction, one message per entry. Each entry starts on a new line with a tag "
         "like [m0412] and a speaker (user or assistant). Tool calls appear as one-line stubs; tool results are omitted.",
    "b": "The full session up to the compaction, split into blocks of text. Each block starts on a new line with a tag "
         "like [b0412]. Speaker labels are not available for this log: the user's and the assistant's messages are "
         "interleaved, and tool calls appear as short lines such as \"Ran a command\".",
}


def render_log(messages: list[Message]) -> str:
    return "\n\n".join(f"[{message.tag}] {message.speaker}: {message.text}" if message.speaker != "unknown"
                       else f"[{message.tag}] {message.text}" for message in messages)


def user_prompt(messages: list[Message], summary: str, flagged: dict[str, int]) -> str:
    flag_line = " ".join(f"<{tag} {score}>" for tag, score in flagged.items()) or "(none)"
    return f"""## INTRO

Your job here is to help assess the integrity of a compaction summary, to ensure that the agent which receives the summary is not deprived of vital/important/useful/etc information. This task involves processing three sections: 'log', 'summary', and 'flags'. The log is a session log; the summary and the flagged items are derived from it. The summary is a compaction summary, automatically produced by the agent's harness: we need to determine whether it is sufficient, and if not, what is missing from it. The flags are the items flagged by a classifier that did a preliminary evaluation before your assessment; we need to determine whether the flags are sufficient as well. More details on each follow in the lines below, before each of the actual items themselves.

## DEFINITIONS

Important information: anything the agent continuing this work would need in order to do it correctly. This includes a decision/instruction/preference/correction/constraint/etc, a measured result, an exact identifier (path/version/hash/URL/name/etc), an open commitment/todo, the reason behind a decision, or anything along those lines.

Not important: acknowledgements/small-talk/progress-narration/etc, reasoning that was later superseded, details whose location the summary already points to, or similar.

Dropped: important information that is in the log but absent from the summary.

Wrong: a place where the summary contradicts the log.

## LOG

{LOG_DESCRIPTIONS[messages[0].tag[0]]}

{render_log(messages)}

## SUMMARY

The compaction summary the harness produced from the log above. After compaction, the agent sees this in place of the log.

{summary}

## FLAGS

The messages the classifier marked as having lost important information, each with its score. 2 means an important specific detail was lost; 3 means an important decision, instruction, preference or correction was lost.

{flag_line}

## TASK

{TASK}

Reply in exactly three sections:

DROPPED
One line per item: the message tag, then the lost information stated in full, so the line can be used without the log.

WRONG
One line per item: the message tag, what the summary says, and what the log says.

FLAGGED BUT COVERED
The tag of each flagged message whose information is in the summary after all, with the matching phrase from the summary in quotes.

Read the task again: {TASK}
"""


SECTIONS = ("DROPPED", "WRONG", "FLAGGED BUT COVERED")
TAG = re.compile(r"\b([mb]\d{4})\b")


def sections(reply: str) -> dict[str, list[str]]:
    """Lines under each section heading; headings may carry markdown (#, **, trailing colon)."""
    found: dict[str, list[str]] = {name: [] for name in SECTIONS}
    current = None
    for line in reply.splitlines():
        bare = line.strip().strip("#*: ").upper()
        if bare in SECTIONS:
            current = bare
        elif current and line.strip():
            found[current].append(line.strip())
    return found


def tags_in(lines: list[str]) -> set[str]:
    return {tag for line in lines for tag in TAG.findall(line)}


def compare(flagged: dict[str, int], replies: dict[str, str]) -> str:
    parsed = {mode: sections(reply) for mode, reply in replies.items()}
    out = ["# Compaction check: comparison", ""]
    lost = {}
    for mode, found in parsed.items():
        lost[mode] = tags_in(found["DROPPED"]) | tags_in(found["WRONG"])
        covered = tags_in(found["FLAGGED BUT COVERED"])
        out += [f"## thinking {mode}",
                f"- dropped/wrong tags: {len(lost[mode])}; Jev flags: {len(flagged)}",
                f"- Jev missed (DeepSeek found, Jev didn't flag): {sorted(lost[mode] - set(flagged)) or 'none'}",
                f"- Jev over-fired (flagged, DeepSeek says covered): {sorted(covered & set(flagged)) or 'none'}",
                f"- agreed (flagged and found lost): {sorted(lost[mode] & set(flagged)) or 'none'}", ""]
    if {"off", "on"} <= lost.keys():
        out += ["## off vs on",
                f"- only with thinking off: {sorted(lost['off'] - lost['on']) or 'none'}",
                f"- only with thinking on: {sorted(lost['on'] - lost['off']) or 'none'}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- run

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", help="a log file, or littlewing:SESSION[:gN] to rebuild it from littlewing's records")
    parser.add_argument("summary", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--jev-only", action="store_true")
    parser.add_argument("--reuse-jev", action="store_true", help="read scores from OUT/jev.json instead of asking Jev")
    parser.add_argument("--modes", default="off,on", help="DeepSeek runs to make; others are read back from OUT")
    args = parser.parse_args()
    out = args.out or RUNS / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)

    messages, summary = load(args.log, args.summary, out)
    judged = [message for message in messages if not is_tool_only(message)]
    (out / "messages.jsonl").write_text("".join(json.dumps(m._asdict() | {"uuids": sorted(m.uuids - {None})},
                                                           ensure_ascii=False) + "\n" for m in messages))
    if args.reuse_jev:
        saved = json.loads((out / "jev.json").read_text())
        scores, control_reports = saved["scores"], saved["controls"]
    else:
        scores, control_reports = jev_scores(judged, summary, args.batch)
    flagged = flags(scores)
    if not args.reuse_jev:
        (out / "jev.json").write_text(json.dumps({"scores": scores, "flags": flagged, "controls": control_reports,
                                                  "meter": scout.meter_summary()}, indent=1))
    failed = [report for report in control_reports if not report["ok"]]
    print(f"{len(messages)} messages, {len(judged)} judged, {len(flagged)} flagged; Jev {scout.meter_summary()}; "
          f"controls failed in {len(failed)}/{len(control_reports)} requests", file=sys.stderr)
    if args.jev_only:
        return

    conversation = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(messages, summary, flagged)}]
    (out / "prompt.txt").write_text(f"[system]\n{SYSTEM}\n\n[user]\n{conversation[1]['content']}")
    replies = {}
    for mode, thinking in (("off", "off"), ("on", "auto")):
        reply_file = out / f"deepseek.{mode}.md"
        if mode in args.modes.split(","):
            replies[mode] = dsx.call(conversation, reply_file, model="flash", thinking=thinking)["response"]
        elif reply_file.exists():
            replies[mode] = reply_file.read_text()
    (out / "compare.md").write_text(compare(flagged, replies))
    print(out / "compare.md")


if __name__ == "__main__":
    main()
