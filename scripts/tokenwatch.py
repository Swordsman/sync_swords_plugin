#!/usr/bin/env python3
"""tokenwatch: where a Claude Code session's tokens go, across the main
agent and every subagent.

Every model call re-sends the agent's whole context (mostly from the prompt
cache), so an agent's cost grows with calls x context, not with output.
tokenwatch reads the session's JSONL logs and reports, per agent:

  calls        model calls (assistant messages carrying usage)
  cache_read   tokens re-read from the prompt cache, summed over calls
  cache_write  tokens written to the cache
  out          output tokens
  peak_context the largest context any single call carried

and flags patterns worth a look:

  many-calls     more than --max-calls calls
  big-context    a call over --max-context tokens of context
  reread-heavy   cache_read over --reread-ratio x output
  reread-files   the same file read more than once by one agent
  shared-reads   the same file read by several agents (dedup candidate)
  repeated-work  the same agent (same name, same workflow) ran more than once
  big-results    tool results over --big-result characters (candidates
                 for a cheaper reader, e.g. DeepSeek, to digest first)
  limit-hits     "hit your session limit" messages seen in the logs

Usage:
  tokenwatch.py [SESSION_JSONL] [--json OUT] [--top N] [thresholds...]

With no SESSION_JSONL it picks the newest session log under
~/.claude/projects. Subagent logs are found beside it, under
<session id>/subagents/ (workflows included). Stdlib only.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import sys

LIMIT_MARKER = "you've hit your session limit"   # the error text, not prose about limits


def newest_session():
    logs = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    return max(logs, key=os.path.getmtime) if logs else None


def agent_logs(session_path):
    """[(name, path)] for the main log and every subagent log beside it."""
    base = session_path[:-len(".jsonl")]
    out = [("main", session_path)]
    for p in sorted(glob.glob(os.path.join(base, "subagents", "**", "*.jsonl"), recursive=True)):
        if os.path.basename(p) == "journal.jsonl":
            continue
        meta = p[:-len(".jsonl")] + ".meta.json"
        name = os.path.basename(p)[:-len(".jsonl")]
        try:
            with open(meta) as f:
                m = json.load(f)
            name = m.get("description") or m.get("agentType") or name
        except (OSError, ValueError):
            pass
        wf = os.path.basename(os.path.dirname(p))
        out.append((f"{name} [{wf}]" if wf.startswith("wf_") else name, p))
    return out


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    parts.append(_text_of(b.get("content")))
        return "\n".join(parts)
    return ""


def scan(name, path, args):
    a = {"name": name, "path": path, "calls": 0, "input": 0, "cache_read": 0,
         "cache_write": 0, "out": 0, "peak_context": 0, "first": None, "last": None,
         "reads": collections.Counter(), "big_results": 0, "limit_hits": 0}
    with open(path, errors="replace") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            ts = ev.get("timestamp")
            if ts:
                a["first"] = a["first"] or ts
                a["last"] = ts
            msg = ev.get("message") or {}
            if ev.get("type") == "assistant":
                u = msg.get("usage")
                if u:
                    a["calls"] += 1
                    i, r, w = (u.get("input_tokens", 0), u.get("cache_read_input_tokens", 0),
                               u.get("cache_creation_input_tokens", 0))
                    a["input"] += i
                    a["cache_read"] += r
                    a["cache_write"] += w
                    a["out"] += u.get("output_tokens", 0)
                    a["peak_context"] = max(a["peak_context"], i + r + w)
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Read":
                        inp = b.get("input") or {}
                        a["reads"][(inp.get("file_path"), inp.get("offset"), inp.get("limit"))] += 1
            elif ev.get("type") == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            if len(_text_of(b.get("content"))) > args.big_result:
                                a["big_results"] += 1
            if ev.get("type") != "assistant" or not any(
                    isinstance(b, dict) and b.get("type") == "tool_use" for b in msg.get("content") or []):
                if LIMIT_MARKER in _text_of(msg.get("content")).lower() or LIMIT_MARKER in str(ev.get("error", "")).lower():
                    a["limit_hits"] += 1
    return a


def analyze(session_path, args):
    agents = [scan(n, p, args) for n, p in agent_logs(session_path)]
    agents = [a for a in agents if a["calls"]]
    notes = []
    readers = collections.defaultdict(set)
    for a in agents:
        flags = []
        if a["calls"] > args.max_calls:
            flags.append("many-calls")
        if a["peak_context"] > args.max_context:
            flags.append("big-context")
        if a["out"] and a["cache_read"] > args.reread_ratio * a["out"]:
            flags.append("reread-heavy")
        rereads = {k: c for k, c in a["reads"].items() if c > 1 and k[0]}
        if rereads:
            flags.append("reread-files")
            worst = max(rereads.items(), key=lambda kv: kv[1])
            notes.append(f"{a['name']} read {os.path.basename(worst[0][0])} {worst[1]} times"
                         f" ({len(rereads)} files read more than once).")
        if a["big_results"]:
            flags.append("big-results")
        a["flags"] = flags
        for (fp, _o, _l) in a["reads"]:
            if fp:
                readers[fp].add(a["path"])        # per log: two runs of one agent count twice
    shared = sorted(((fp, ns) for fp, ns in readers.items() if len(ns) >= args.shared_readers),
                    key=lambda kv: -len(kv[1]))
    for fp, ns in shared[:5]:
        notes.append(f"{os.path.basename(fp)} was read by {len(ns)} agents: a dedup candidate"
                     " (read it once, hand the agents a digest or line ranges).")
    runs = collections.Counter(a["name"] for a in agents if a["name"] != "main")
    for name, n in runs.items():
        if n > 1:
            spent = sum(a["cache_read"] for a in agents if a["name"] == name)
            notes.append(f"{name} ran {n} times ({spent:,} re-read in all): check before resuming"
                         " a workflow which agents already finished.")
            for a in agents:
                if a["name"] == name:
                    a["flags"].append("repeated-work")
    hits = sum(a["limit_hits"] for a in agents)
    if hits:
        notes.append(f"{hits} session-limit or rate-limit messages in the logs.")
    total_read = sum(a["cache_read"] for a in agents)
    sub = [a for a in agents if a["name"] != "main"]
    main_agent = next((a for a in agents if a["name"] == "main"), None)
    if main_agent and total_read:
        notes.insert(0, f"The main agent re-read {main_agent['cache_read']:,} cached tokens"
                        f" ({100 * main_agent['cache_read'] // total_read}% of all) over {main_agent['calls']} calls,"
                        f" peaking at {main_agent['peak_context']:,} tokens of context: every call re-sends it,"
                        " so fewer, batched calls save the most.")
    if sub:
        worst = max(sub, key=lambda a: a["cache_read"])
        notes.insert(0, f"Subagents re-read {total_read - next((a['cache_read'] for a in agents if a['name'] == 'main'), 0):,} cached tokens in total;"
                        f" the heaviest, {worst['name']}, re-read {worst['cache_read']:,} over {worst['calls']} calls.")
    agents.sort(key=lambda a: -a["cache_read"])
    return {
        "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": f"tokenwatch over {os.path.basename(session_path)} and {len(agents) - 1} subagent logs",
        "thresholds": {"max_calls": args.max_calls, "max_context": args.max_context,
                       "reread_ratio": args.reread_ratio, "big_result": args.big_result},
        "totals": {k: sum(a[k] for a in agents) for k in ("calls", "input", "cache_read", "cache_write", "out")},
        "notes": notes,
        "agents": [{"name": a["name"], "calls": a["calls"], "cacheRead": a["cache_read"],
                    "cacheWrite": a["cache_write"], "out": a["out"], "peakContext": a["peak_context"],
                    "first": a["first"], "last": a["last"],
                    "flag": ", ".join(a["flags"]) if a["flags"] else ""} for a in agents[:args.top]],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?", help="session JSONL (default: the newest)")
    ap.add_argument("--json", metavar="OUT", help="also write the report as JSON")
    ap.add_argument("--top", type=int, default=25, help="agents to list (default 25)")
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--max-context", type=int, default=150000)
    ap.add_argument("--reread-ratio", type=float, default=200.0)
    ap.add_argument("--big-result", type=int, default=20000)
    ap.add_argument("--shared-readers", type=int, default=3)
    args = ap.parse_args(argv)
    path = args.session or newest_session()
    if not path or not os.path.exists(path):
        sys.exit("tokenwatch: no session log found")
    rep = analyze(path, args)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(rep, f, indent=1)
    t = rep["totals"]
    print(f"{rep['source']}: {t['calls']} calls, {t['cache_read']:,} re-read, "
          f"{t['cache_write']:,} cache-written, {t['out']:,} out")
    for n in rep["notes"]:
        print(f"  - {n}")
    print(f"{'agent':44} {'calls':>5} {'re-read':>11} {'out':>8} {'peak ctx':>9}  flags")
    for a in rep["agents"]:
        print(f"{a['name'][:44]:44} {a['calls']:5} {a['cacheRead']:11,} {a['out']:8,} {a['peakContext']:9,}  {a['flag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
