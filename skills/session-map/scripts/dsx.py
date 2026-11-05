#!/usr/bin/env python3
"""DeepSeek calls with cost accounting, a 24h I/O log, and cache-miss tripwires.

usage: dsx.py prefill PARENT_ID TEXT_FILE   add an assistant node you wrote after a user node; prints its id
       dsx.py call PROMPT_FILE OUT_FILE [--model flash|pro] [--thinking auto|off|high|max]
       dsx.py send PARENT_ID PROMPT_FILE OUT_FILE [--model ..] [--thinking ..]   PARENT_ID: node id or prefix, - for a new
                                         root; prints the reply's node id, which is the PARENT_ID for the next turn
       dsx.py show NODE_ID               the conversation path ending at a node
       dsx.py import                     load ~/.dsx/io.jsonl into the tree store
       dsx.py tree-report                roots, nodes, calls, cache hit share
       dsx.py balance            record a balance snapshot
       dsx.py reconcile          calculated spend since a snapshot vs the balance change
       dsx.py report [--hours H] calls, tokens, cost, cache hit rate
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import hashlib
import itertools
import json
import pathlib
import socket
import sqlite3
import sys
import threading
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
DB = HOME / "dsx.db"
CACHE_WINDOW = dt.timedelta(hours=24)
SHINGLE = 2048            # chars per block when looking for shared content
MIN_SHARED = 8192         # shared chars worth caching
CACHE_BLOCK_TOKENS = 64   # DeepSeek caches in 64-token units
QUEUE_SECONDS = 600       # no first token by then: DeepSeek's documented limit for inference to start
STALL_SECONDS = 120       # gap between tokens once output (thinking included) has started
READ_SECONDS = 60         # socket read timeout: a connection that sends nothing at all, not even keep-alives
MAX_OUTPUT_TOKENS = 393216  # API maximum. Unset, non-thinking output stops at 8192 (deepseek-api notes; hit 2026-11-03)


class StreamError(RuntimeError):
    """The stream stalled, sat queued past the limit, or ended without usage. Nothing is logged for it."""


class TruncatedError(RuntimeError):
    """finish_reason was "length": the reply hit an output limit. Raised after the call is logged and costed."""


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


_LOG_CACHE = {"path": None, "offset": 0, "calls": []}
_LOG_LOCK = threading.Lock()


def logged_calls() -> list[dict]:
    """Every logged call, read incrementally: a broadcast of N calls must not re-parse the whole log N times."""
    with _LOG_LOCK:
        if _LOG_CACHE["path"] != LOG or (LOG.exists() and LOG.stat().st_size < _LOG_CACHE["offset"]):
            _LOG_CACHE.update(path=LOG, offset=0, calls=[])
        if LOG.exists():
            with LOG.open("rb") as log:
                log.seek(_LOG_CACHE["offset"])
                data = log.read()
            complete = data[:data.rfind(b"\n") + 1]
            _LOG_CACHE["calls"] += [json.loads(line) for line in complete.decode().splitlines() if line.strip()]
            _LOG_CACHE["offset"] += len(complete)
        return list(_LOG_CACHE["calls"])


def recent_calls(model: str, thinking: str, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(same cache partition, other thinking settings). Observed 2026-11-01: a thinking=max call got 0 hits on a
    prefix cached by thinking=auto calls, so model + thinking setting is the cache partition."""
    calls = logged_calls()
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


