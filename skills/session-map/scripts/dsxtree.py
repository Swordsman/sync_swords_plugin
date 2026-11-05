"""The dsx tree store as a graph. Every node is one message appended to its parent's prefix, so a root-to-node path is the exact
prompt a call saw and a fork is where calls shared a cached prefix and then diverged. Nodes carry what they cost: a call's
request holds the prompt side (tokens, cache hit and miss, input cost), its response the output side; every node also
carries what its whole branch below spent. A tree over the budget keeps its costliest branches and folds the rest into one
rollup node per fork, so forks and totals survive the trimming."""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import heapq
import json
import re
import sqlite3

import dsx

ICON = {"system": "⚙️", "context": "💬", "request": "📤", "response": "🤖", "authored": "✍️", "rollup": "➕"}
Call = collections.namedtuple("Call", "request response model thinking usage usd seconds created")
Row = collections.namedtuple("Row", "id parent role head created origin")


def short(identity: str) -> str:
    return identity[:10]


def label(head: str, width: int = 64) -> str:
    lines = [x.strip() for x in head.splitlines() if x.strip()]
    line = re.sub(r"\s+", " ", " ".join(lines[:2] if lines and lines[0].endswith(":") else lines[:1]))   # "Context:" alone says nothing
    return line if len(line) <= width else line[:width - 1] + "…"


def read(db: sqlite3.Connection) -> tuple[dict, dict, list[Call]]:
    rows = {r[0]: Row(*r) for r in db.execute("SELECT id, parent, role, substr(content, 1, 300), created_at, origin FROM node")}
    kids = collections.defaultdict(list)
    for r in sorted(rows.values(), key=lambda r: r.created):
        kids[r.parent].append(r.id)
    calls = [Call(c[0], c[1], c[2], c[3], json.loads(c[4]), c[5], c[6], c[7]) for c in db.execute(
        "SELECT request_node, response_node, model, thinking, usage, usd, seconds, created_at FROM call")]
    return rows, kids, calls


def tagged(db: sqlite3.Connection, tag: str) -> list[str]:
    try:   # the agent table belongs to msgagents; a store without it has no tags
        return [r[0] for r in db.execute("SELECT id FROM agent WHERE tag = ?", (tag,))]
    except sqlite3.OperationalError:
        return []


def resolve(db: sqlite3.Connection, rows: dict, ref: str | None, days: int = 14) -> str:
    """A node id or prefix, an agent tag (b0001), or by default the largest root made in the last `days` days."""
    if ref:
        hits = tagged(db, ref) or [i for i in rows if i.startswith(ref)]
        if len(hits) != 1:
            raise ValueError(f"{ref!r} names {len(hits)} nodes; give a longer id prefix or an agent tag")
        return hits[0]
    kids = collections.Counter(r.parent for r in rows.values())
    size = {}
    for node_id, r in rows.items():
        top = node_id
        while rows[top].parent:
            top = rows[top].parent
        size[top] = size.get(top, 0) + 1
    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    roots = [i for i, r in rows.items() if r.parent is None and dt.datetime.fromisoformat(r.created) >= recent] or [i for i in rows if rows[i].parent is None]
    return max(roots, key=lambda i: (size[i], kids[i]))


def prices(call: Call) -> dict:
    when = dt.datetime.fromisoformat(call.created)
    out = dsx.cost({"completion_tokens": call.usage.get("completion_tokens", 0)}, call.model, when)
    return {"in": max(call.usd - out, 0.0), "out": out}


def spend(node_calls: list[Call], side: str) -> dict:
    """What a node's own calls cost on one side: the prompt for a request, the output for a response."""
    u = [c.usage for c in node_calls]
    if side == "request":
        hit, miss = sum(x.get("prompt_cache_hit_tokens", 0) for x in u), sum(x.get("prompt_cache_miss_tokens", 0) for x in u)
        got = {"tokens": sum(x.get("prompt_tokens", 0) for x in u), "hit": hit, "hitrate": round(hit / (hit + miss), 3) if hit + miss else None,
               "cost": round(sum(prices(c)["in"] for c in node_calls), 8)}
    else:
        got = {"tokens": sum(x.get("completion_tokens", 0) for x in u), "cost": round(sum(prices(c)["out"] for c in node_calls), 8),
               "think": sum(x.get("completion_tokens_details", {}).get("reasoning_tokens", 0) for x in u),
               "seconds": round(sum(c.seconds for c in node_calls), 1)}
    models = {c.model for c in node_calls}
    return {**got, "model": models.pop() if len(models) == 1 else "mixed"}


