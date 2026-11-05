#!/usr/bin/env python3
"""What did a compaction drop? One command: Jev scores + DeepSeek Flash (thinking on), then message agents, then the
Jev-checked dedup into OUT/dropped.md (verbatim items, each with its source message ids).

usage: compaction_drop.py LOG|littlewing:SESSION[:gN] SUMMARY --out DIR
  SUMMARY: the post-compaction session JSONL (its compaction summary row is used), or a text file of the summary
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def step(*args: str) -> None:
    print("+", " ".join(args), file=sys.stderr)
    subprocess.run([sys.executable, *args], check=True, cwd=HERE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log")
    parser.add_argument("summary", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    log = args.log
    if log.startswith("littlewing:"):   # rebuild once, so every step reads the same bytes
        sys.path.insert(0, str(HERE))
        import compaction_check
        log = str(compaction_check.littlewing_snapshot(log, args.out))
    summary, out = str(args.summary.resolve()), str(args.out.resolve())
    step("compaction_check.py", log, summary, "--out", out, "--modes", "on")
    step("agent_check.py", log, summary, "--out", out)
    step("merge_dropped.py", out)
    print(args.out / "dropped.md")


if __name__ == "__main__":
    main()