@functools.lru_cache(maxsize=2048)
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
    or a prefix two earlier requests already shared (common-prefix unit). Interval units are a bonus, not expected.
    Linear: with a_f = common_prefix(prompt, f), two priors with different a share exactly min(a) with each other,
    which the prompt matches; priors with equal a share exactly a only if they differ at position a."""
    boundary = max((len(call["prompt"]) for call in prior if prompt.startswith(call["prompt"])), default=0)
    groups: dict[int, list[str]] = {}
    for call in prior:
        groups.setdefault(common_prefix(prompt, call["prompt"]), []).append(call["prompt"])
    shared, higher = 0, False
    for length in sorted(groups, reverse=True):
        members = groups[length]
        if higher or len({text[length:length + 1] for text in members}) >= 2:
            shared = length
            break
        higher = True
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
        theirs = shingles(call["prompt"]).keys()
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


def as_messages(prompt: str | list[dict]) -> list[dict]:
    return [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt


def flatten(prompt: str | list[dict]) -> str:
    """One string per conversation, for prefix checks: a resumed conversation extends its first prompt."""
    return prompt if isinstance(prompt, str) else "\n".join(message["content"] for message in prompt)


def body_for(prompt: str | list[dict], model: str, thinking: str) -> dict:
    body = {"model": model, "messages": as_messages(prompt), "stream": True,
            "stream_options": {"include_usage": True}}
    if thinking == "off":
        body["thinking"] = {"type": "disabled"}
        body["max_tokens"] = MAX_OUTPUT_TOKENS  # thinking modes keep the server default: setting it there is brittle
    elif thinking in ("high", "max"):
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = thinking
    return body


def stream(body: dict) -> tuple[str, str, dict, str | None]:
    request = urllib.request.Request(f"{API}/chat/completions", json.dumps(body).encode(),
                                     {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=READ_SECONDS) as response:
            return parse_stream((raw.decode() for raw in response), time.monotonic)
    except socket.timeout as error:
        raise StreamError(f"no bytes at all for {READ_SECONDS}s, not even keep-alives") from error


def parse_stream(lines, clock) -> tuple[str, str, dict, str | None]:
    """Keep-alive comments and blank lines are not progress: only tokens and usage reset the stall clock."""
    content, reasoning, usage, finish = [], [], {}, None
    started, last_progress = clock(), None
    for raw in lines:
        line, now = raw.strip(), clock()
        if last_progress is None and now - started > QUEUE_SECONDS:
            raise StreamError(f"no first token after {QUEUE_SECONDS}s (queued; keep-alives only)")
        if last_progress is not None and now - last_progress > STALL_SECONDS:
            raise StreamError(f"no new token for {STALL_SECONDS}s after output started")
        if line == "data: [DONE]":
            break
        if not line.startswith("data:"):
            continue
        chunk = json.loads(line[5:])
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            content.append(delta.get("content") or "")
            reasoning.append(delta.get("reasoning_content") or "")
            finish = choice.get("finish_reason") or finish
        last_progress = now
    if not usage:
        raise StreamError("stream ended without usage: incomplete response, not logged")
    return "".join(content), "".join(reasoning), usage, finish


SCHEMA = """
CREATE TABLE IF NOT EXISTS node (
    id TEXT PRIMARY KEY, parent TEXT REFERENCES node(id), role TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'generated' CHECK (origin IN ('generated', 'authored')));
CREATE INDEX IF NOT EXISTS node_parent ON node(parent);
CREATE TABLE IF NOT EXISTS call (
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_node TEXT NOT NULL REFERENCES node(id),
    response_node TEXT NOT NULL REFERENCES node(id), model TEXT NOT NULL, thinking TEXT NOT NULL, usage TEXT NOT NULL,
    usd REAL NOT NULL, reasoning TEXT NOT NULL, seconds REAL NOT NULL, accept_miss TEXT, created_at TEXT NOT NULL);
"""


def open_db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=60)  # broadcasts write from many threads
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    if "origin" not in [column[1] for column in db.execute("PRAGMA table_info(node)")]:   # store made before prefill
        db.execute("ALTER TABLE node ADD COLUMN origin TEXT NOT NULL DEFAULT 'generated'")
    return db


def node_id(parent: str | None, role: str, content: str) -> str:
    return hashlib.sha256("\0".join((parent or "", role, content)).encode()).hexdigest()


def add_node(db: sqlite3.Connection, parent: str | None, role: str, content: str, created_at: str,
             origin: str = "generated") -> str:
    """Idempotent: the same history always maps to the same id, and the first insert keeps its created_at and origin."""
    identity = node_id(parent, role, content)
    db.execute("INSERT OR IGNORE INTO node (id, parent, role, content, created_at, origin) VALUES (?, ?, ?, ?, ?, ?)",
               (identity, parent, role, content, created_at, origin))
    return identity


def add_messages(db: sqlite3.Connection, messages: list[dict], created_at: str) -> str:
    """Store a message list as a chain from a root; returns the last node's id."""
    parent = None
    for message in messages:
        parent = add_node(db, parent, message["role"], message["content"], created_at)
    return parent


