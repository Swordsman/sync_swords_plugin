#!/usr/bin/env python3
"""DeepSeek calls with cost accounting, a 24h I/O log, and cache-miss tripwires.

usage: dsx.py call PROMPT_FILE OUT_FILE [--model flash|pro] [--thinking auto|off|high|max]
       dsx.py balance            record a balance snapshot
       dsx.py reconcile          calculated spend since a snapshot vs the balance change
       dsx.py report [--hours H] calls, tokens, cost, cache hit rate
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import socket
import sys
import time
import urllib.request

API = "https://api.deepseek.com"
MODELS = {"flash": "deepseek-flash", "pro": "deepseek-v4-pro"}
# $ per million tokens: (cache hit, cache miss, output), off-peak then peak. Verified against the balance 2026-11-01.
RATES = {"deepseek-flash": ((0.003, 0.15, 0.60), (0.006, 0.30, 1.20)),
         "deepseek-v4-pro": ((0.022, 0.66, 1.98), (0.044, 1.32, 3.96))}
PEAK_HOURS = set(range(1, 4)) | set(range(6, 10))   # UTC, weekdays
HOME = pathlib.Path.home() / ".dsx"
LOG, BALANCES = HOME / "io.jsonl", HOME / "balances.jsonl"
CACHE_WINDOW = dt.timedelta(hours=24)
SHINGLE = 2048            # chars per block when looking for shared content
MIN_SHARED = 8192         # shared chars worth caching
CACHE_BLOCK_TOKENS = 64   # DeepSeek caches in 64-token units
STALL_SECONDS = 300


class MissedCacheError(RuntimeError):
    """Content that could have been a cache hit was not, or will not be."""


def key() -> str:
    return (pathlib.Path.home() / ".deepseek_key").read_text().strip()


def is_peak(when: dt.datetime) -> bool:
    return when.weekday() < 5 and when.hour in PEAK_HOURS


def cost(usage: dict, model: str, when: dt.datetime) -> float:
    hit_rate, miss_rate, out_rate = RATES[model][is_peak(when)]
    return (usage.get("prompt_cache_hit_tokens", 0) * hit_rate + usage.get("prompt_cache_miss_tokens", 0) * miss_rate
            + usage.get("completion_tokens", 0) * out_rate) / 1e6


def recent_calls(model: str, thinking: str, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(same cache partition, other thinking settings). Observed 2026-11-01: a thinking=max call got 0 hits on a
    prefix cached by thinking=auto calls, so model + thinking setting is the cache partition."""
    if not LOG.exists():
        return [], []
    calls = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]
    recent = [c for c in calls if c["model"] == model and now - dt.datetime.fromisoformat(c["at"]) < CACHE_WINDOW]
    return [c for c in recent if c["thinking"] == thinking], [c for c in recent if c["thinking"] != thinking]


def warn_other_partitions(prompt: str, others: list[dict], thinking: str) -> None:
    for call in others:
        prefix = common_prefix(prompt, call["prompt"])
        if prefix >= MIN_SHARED:
            print(f"dsx warning: a {prefix}-char prefix is cached under thinking={call['thinking']}, "
                  f"but this call uses thinking={thinking}; it will not hit", file=sys.stderr)
            return


