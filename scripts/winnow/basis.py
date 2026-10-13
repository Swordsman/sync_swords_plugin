#!/usr/bin/env python3
"""winnow basis: what each conclusion rests on, and whether that still holds.

A view over the folded graph, built on logic, not scores: "assuming X, we
infer Y, so Y holds so long as X holds." Two edge types are read as
grounds, with different logic:

    (depends Y X)     Y needs X: every premise must hold        (AND)
    (motivates X Y)   X is a reason for Y: one surviving reason
                      is enough                                 (OR)

Evidence edges (supports, contradicts) argue for or against a node but do
not cascade, with one exception: a node under a live `contradicts` is
disputed, so whatever rests on it is pending.

Every node gets one of three labels:

    holds       it, and everything it rests on, stands
    pending     it rests on something unsettled: a hedge (:modal may), a
                proposed decision, an open question, an unfinished action,
                a disputed node, or a circular basis
    undermined  it rests on something rejected: corrected, retracted,
                superseded, abandoned, dropped, relaxed, retired or
                deprecated

The label of a conclusion is worse of its own state and its grounds, so
correcting one premise flags everything built on it the next time the
view runs. Nothing here is logged; the log stays a record of what was
said.

Usage:
    python3 basis.py LOG.wno [--upto N]     every conclusion, labeled
    python3 basis.py LOG.wno --undermined   only undermined ones
    python3 basis.py LOG.wno --node ID      one node: label, chains, grounds
    python3 basis.py LOG.wno --rests-on ID  blast radius: all that rests on ID
"""
import sys

from fold import load, flag_value

REJECTED = {"corrected", "retracted", "superseded", "abandoned", "dropped",
            "relaxed", "retired", "deprecated"}
UNSETTLED = {"proposed", "open", "todo", "doing", "blocked"}
RANK = {"holds": 0, "pending": 1, "undermined": 2}


class Basis:
    """A node's label, the causes behind it, and the base nodes it rests on.

    causes maps each cause node to (path, label, why), path running from
    the node down to the cause; only the shortest path per cause is kept.
    """

    def __init__(self, label, causes, rests_on):
        self.label = label
        self.causes = causes
        self.rests_on = rests_on


def premises(g, nid):
    """Nodes nid needs: (depends nid X)."""
    return [b for t, a, b in g.edges if t == "depends" and a == nid and b in g.nodes]


def reasons(g, nid):
    """Nodes that are reasons for nid: (motivates X nid)."""
    return [a for t, a, b in g.edges if t == "motivates" and b == nid and a in g.nodes]


def own_state(g, nid):
    """(label, why) for the node alone, ignoring what it rests on."""
    n = g.nodes[nid]
    st = n["status"]
    if st in REJECTED:
        why = st
        newer = [a for t, a, b in g.edges if t == "supersedes" and b == nid]
        if newer:
            why += f", replaced by {', '.join(newer)}"
        turn = g.touched_at_turn(nid)
        if turn is not None:
            why += f" (last changed t{turn})"
        return "undermined", why
    if str(n.get("modal")) == "may":
        return "pending", "hedged (:modal may)"
    if st in UNSETTLED:
        return "pending", st
    challengers = [a for t, a, b in g.edges
                   if t == "contradicts" and b == nid and a in g.nodes
                   and g.nodes[a]["status"] not in REJECTED]
    if challengers:
        return "pending", f"disputed by {', '.join(challengers)}"
    return "holds", None


def _worst(labels):
    return max(labels, key=RANK.__getitem__, default="holds")