def chain(db: sqlite3.Connection, last: str) -> list[tuple[str, str, str]]:
    """(id, role, content) from the root down to `last`."""
    rows = db.execute("""
        WITH RECURSIVE path(id, parent, role, content, depth) AS (
            SELECT id, parent, role, content, 0 FROM node WHERE id = ?
            UNION ALL SELECT node.id, node.parent, node.role, node.content, path.depth + 1
                      FROM node JOIN path ON node.id = path.parent)
        SELECT id, role, content FROM path ORDER BY depth DESC""", (last,)).fetchall()
    if not rows:
        raise KeyError(f"no node {last}")
    return rows


def messages_to(db: sqlite3.Connection, last: str) -> list[dict]:
    return [{"role": role, "content": content} for _, role, content in chain(db, last)]


def store_call(db: sqlite3.Connection, *, request_node: str, response_node: str, model: str, thinking: str,
               usage: dict, usd: float, reasoning: str, seconds: float, accept_miss: str | None, created_at: str) -> None:
    db.execute("INSERT INTO call (request_node, response_node, model, thinking, usage, usd, reasoning, seconds, "
               "accept_miss, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (request_node, response_node, model, thinking, json.dumps(usage), usd, reasoning, seconds,
                accept_miss, created_at))


def ancestor_ids(db: sqlite3.Connection, last: str) -> set[str]:
    return {identity for (identity,) in db.execute("""
        WITH RECURSIVE path(id, parent) AS (
            SELECT id, parent FROM node WHERE id = ?
            UNION ALL SELECT node.id, node.parent FROM node JOIN path ON node.id = path.parent)
        SELECT id FROM path""", (last,))}


def shared_stretch(new: str, siblings: list[str]) -> int:
    """Longest leading stretch that two earlier siblings share and `new` starts with (DeepSeek persists a prefix only
    once two requests have shared it)."""
    return max((min(common_prefix(first, second), common_prefix(new, first))
                for first, second in itertools.combinations(siblings, 2)), default=0)


def cached_prefix_chars(db: sqlite3.Connection, request_node: str, model: str, thinking: str, now: dt.datetime) -> int:
    """Expected cached chars (in flatten() terms) for this request: the larger of
    - the deepest node on its chain that a request in the last 24h, same model and thinking, ended at or replied with;
    - at any node on the chain, everything above it plus the stretch of its content that two such earlier sibling
      requests (same parent, or both roots) share and this node starts with."""
    cached, sent = set(), set()
    for request, response, created_at in db.execute(
            "SELECT request_node, response_node, created_at FROM call WHERE model = ? AND thinking = ?", (model, thinking)):
        if now - dt.datetime.fromisoformat(created_at) < CACHE_WINDOW:
            cached.update((request, response))
            sent |= ancestor_ids(db, request)
    expected = length = 0
    parent = None
    for index, (identity, _, content) in enumerate(chain(db, request_node)):
        before, separator = length, int(index > 0)      # flatten() joins messages with one newline
        length = before + separator + len(content)
        if identity in cached:
            expected = max(expected, length)
        siblings = [other_content for other, other_content in db.execute(
            "SELECT id, content FROM node WHERE parent IS ? AND id != ?", (parent, identity)) if other in sent]
        if len(siblings) >= 2:                         # the parent chain is a persisted unit, plus any shared stretch
            stretch = shared_stretch(content, siblings)
            expected = max(expected, before + (separator + stretch if stretch else 0))
        parent = identity
    return expected