def common_prefix(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    low, high = 0, limit
    while low < high:                       # binary search on prefix equality
        mid = (low + high + 1) // 2
        if a[:mid] == b[:mid]:
            low = mid
        else:
            high = mid - 1
    return low


def chunks(text: str) -> list[tuple[str, int]]:
    """Content-defined chunks (cut after a line whose hash hits a mark), so a shifted copy chunks identically."""
    found, current = [], []
    for line in text.splitlines(keepends=True):
        current.append(line)
        size = sum(map(len, current))
        if size >= SHINGLE // 4 and (int(hashlib.sha1(line.encode()).hexdigest()[:4], 16) % 8 == 0 or size >= SHINGLE * 2):
            block = "".join(current)
            found.append((hashlib.sha1(block.encode()).hexdigest(), len(block)))
            current = []
    return found


def shingles(text: str) -> dict[str, int]:
    return dict(chunks(text))


def duplicate_chars_within(text: str) -> int:
    seen, duplicated = set(), 0
    for digest, size in chunks(text):
        duplicated += size if digest in seen else 0
        seen.add(digest)
    return duplicated


def persisted_prefix(prompt: str, prior: list[dict]) -> int:
    """Chars of `prompt` the cache should hold as a full unit: an earlier request's whole prompt (end-of-input unit),
    or a prefix two earlier requests already shared (common-prefix unit). Interval units are a bonus, not expected."""
    boundary = max((len(call["prompt"]) for call in prior if prompt.startswith(call["prompt"])), default=0)
    shared = 0
    for index, first in enumerate(prior):
        for second in prior[index + 1:]:
            pair = common_prefix(first["prompt"], second["prompt"])
            if pair > shared and prompt.startswith(first["prompt"][:pair]):
                shared = pair
    return max(boundary, shared)


def precheck(prompt: str, prior: list[dict], accept_miss: str | None = None) -> dict:
    """Before sending: content shared with a recent call but not as a prefix will miss the cache."""
    best = max((common_prefix(prompt, call["prompt"]) for call in prior), default=0)
    persisted = persisted_prefix(prompt, prior)
    if best >= MIN_SHARED and persisted < 0.5 * best:
        print(f"dsx warning: first reuse of a {best}-char prefix; only interval units can hit until it persists "
              "(it will after this call)", file=sys.stderr)
    mine = shingles(prompt)
    shared = 0
    for call in prior:
        theirs = set(shingles(call["prompt"]))
        shared = max(shared, sum(size for digest, size in mine.items() if digest in theirs))
    if shared >= MIN_SHARED and best < 0.5 * shared and not accept_miss:
        raise MissedCacheError(f"{shared} chars are shared with a call in the last 24h, but only the first {best} "
                               "form a common prefix. Put the shared content first so it caches.")
    duplicated = duplicate_chars_within(prompt)
    if duplicated >= MIN_SHARED:
        print(f"dsx warning: {duplicated} chars repeat within this prompt; deliberate (RE2)?", file=sys.stderr)
    return {"expected_prefix_chars": persisted, "common_prefix_chars": best, "shared_chars": shared,
            "duplicated_chars": duplicated}


def postcheck(prompt: str, usage: dict, expected_prefix_chars: int) -> None:
    chars_per_token = len(prompt) / max(usage["prompt_tokens"], 1)
    expected_hit = expected_prefix_chars / chars_per_token - CACHE_BLOCK_TOKENS
    actual_hit = usage.get("prompt_cache_hit_tokens", 0)
    if expected_hit >= 1024 and actual_hit < 0.5 * expected_hit:
        raise MissedCacheError(f"expected about {expected_hit:.0f} cached tokens from the shared prefix, got {actual_hit}. "
                               "The prefix differs somewhere, or the cache was evicted.")


def body_for(prompt: str, model: str, thinking: str) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True,
            "stream_options": {"include_usage": True}}
    if thinking == "off":
        body["thinking"] = {"type": "disabled"}
    elif thinking in ("high", "max"):
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = thinking
    return body


