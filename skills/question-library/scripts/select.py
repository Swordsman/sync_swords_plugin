#!/usr/bin/env python3
"""Pick the library questions that apply to a context: one Jev call, one Noul per entry. The core of the selection hook.

usage: select.py [CONTEXT_FILE | -] [--top N] [--threshold P] [--skip-asked] [--record]
  CONTEXT_FILE  text of the current context (latest messages, draft reply, recent tool results); '-' or omitted reads stdin
  --skip-asked  leave out entries already in the history log ($QUESTION_LIBRARY_OUT/asked.jsonl)
  --record      append the selected entries to the history log
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from paths import DATA, output, use_jev

APPLIES = ("Would asking `library.{id}` right now be likely to change what happens next in `context`, "
           "by surfacing something not yet considered, checked, or asked?")
DOUBT = (0.4, 0.6)


def load_library() -> dict[str, str]:
    entries = json.loads((DATA / "questions.json").read_text())
    entries = entries["entries"] if isinstance(entries, dict) else entries
    return {entry["id"]: entry["question"] for entry in entries}


def asked_before() -> set[str]:
    log = output("asked.jsonl")
    return {json.loads(line)["id"] for line in log.read_text().splitlines() if line.strip()} if log.exists() else set()


def select(context: str, library: dict[str, str]) -> list[dict]:
    use_jev()
    import scout
    questions = {entry_id: scout.noul(APPLIES.format(id=entry_id)) for entry_id in library}
    answers = scout.ask_jev({"context": context, "library": library}, questions)["answers"]
    ranked = [{"id": entry_id, "question": library[entry_id], "applies": round(answers[entry_id]["noul"], 2)}
              for entry_id in library]
    for item in ranked:
        item["doubtful"] = DOUBT[0] <= item["applies"] <= DOUBT[1]
    ranked.sort(key=lambda item: -item["applies"])
    print(json.dumps(scout.meter_summary()), file=sys.stderr)
    return ranked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("context", nargs="?", default="-")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--skip-asked", action="store_true")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    context = sys.stdin.read() if args.context == "-" else open(args.context).read()
    if not context.strip():
        raise SystemExit("empty context: nothing to judge against")
    library = load_library()
    if args.skip_asked:
        library = {entry_id: text for entry_id, text in library.items() if entry_id not in asked_before()}
    chosen = [item for item in select(context, library) if item["applies"] >= args.threshold][:args.top]
    if args.record and chosen:
        with output("asked.jsonl").open("a") as log:
            for item in chosen:
                log.write(json.dumps({"id": item["id"], "applies": item["applies"], "at": time.time()}) + "\n")
    print(json.dumps(chosen, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