def converse(db: sqlite3.Connection, request_node: str, out: pathlib.Path, model: str, thinking: str,
             accept_miss: str | None) -> dict:
    """Send the chain ending at `request_node` (a user node); store the reply as its child."""
    messages = messages_to(db, request_node)
    prompt = flatten(messages)
    model, now = MODELS.get(model, model), dt.datetime.now(dt.timezone.utc)
    same, others = recent_calls(model, thinking, now)
    warn_other_partitions(prompt, others, thinking)
    checks = precheck(prompt, same, accept_miss)
    checks["expected_prefix_chars"] = cached_prefix_chars(db, request_node, model, thinking, now)
    started = time.time()
    content, reasoning, usage, finish = stream(body_for(messages, model, thinking))
    seconds, usd = round(time.time() - started, 1), round(cost(usage, model, now), 6)
    with db:
        response_node = add_node(db, request_node, "assistant", content, dt.datetime.now(dt.timezone.utc).isoformat())
        store_call(db, request_node=request_node, response_node=response_node, model=model, thinking=thinking,
                   usage=usage, usd=usd, reasoning=reasoning, seconds=seconds, accept_miss=accept_miss,
                   created_at=now.isoformat())
    record = {"at": now.isoformat(), "model": model, "thinking": thinking, "seconds": seconds,
              "usage": usage, "usd": usd, "out": str(out), "finish_reason": finish,
              "accept_miss": accept_miss, "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16], "prompt": prompt,
              "messages": messages, "response": content, "reasoning_chars": len(reasoning), **checks,
              "request_node": request_node, "response_node": response_node}
    HOME.mkdir(exist_ok=True)
    with _LOG_LOCK, LOG.open("a") as log:   # one lock: large lines from parallel calls must not interleave
        log.write(json.dumps(record, ensure_ascii=False) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)   # after logging: a paid call is never lost to a bad path
    out.write_text(content)
    out.with_name(out.name + ".reasoning").write_text(reasoning)
    if finish == "length":
        raise TruncatedError(f"reply truncated at {usage.get('completion_tokens')} output tokens; partial text in {out}")
    print(json.dumps({k: record[k] for k in ("model", "thinking", "seconds", "usd")} | {
        "hit": usage.get("prompt_cache_hit_tokens"), "miss": usage.get("prompt_cache_miss_tokens"),
        "out_tokens": usage.get("completion_tokens")}), file=sys.stderr)
    postcheck(prompt, usage, checks["expected_prefix_chars"])
    return record


def send(parent: str | None, message: str, out: pathlib.Path, model: str = "flash", thinking: str = "auto",
         accept_miss: str | None = None) -> str:
    """Add `message` under `parent` (None: a new root) and send the whole chain. Returns the reply's node id:
    send from it to continue, send from any earlier id to fork."""
    with contextlib.closing(open_db()) as db:
        with db:
            request_node = add_node(db, parent, "user", message, dt.datetime.now(dt.timezone.utc).isoformat())
        return converse(db, request_node, out, model, thinking, accept_miss)["response_node"]


def prefill(parent: str, text: str) -> str:
    """Add an assistant node we wrote ourselves under a user node. DeepSeek sees it as its own reply; no call, no cost."""
    with contextlib.closing(open_db()) as db:
        if chain(db, parent)[-1][1] != "user":
            raise ValueError("a prefilled assistant message must follow a user node")
        with db:
            return add_node(db, parent, "assistant", text, dt.datetime.now(dt.timezone.utc).isoformat(), origin="authored")


def call(conversation: str | list[dict], out: pathlib.Path, model: str = "flash", thinking: str = "auto",
         accept_miss: str | None = None) -> dict:
    """conversation: one prompt, or messages ending on user (a resumed session). accept_miss: the reason a known
    cache miss is worth it; logged with the call. Recorded in the tree as a root chain plus its reply."""
    with contextlib.closing(open_db()) as db:
        with db:
            request_node = add_messages(db, as_messages(conversation), dt.datetime.now(dt.timezone.utc).isoformat())
        return converse(db, request_node, out, model, thinking, accept_miss)