def analyze(g):
    """nid -> Basis for every node in the graph."""
    memo = {}

    def visit(nid, stack):
        """(Basis, cut): cut is True when a cycle was cut below nid, in
        which case the result depends on where the walk entered the cycle
        and isn't memoized."""
        if nid in memo:
            return memo[nid], False
        if nid in stack:
            return Basis("pending", {nid: ((nid,), "pending", "circular basis")},
                         set()), True
        label, why = own_state(g, nid)
        causes = {nid: ((nid,), label, why)} if label != "holds" else {}
        prem, rsn = premises(g, nid), reasons(g, nid)
        rests_on = set() if prem or rsn else {nid}
        labels, cut = [label], False

        def absorb(b):
            for cause, (path, lab, w) in b.causes.items():
                p = (nid,) + path
                if cause not in causes or len(p) < len(causes[cause][0]):
                    causes[cause] = (p, lab, w)

        for p in prem:                                   # AND: all needed
            b, c = visit(p, stack | {nid})
            cut |= c
            rests_on |= b.rests_on
            labels.append(b.label)
            if b.label != "holds":
                absorb(b)
        if rsn:                                          # OR: one suffices
            bs = []
            for r in rsn:
                b, c = visit(r, stack | {nid})
                cut |= c
                rests_on |= b.rests_on
                bs.append(b)
            best = min((b.label for b in bs), key=RANK.__getitem__)
            labels.append(best)
            if best != "holds":
                for b in bs:
                    absorb(b)
        result = Basis(_worst(labels), causes, rests_on)
        if not cut:
            memo[nid] = result
        return result, cut

    return {nid: visit(nid, frozenset())[0] for nid in g.nodes}


def rests_on_closure(g, nid):
    """Everything that rests on nid, directly or through others."""
    up = {}
    for t, a, b in g.edges:
        if t == "depends":
            up.setdefault(b, set()).add(a)      # a needs b
        elif t == "motivates":
            up.setdefault(a, set()).add(b)      # a is a reason for b
    seen, todo = set(), [nid]
    while todo:
        for x in up.get(todo.pop(), ()):
            if x not in seen and x in g.nodes:
                seen.add(x)
                todo.append(x)
    return seen


def has_grounds(g, nid):
    return bool(premises(g, nid) or reasons(g, nid))


def _render_one(g, nid, b):
    lines = [f"{g._payload_line(nid)}  {b.label}"]
    for cause, (path, lab, why) in sorted(b.causes.items(),
                                          key=lambda kv: (len(kv[1][0]), kv[0])):
        lines.append(f"  ; {' -> '.join(path)}: {why}")
    base = sorted(b.rests_on - {nid}, key=g._node_key)
    if base:
        lines.append(f"  ; rests on: {', '.join(base)}")
    return lines


def render(g, only=None):
    """Every node with grounds (or `only` those labeled `only`)."""
    result = analyze(g)
    shown = [nid for nid in sorted(g.nodes, key=g._node_key) if has_grounds(g, nid)]
    counts = {k: sum(1 for n in shown if result[n].label == k) for k in RANK}
    lines = [f"; basis @ turn {g.turn} -- derived, never logged; "
             f"{len(shown)} nodes with grounds: {counts['holds']} hold, "
             f"{counts['pending']} pending, {counts['undermined']} undermined"]
    for nid in shown:
        if only and result[nid].label != only:
            continue
        lines += _render_one(g, nid, result[nid])
    return "\n".join(lines)


def render_node(g, nid):
    if nid not in g.nodes:
        return f"; no node {nid}"
    b = analyze(g)[nid]
    lines = _render_one(g, nid, b)
    up = sorted(rests_on_closure(g, nid), key=g._node_key)
    lines.append(f"  ; rested on by: {', '.join(up) if up else 'nothing'}")
    return "\n".join(lines)


def render_rests_on(g, nid):
    if nid not in g.nodes:
        return f"; no node {nid}"
    result = analyze(g)
    up = sorted(rests_on_closure(g, nid), key=g._node_key)
    lines = [f"; {len(up)} nodes rest on {nid} ({g._payload_line(nid)} "
             f"{result[nid].label})"]
    lines += [f"{g._payload_line(x)}  {result[x].label}" for x in up]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        sys.exit(1)
    upto = flag_value(argv, "--upto")
    g = load(argv[0], int(upto) if upto is not None else None)
    if "--node" in argv:
        print(render_node(g, flag_value(argv, "--node", "")))
    elif "--rests-on" in argv:
        print(render_rests_on(g, flag_value(argv, "--rests-on", "")))
    else:
        print(render(g, only="undermined" if "--undermined" in argv else None))


if __name__ == "__main__":
    main()