def stream(body: dict) -> tuple[str, str, dict]:
    request = urllib.request.Request(f"{API}/chat/completions", json.dumps(body).encode(),
                                     {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
    content, reasoning, usage = [], [], {}
    with urllib.request.urlopen(request, timeout=STALL_SECONDS) as response:   # timeout applies per read: a stall timeout
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[5:])
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                content.append(delta.get("content") or "")
                reasoning.append(delta.get("reasoning_content") or "")
    return "".join(content), "".join(reasoning), usage


def call(prompt: str, out: pathlib.Path, model: str = "flash", thinking: str = "auto",
         accept_miss: str | None = None) -> dict:
    """accept_miss: the reason a known cache miss is worth it; logged with the call."""
    model, now = MODELS.get(model, model), dt.datetime.now(dt.timezone.utc)
    same, others = recent_calls(model, thinking, now)
    warn_other_partitions(prompt, others, thinking)
    checks = precheck(prompt, same, accept_miss)
    started = time.time()
    try:
        content, reasoning, usage = stream(body_for(prompt, model, thinking))
    except socket.timeout as error:
        raise TimeoutError(f"no data for {STALL_SECONDS}s: stalled") from error
    out.write_text(content)
    out.with_name(out.name + ".reasoning").write_text(reasoning)
    record = {"at": now.isoformat(), "model": model, "thinking": thinking, "seconds": round(time.time() - started, 1),
              "usage": usage, "usd": round(cost(usage, model, now), 6), "out": str(out),
              "accept_miss": accept_miss, "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16], "prompt": prompt, **checks}
    HOME.mkdir(exist_ok=True)
    with LOG.open("a") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({k: record[k] for k in ("model", "thinking", "seconds", "usd")} | {
        "hit": usage.get("prompt_cache_hit_tokens"), "miss": usage.get("prompt_cache_miss_tokens"),
        "out_tokens": usage.get("completion_tokens")}), file=sys.stderr)
    postcheck(prompt, usage, checks["expected_prefix_chars"])
    return record


def balance() -> float:
    request = urllib.request.Request(f"{API}/user/balance", headers={"Authorization": f"Bearer {key()}"})
    value = float(json.load(urllib.request.urlopen(request, timeout=30))["balance_infos"][0]["total_balance"])
    HOME.mkdir(exist_ok=True)
    with BALANCES.open("a") as log:
        log.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(), "usd": value}) + "\n")
    return value


def calls_since(since: dt.datetime) -> list[dict]:
    lines = LOG.read_text().splitlines() if LOG.exists() else []
    return [c for c in map(json.loads, filter(None, lines)) if dt.datetime.fromisoformat(c["at"]) >= since]


def reconcile() -> str:
    snapshots = [json.loads(line) for line in BALANCES.read_text().splitlines() if line.strip()]
    first, now_usd = snapshots[0], balance()
    spent = sum(c["usd"] for c in calls_since(dt.datetime.fromisoformat(first["at"])))
    return (f"since {first['at']}: calculated ${spent:.4f}, balance moved ${first['usd'] - now_usd:.2f} "
            "(whole cents; charges post a few minutes late)")


def report(hours: float) -> str:
    calls = calls_since(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours))
    hit = sum(c["usage"].get("prompt_cache_hit_tokens", 0) for c in calls)
    miss = sum(c["usage"].get("prompt_cache_miss_tokens", 0) for c in calls)
    output = sum(c["usage"].get("completion_tokens", 0) for c in calls)
    return (f"{len(calls)} calls, ${sum(c['usd'] for c in calls):.4f}, input {hit + miss} "
            f"({hit / max(hit + miss, 1):.0%} cached), output {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("call")
    run.add_argument("prompt_file", type=pathlib.Path)
    run.add_argument("out_file", type=pathlib.Path)
    run.add_argument("--model", default="flash")
    run.add_argument("--thinking", default="auto", choices=("auto", "off", "high", "max"))
    sub.add_parser("balance")
    sub.add_parser("reconcile")
    rep = sub.add_parser("report")
    rep.add_argument("--hours", type=float, default=24)
    args = parser.parse_args()
    if args.command == "call":
        call(args.prompt_file.read_text(), args.out_file, args.model, args.thinking)
    elif args.command == "balance":
        print(balance())
    elif args.command == "reconcile":
        print(reconcile())
    else:
        print(report(args.hours))


if __name__ == "__main__":
    main()
