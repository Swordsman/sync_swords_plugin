#!/usr/bin/env python3
"""The compaction check done by message agents: every message judges whether the summary lost its important content.
Compares against compaction_check's Jev flags and DeepSeek replies already in OUT.

usage: agent_check.py LOG SUMMARY --out DIR [--workers 16] [--thinking auto|off] [--limit N]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import re
import sys

import compaction_check as cc
import msgagents

PAYLOAD = """## SUMMARY

The compaction summary below was produced from the conversation your message belongs to. After compaction, the agent continuing the work sees this summary in place of the conversation, so anything important the summary leaves out is lost to it.

{summary}"""
QUESTION = """Does your message contain important information that the summary is missing?

Important means information the agent continuing this work would need to do it correctly: a decision/instruction/preference/correction/constraint/etc, a measured result, an exact identifier (path/version/hash/URL/name/etc), an open commitment/todo, the reason behind a decision, or anything along those lines.
Not important: acknowledgements/small-talk/progress-narration/etc, reasoning that was later superseded, details whose location the summary already points to, or similar.

Reply in exactly this format, two lines:
SCORE: 0, 1, 2, 3 or UNKNOWN
LOST: the missing important information, stated in full so it can be used without your message; or NONE

0: your message contains nothing important, or everything important in it is in the summary
1: the summary loses something from your message, but nothing important
2: the summary loses an important specific detail (a number/path/name/measured-result/exact-wording/etc)
3: the summary loses an important decision/instruction/preference/correction/etc.

Read the question again: Does your message contain important information that the summary is missing?"""
SCORE = re.compile(r"^\s*\**SCORE\s*:?\**\s*:?\s*(\d|UNKNOWN)", re.M | re.I)
LOST = re.compile(r"^\s*\**LOST\s*:?\**\s*:?\s*(.*)", re.M | re.I | re.S)
BEFORE_CHARS = 600  # per preceding message, for reference resolution


def parse(reply: str) -> tuple[int | None, str]:
    """(score or None for UNKNOWN/unparsed, lost text or '')."""
    score, lost = SCORE.search(reply), LOST.search(reply)
    value = int(score.group(1)) if score and score.group(1).isdigit() else None
    text = lost.group(1).strip() if lost else ""
    return value, "" if text.upper().startswith("NONE") else text


def control_tags(messages: list[cc.Message], summary: str) -> set[str]:
    return {message.tag for message, _ in cc.controls(summary, messages[0].tag[0])}


def spawn_all(messages: list[cc.Message], summary: str) -> dict[str, str]:
    planted = [message for message, _ in cc.controls(summary, messages[0].tag[0])]
    with contextlib.closing(msgagents.open_db()) as db, db:
        under = msgagents.context(db, PAYLOAD.format(summary=summary))
        agents, previous = {}, None
        for index, message in enumerate(messages):
            before = [m.text[:BEFORE_CHARS] for m in messages[max(0, index - 2):index]]
            previous = agents[message.tag] = msgagents.spawn(db, under, message.tag, message.speaker, message.text,
                                                             before, parent_agent=previous)
        for message in planted:
            agents[message.tag] = msgagents.spawn(db, under, message.tag, message.speaker, message.text)
    return agents


def report(out: pathlib.Path, answers: dict[str, tuple[int | None, str]], usd: float, controls: set[str]) -> str:
    flagged = {tag for tag, (score, _) in answers.items() if score is not None and score >= 2 and tag not in controls}
    jev = set(cc.flags(json.loads((out / "jev.json").read_text())["scores"]))
    lines = [f"# Agent check: {len(answers)} agents, ${usd:.4f}", "",
             f"- agents flag (score 2-3): {len(flagged)}; unparsed/UNKNOWN: "
             f"{sum(score is None for score, _ in answers.values())}",
             f"- controls: " + ", ".join(f"{tag}={answers[tag][0]}" for tag in sorted(controls & answers.keys())),
             f"- vs Jev ({len(jev)}): both {len(flagged & jev)}, agents only {len(flagged - jev)}, "
             f"Jev only {len(jev - flagged)}"]
    for mode in ("off", "on"):
        reply = out / f"deepseek.{mode}.md"
        if reply.exists():
            found = cc.sections(reply.read_text())
            lost = cc.tags_in(found["DROPPED"]) | cc.tags_in(found["WRONG"])
            lines.append(f"- vs DeepSeek thinking {mode} ({len(lost)}): both {len(flagged & lost)}, "
                         f"agents only {len(flagged - lost)}, DeepSeek only {len(lost - flagged)}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=pathlib.Path)
    parser.add_argument("summary", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--thinking", default="auto")
    parser.add_argument("--limit", type=int, help="ask only the first N agents (plus the controls): a cheap trial")
    args = parser.parse_args()
    messages, summary = cc.load(args.log, args.summary)
    judged = [message for message in messages if not cc.is_tool_only(message)]
    agents = spawn_all(judged, summary)
    if args.limit:
        keep = [m.tag for m in judged[:args.limit]]
        agents = {tag: agent for tag, agent in agents.items() if tag in keep or tag in control_tags(judged, summary)}
    answers_dir = args.out / f"agents.{args.thinking}"
    try:
        records = msgagents.broadcast(agents, QUESTION, answers_dir, args.workers, thinking=args.thinking)
    except msgagents.BroadcastError as error:
        print(error, file=sys.stderr)
        records = error.results
    answers = {tag: parse(record["response"]) for tag, record in records.items()}
    usd = sum(record["usd"] for record in records.values())
    (args.out / f"agents.{args.thinking}.json").write_text(json.dumps(
        {tag: {"score": score, "lost": lost} for tag, (score, lost) in sorted(answers.items())}, indent=1))
    text = report(args.out, answers, usd, control_tags(judged, summary))
    (args.out / f"agents.{args.thinking}.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