def import_log(db: sqlite3.Connection, path: pathlib.Path) -> dict[str, int]:
    counts = {"imported": 0, "already_imported": 0, "skipped_no_response": 0}
    with db:
        for line in filter(str.strip, path.read_text().splitlines()):
            record = json.loads(line)
            if record.get("response") is None:
                counts["skipped_no_response"] += 1
                continue
            messages = record.get("messages") or [{"role": "user", "content": record["prompt"]}]
            request_node = add_messages(db, messages, record["at"])
            response_node = add_node(db, request_node, "assistant", record["response"], record["at"])
            if db.execute("SELECT 1 FROM call WHERE request_node = ? AND model = ? AND thinking = ? AND created_at = ?",
                          (request_node, record["model"], record["thinking"], record["at"])).fetchone():
                counts["already_imported"] += 1
                continue
            store_call(db, request_node=request_node, response_node=response_node, model=record["model"],
                       thinking=record["thinking"], usage=record["usage"], usd=record["usd"], reasoning="",
                       seconds=record["seconds"], accept_miss=record.get("accept_miss"), created_at=record["at"])
            counts["imported"] += 1
    return counts


def resolve(db: sqlite3.Connection, prefix: str) -> str:
    matches = [identity for (identity,) in db.execute(
        "SELECT id FROM node WHERE substr(id, 1, ?) = ?", (len(prefix), prefix))]
    if len(matches) != 1:
        raise SystemExit(f"{len(matches)} nodes match {prefix!r}")
    return matches[0]


def describe(db: sqlite3.Connection, last: str) -> list[str]:
    return [f"{identity[:12]} {role}: {content[:80].replace(chr(10), ' ')}" for identity, role, content in chain(db, last)]


def tree_report(db: sqlite3.Connection) -> str:
    roots, nodes, calls = (db.execute(f"SELECT COUNT(*) FROM {query}").fetchone()[0]
                           for query in ("node WHERE parent IS NULL", "node", "call"))
    usages = [json.loads(usage) for (usage,) in db.execute("SELECT usage FROM call")]
    hit = sum(usage.get("prompt_cache_hit_tokens", 0) for usage in usages)
    miss = sum(usage.get("prompt_cache_miss_tokens", 0) for usage in usages)
    return f"{roots} roots, {nodes} nodes, {calls} calls, {hit / max(hit + miss, 1):.0%} of input tokens cache hits"


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
    for name in ("call", "send"):
        run = sub.add_parser(name)
        if name == "send":
            run.add_argument("parent")
        run.add_argument("prompt_file", type=pathlib.Path)
        run.add_argument("out_file", type=pathlib.Path)
        run.add_argument("--model", default="flash")
        run.add_argument("--thinking", default="auto", choices=("auto", "off", "high", "max"))
    sub.add_parser("balance")
    sub.add_parser("reconcile")
    rep = sub.add_parser("report")
    rep.add_argument("--hours", type=float, default=24)
    sub.add_parser("show").add_argument("node")
    fill = sub.add_parser("prefill")
    fill.add_argument("parent")
    fill.add_argument("text_file", type=pathlib.Path)
    sub.add_parser("import")
    sub.add_parser("tree-report")
    args = parser.parse_args()
    if args.command == "call":
        call(args.prompt_file.read_text(), args.out_file, args.model, args.thinking)
    elif args.command == "send":
        with contextlib.closing(open_db()) as db:
            parent = None if args.parent == "-" else resolve(db, args.parent)
        print(send(parent, args.prompt_file.read_text(), args.out_file, args.model, args.thinking))
    elif args.command == "prefill":
        with contextlib.closing(open_db()) as db:
            parent = resolve(db, args.parent)
        print(prefill(parent, args.text_file.read_text()))
    elif args.command == "balance":
        print(balance())
    elif args.command == "reconcile":
        print(reconcile())
    elif args.command == "report":
        print(report(args.hours))
    else:
        with contextlib.closing(open_db()) as db:
            if args.command == "show":
                print("\n".join(describe(db, resolve(db, args.node))))
            elif args.command == "import":
                print(import_log(db, LOG))
            else:
                print(tree_report(db))


if __name__ == "__main__":
    main()