def tally(rows: dict, kids: dict, root: str, calls: list[Call]) -> dict:
    """Per node: depth, own calls as request and response, and the branch totals below it (spent, calls, size)."""
    order, depth, stack = [], {root: 0}, [root]
    while stack:
        i = stack.pop(); order.append(i)
        for k in kids[i]:
            depth[k] = depth[i] + 1; stack.append(k)
    asked, answered = collections.defaultdict(list), collections.defaultdict(list)
    for c in calls:
        if c.request in depth:
            asked[c.request].append(c); answered[c.response].append(c)
    info = {i: {"depth": depth[i], "asked": asked[i], "answered": answered[i], "spent": sum(c.usd for c in asked[i]),
                "calls": len(asked[i]), "size": 1} for i in order}
    for i in reversed(order):
        parent = rows[i].parent
        if i != root and parent in info:
            for key in ("spent", "calls", "size"):
                info[parent][key] += info[i][key]
    return info


def keep(kids: dict, info: dict, root: str, budget: int) -> set:
    """The connected top of the tree: nodes in order of what their branch spent, until the budget is used."""
    kept, queue = set(), [(0, 0, root)]
    while queue and len(kept) < budget:
        _, _, i = heapq.heappop(queue); kept.add(i)
        for k in kids[i]:   # a call's response comes with its request: the pair is one spend
            heapq.heappush(queue, (-float("inf"), 0, k) if info[k]["answered"] and info[i]["asked"] else (-info[k]["spent"], -info[k]["size"], k))
    return kept


def style_of(row: Row, info: dict) -> str:
    if info["answered"]:
        return "response"
    return "request" if info["asked"] else "authored" if row.origin == "authored" else "context"


def emit(rows: dict, kids: dict, info: dict, i: int, branch: str) -> dict:
    r, f = rows[i], info[i]
    style = style_of(r, f)
    side = spend(f["asked"], "request") if f["asked"] else spend(f["answered"], "response") if f["answered"] else {}
    node = {"id": short(i), "kind": r.role, "style": style, "text": label(r.head), "icon": ICON["system" if r.role == "system" else style],
            "group": branch, "depth": f["depth"], "branches": len(kids[i]), "fork": len(kids[i]) > 1, **side}
    if f["spent"]:
        node.update(spent=round(f["spent"], 6), calls=f["calls"], size=f["size"])
    return {k: v for k, v in node.items() if v is not None}


def rank(nodes: list[dict]) -> None:
    """priority 0 for nodes that spent nothing, else 1-5 by where their branch's spend falls among the others (a fifth each)."""
    spents = sorted(n["spent"] for n in nodes if "spent" in n)
    for n in nodes:
        n["priority"] = 1 + min(4, 5 * bisect.bisect_left(spents, n["spent"]) // len(spents)) if "spent" in n else 0


def rollup(parent: str, depth: int, branch: str, cut: list[str], info: dict) -> dict:
    total = {key: sum(info[k][key] for k in cut) for key in ("spent", "calls", "size")}
    node = {"id": f"rollup-{short(parent)}", "kind": "rollup", "style": "rollup", "icon": ICON["rollup"], "group": branch, "depth": depth,
            "text": f"+{len(cut)} more branches, {total['size']} nodes", "branches": 0, "fork": False}
    if total["spent"]:
        node.update(spent=round(total["spent"], 6), calls=total["calls"], size=total["size"])
    return node


def graph(db: sqlite3.Connection, root: str | None = None, budget: int = 400) -> dict:
    """{nodes, links, warnings, stats} for the subtree under `root` (see resolve), at most `budget` real nodes plus rollups."""
    rows, kids, calls = read(db)
    top = resolve(db, rows, root)
    info = tally(rows, kids, top, calls)
    kept = keep(kids, info, top, budget)
    nodes, links, stack, branch = [], [], [top], {top: "trunk"}
    while stack:
        i = stack.pop()
        nodes.append(emit(rows, kids, info, i, branch[i]))
        inside = [k for k in kids[i] if k in kept]
        for k in inside:
            branch[k] = k[:6] if branch[i] == "trunk" and len(kids[i]) > 1 else branch[i]
            links.append({"source": short(i), "target": short(k), "kind": "call" if info[i]["asked"] and info[k]["answered"] else "extends"})
        stack.extend(reversed(inside))
        if len(inside) < len(kids[i]):
            nodes.append(rollup(i, info[i]["depth"] + 1, branch[i], [k for k in kids[i] if k not in kept], info))
            links.append({"source": short(i), "target": nodes[-1]["id"], "kind": "rollup"})
    rank(nodes)
    if len({n["id"] for n in nodes}) != len(nodes):
        raise ValueError("short ids collide; raise short() width")
    return {"nodes": nodes, "links": links, "warnings": [], "stats": {"root": short(top), "total": info[top]["size"], "shown": len(nodes),
            "spent": round(info[top]["spent"], 6), "calls": info[top]["calls"]}}
