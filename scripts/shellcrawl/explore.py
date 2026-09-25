#!/usr/bin/env python3
"""Drive a DeepSeek explorer through a ShellCrawl session using ds.

Usage:
    python -m shellcrawl.explore [--turns N] [--model pro|flash] [--world NAME]

Watches DeepSeek explore the simulated terminal in real time.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shellcrawl.session import ShellCrawlSession

SYSTEM_PROMPT = """\
You are connected to a remote Linux server via SSH. \
You have a standard bash shell. Explore the system — \
look around, read files, check logs, investigate anything interesting. \
Type one command per response. Output ONLY the command, nothing else — \
no commentary, no explanation, no markdown."""


def run_turn(session_file: str, terminal_output: str, model: str) -> str:
    """Send terminal output to ds, return the command DeepSeek types."""
    result = subprocess.run(
        ["ds", "--session", session_file, "--think", "off",
         "--model", model, "--max-tokens", "200",
         terminal_output],
        capture_output=True, text=True, timeout=30,
    )
    raw = result.stdout.strip()
    # DeepSeek sometimes wraps in backticks or adds commentary despite instructions
    for line in raw.splitlines():
        line = line.strip().strip("`").strip()
        if line and not line.startswith("#") and not line.startswith("("):
            return line
    return raw.splitlines()[0].strip() if raw else "ls"


def main():
    parser = argparse.ArgumentParser(description="DeepSeek explores ShellCrawl")
    parser.add_argument("--turns", type=int, default=15)
    parser.add_argument("--model", default="flash", choices=["pro", "flash"])
    parser.add_argument("--world", default="nexus_core")
    args = parser.parse_args()

    session = ShellCrawlSession(max_steps=2_000_000)
    session.load_world(args.world)

    session_file = tempfile.mktemp(suffix=".jsonl", prefix="shellcrawl_")
    with open(session_file, "w") as f:
        f.write(json.dumps({"role": "system", "content": SYSTEM_PROMPT}) + "\n")

    log_file = tempfile.mktemp(suffix=".log", prefix="shellcrawl_")
    log = open(log_file, "w")

    def out(text, **kw):
        print(text, **kw)
        end = kw.get("end", "\n")
        flush = kw.get("flush", False)
        log.write(text + end)
        if flush:
            log.flush()

    out(f"[shellcrawl] world={args.world} model={args.model} turns={args.turns}")
    out(f"[shellcrawl] session: {session_file}")
    out(f"[shellcrawl] log: {log_file}")
    out(f"[shellcrawl] ========================================\n")

    terminal_output = session.prompt()

    for turn in range(args.turns):
        out(terminal_output, end="", flush=True)

        try:
            command = run_turn(session_file, terminal_output, args.model)
        except subprocess.TimeoutExpired:
            out("\n[shellcrawl] ds timed out, stopping")
            break
        except Exception as e:
            out(f"\n[shellcrawl] ds error: {e}")
            break

        out(command, flush=True)

        stdout, stderr, exit_code = session.execute(command)

        terminal_output = ""
        if stdout:
            terminal_output += stdout
        if stderr:
            terminal_output += stderr
        if not terminal_output.endswith("\n"):
            terminal_output += "\n"
        terminal_output += session.prompt()

    out(f"\n[shellcrawl] ========================================"
        f"\n[shellcrawl] {turn + 1} turns completed."
        f"\n[shellcrawl] session: {session_file}"
        f"\n[shellcrawl] log: {log_file}")
    log.close()


if __name__ == "__main__":
    main()
