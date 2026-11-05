"""The map's contract: hard errors raise, unmet needs come back as warnings."""
from __future__ import annotations

from collections import Counter

from imparse import STATUSES, Node, Ref


def check(nodes: list[Node], refs: tuple[Ref, ...] = ()) -> list[str]:
    """Hard errors raise; returns warnings (unmet needs)."""
    by_id: dict[str, Node] = {}
    for node in nodes:
        if node.id in by_id:
            raise ValueError(f"duplicate id {node.id}")
        by_id[node.id] = node
    wants = {"need": "goal", "solution": "need", "test": "solution"}
    for node in nodes:
        if node.kind == "goal":
            continue
        if not node.links:
            raise ValueError(f"{node.kind} {node.id} links to nothing: every {node.kind} needs a {wants[node.kind]}")
        for target in node.links:
            if target not in by_id or by_id[target].kind != wants[node.kind]:
                raise ValueError(f"{node.id} -> {target}: expected an existing {wants[node.kind]}")
        if node.kind == "solution" and node.status not in STATUSES:
            raise ValueError(f"solution {node.id}: :status must be one of {STATUSES}")
    slugs = [ref.slug for ref in refs]
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"a map refers to the same map twice: {sorted(s for s in set(slugs) if slugs.count(s) > 1)}")
    met = {target for node in nodes if node.kind == "solution" for target in node.links}
    warnings = [f"UNMET: need {node.id} has no solution ({node.text})" for node in nodes
                if node.kind == "need" and node.id not in met]
    served = {target for node in nodes if node.kind == "need" for target in node.links}
    warnings += [f"goal {node.id} has no needs" for node in nodes if node.kind == "goal" and node.id not in served]
    return warnings


def tested_by(nodes: list[Node]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in nodes:
        if node.kind == "test":
            for target in node.links:
                result.setdefault(target, []).append(node.id)
    return result


def met_needs(nodes: list[Node]) -> set[str]:
    return {target for node in nodes if node.kind == "solution" for target in node.links}


def style_of(node: Node, met: set[str]) -> str:
    if node.kind == "solution":
        return node.status
    if node.kind == "need" and node.id not in met:
        return "unmet"
    return node.kind


def status_counts(nodes: list[Node]) -> dict[str, int]:
    """Solutions by status, plus `unmet` for needs nobody meets; zero counts left out."""
    met = met_needs(nodes)
    counts = Counter(node.status for node in nodes if node.kind == "solution")
    counts.update("unmet" for node in nodes if node.kind == "need" and node.id not in met)
    return dict(counts)
