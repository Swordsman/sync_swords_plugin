#!/usr/bin/env python3
"""Final dropped list: the union of the message agents' LOST lines (score 2-3) and the DeepSeek thinking-on findings
for blocks the agents missed. DeepSeek only groups duplicate item ids; code assembles the list, so no text is ever
reworded: each group keeps its longest member verbatim and the source ids of every member.

usage: merge_dropped.py RUN_DIR [--reuse]   (--reuse: take DeepSeek's grouping from RUN_DIR/dedup.reply.md)
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import paths  # noqa: E402
sys.path.insert(0, str(paths.JEV_TOOLKIT))
import compaction_check as cc  # noqa: E402
import dsx

TAG_LINE = re.compile(r"^\W*((?:[mb]\d{4}\W*)+)[\s—:–-]+(.*)$")
GROUP_LINE = re.compile(r"\bi\d{3}\b")


def items_from(run: pathlib.Path) -> list[dict]:
    """[{id, sources, text, origin}] — agents first, then DeepSeek-on lines for blocks the agents didn't flag."""
    agents = json.loads((run / "agents.auto.json").read_text())
    flagged = {tag for tag, answer in agents.items() if (answer["score"] or 0) >= 2 and not tag[1:].startswith("99")}
    items = [{"sources": [tag], "text": agents[tag]["lost"], "origin": "agent"} for tag in sorted(flagged)
             if agents[tag]["lost"]]
    found = cc.sections((run / "deepseek.on.md").read_text())
    for kind in ("DROPPED", "WRONG"):
        for line in found[kind]:
            tags = sorted(set(cc.TAG.findall(line)))
            if tags and (kind == "WRONG" or not set(tags) <= flagged):   # agents never report contradictions
                match = TAG_LINE.match(line)
                items.append({"sources": tags, "text": (match.group(2) if match else line).strip(),
                              "origin": "deepseek-on" + (" (summary contradicts log)" if kind == "WRONG" else "")})
    for number, item in enumerate(items, 1):
        item["id"] = f"i{number:03d}"
    return items


def prompt(items: list[dict]) -> str:
    listing = "\n".join(f"[{item['id']}] {item['text']}" for item in items)
    task = ("Find every group of items that are duplicates: items that state the same information, or where one item "
            "contains everything another one says. Items that only overlap partly, or are about the same topic but "
            "each say something the other does not, are not duplicates.")
    return f"""## INTRO

Your job here is to deduplicate a list of findings, so that a later reader gets each piece of information once. This task involves one section, 'items': findings about information that a conversation summary left out, collected from several reviewers, so the same finding can appear more than once in different words. You will not rewrite anything: you only say which items are duplicates of each other, by their ids.

## ITEMS

Each item starts on a new line with an id in brackets, like [i012].

{listing}

## TASK

{task}

Reply with one line per group, listing the ids of the items in that group separated by spaces, for example:
i004 i017
i023 i051 i060
List only groups of two or more items; an item that has no duplicate does not appear. If there are no duplicates at all, reply with exactly NONE.

Read the task again: {task}
"""


def groups_from(reply: str, ids: set[str]) -> list[set[str]]:
    """Union of overlapping groups; unknown ids are a loud error, not silently dropped."""
    groups: list[set[str]] = []
    for line in reply.splitlines():
        found = set(GROUP_LINE.findall(line))
        if unknown := found - ids:
            raise ValueError(f"reply names unknown items {sorted(unknown)}: {line!r}")
        if len(found) < 2:
            continue
        overlapping = [group for group in groups if group & found]
        for group in overlapping:
            groups.remove(group)
            found |= group
        groups.append(found)
    return groups


def contained(items: list[dict], groups: list[set[str]], ask=None) -> dict[tuple[str, str], float]:
    """Jev check of every merge before it happens: P(the kept item states everything the other member states).
    2026-11-05: the dedup pass grouped "stage was removed" with "the six remaining collision groups"."""
    import scout
    ask = ask or scout.ask_jev
    by_id = {item["id"]: item for item in items}
    pairs = [(keeper(by_id, group)["id"], member) for group in groups for member in sorted(group)
             if member != keeper(by_id, group)["id"]]
    if not pairs:
        return {}
    state = {"items": {item_id: by_id[item_id]["text"] for item_id in sorted(set().union(*groups))}}
    questions = {f"{kept}_{member}": {
        "type": "noul", "instructions": f"Does `items.{kept}` state everything that `items.{member}` states, so that "
                                        f"dropping `items.{member}` loses no information?"} for kept, member in pairs}
    answers = ask(state, questions)["answers"]
    return {(kept, member): answers[f"{kept}_{member}"]["noul"] for kept, member in pairs}


def keeper(by_id: dict, group: set[str]) -> dict:
    return max((by_id[member] for member in sorted(group)), key=lambda item: len(item["text"]))


def verified(items: list[dict], groups: list[set[str]], probabilities: dict, threshold: float = 0.5) -> list[set[str]]:
    """Groups with every member Jev doubts split back out (a split-out member stands alone)."""
    by_id = {item["id"]: item for item in items}
    kept_groups = []
    for group in groups:
        kept = keeper(by_id, group)["id"]
        survivors = {kept} | {member for member in group if member != kept
                              and probabilities.get((kept, member), 0) >= threshold}
        if len(survivors) >= 2:
            kept_groups.append(survivors)
    return kept_groups


def assemble(items: list[dict], groups: list[set[str]]) -> list[dict]:
    by_id = {item["id"]: item for item in items}
    grouped = set().union(*groups) if groups else set()
    final = [dict(item, members=[item["id"]]) for item in items if item["id"] not in grouped]
    for group in groups:
        members = sorted(group)
        keep = keeper(by_id, group)
        sources = sorted({source for member in members for source in by_id[member]["sources"]})
        origins = sorted({by_id[member]["origin"] for member in members})
        final.append(dict(keep, sources=sources, origin=", ".join(origins), members=members))
    return sorted(final, key=lambda item: item["sources"][0])


def main() -> None:
    run = pathlib.Path(sys.argv[1])
    items = items_from(run)
    reply_file = run / "dedup.reply.md"
    record = {"response": reply_file.read_text(), "usd": 0.0} if "--reuse" in sys.argv and reply_file.exists() else dsx.call([{"role": "system", "content": cc.SYSTEM}, {"role": "user", "content": prompt(items)}],
                      run / "dedup.reply.md", model="flash", thinking="auto")
    proposed = groups_from(record["response"], {item["id"] for item in items})
    probabilities = contained(items, proposed)
    groups = verified(items, proposed, probabilities)
    final = assemble(items, groups)
    (run / "dropped.json").write_text(json.dumps({
        "items": items, "proposed_groups": [sorted(g) for g in proposed], "groups": [sorted(g) for g in groups],
        "containment": {f"{kept}>{member}": p for (kept, member), p in probabilities.items()}, "final": final},
        indent=1, ensure_ascii=False))
    lines = [f"# Dropped by the compaction summary: {len(final)} items "
             f"(from {len(items)} findings, {len(groups)} duplicate groups merged)", ""]
    lines += [f"- {item['text']} [sources: {', '.join(item['sources'])}; {item['origin']}]" for item in final]
    (run / "dropped.md").write_text("\n".join(lines) + "\n")
    print(lines[0], f"${record['usd']:.4f}")


if __name__ == "__main__":
    main()
