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
    pending     it rests on something unsettled: a hedge (:modal may), an
                open assumption (:status assumed), a proposed decision, an
                open question, an unfinished action, a disputed node, or a
                circular basis
    undermined  it rests on something rejected: corrected, retracted,
                superseded, abandoned, dropped, relaxed, retired or
                deprecated

The label of a conclusion is worse of its own state and its grounds, so
correcting one premise flags everything built on it the next time the
view runs. Nothing here is logged; the log stays a record of what was
said.

A conditional is a claim (implies A C) over two node ids: "if A, then
C". It discharges A: its grounds are C plus its own, walked with A
treated as holding on every path below it. So it holds when everything
except A holds, and refuting A undermines C but not the conditional.
The open assumptions a node rests on are listed on an `under:` line;
what rests on an assumption is its scope (--rests-on), and a
conditional closes it. Discharge is the only rule: no proof search, and
no conditional anybody didn't state.

Usage:
    python3 basis.py LOG.wno [--upto N]     every conclusion, labeled
    python3 basis.py LOG.wno --undermined   only undermined ones
    python3 basis.py LOG.wno --node ID      one node: label, chains, grounds
    python3 basis.py LOG.wno --rests-on ID  blast radius: all that rests on ID
"""
import re
import sys

from fold import load, flag_value, Lit

REJECTED = {"corrected", "retracted", "superseded", "abandoned", "dropped",
            "relaxed", "retired", "deprecated"}
UNSETTLED = {"proposed", "open", "todo", "doing", "blocked", "assumed"}
RANK = {"holds": 0, "pending": 1, "undermined": 2}
COND = "implies"                     # seeded relation (spec section 4)
IDLIKE = re.compile(r"[cdqkfar][0-9]+\Z")


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


def cond_args(n):
    """(A, C) when node dict n is an unnegated claim (implies A C) over
    two symbols, else None. Whether A and C are nodes is not checked."""
    p = n.get("payload")
    if n.get("frame") != "claim" or str(n.get("neg")) == "true" \
            or not isinstance(p, list) or len(p) != 3 or p[0] != COND:
        return None
    if not all(isinstance(x, str) and not isinstance(x, Lit) for x in p[1:]):
        return None
    return p[1], p[2]


def conditional(g, nid):
    """(A, C) when nid is a conditional: a claim (implies A C) over two
    distinct nodes other than itself. It discharges A (spec section 5)."""
    ac = cond_args(g.nodes[nid])
    if ac and ac[0] != ac[1] and nid not in ac \
            and all(x in g.nodes for x in ac):
        return ac
    return None


def grounds(g, nid):
    """(premises, reasons, discharged): a conditional's consequent joins
    its premises, and its antecedent is discharged below it."""
    prem, rsn = premises(g, nid), reasons(g, nid)
    cond = conditional(g, nid)
    if not cond:
        return prem, rsn, None
    if cond[1] not in prem:
        prem.append(cond[1])
    return prem, rsn, cond[0]


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
    gone = [x for x in cond_args(n) or ()
            if x not in g.nodes and IDLIKE.match(x)]
    if gone:                     # merged or deleted; payloads keep the id
        return "pending", f"conditional over missing node {gone[0]}"
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

    def visit(nid, stack, off):
        """(Basis, cut): cut is True when a cycle was cut below nid, in
        which case the result depends on where the walk entered the cycle
        and isn't memoized. `off` is the antecedents a conditional above
        nid discharged: on this path they hold."""
        if nid in off:
            return Basis("holds", {}, set()), False
        key = (nid, off)
        if key in memo:
            return memo[key], False
        if nid in stack:
            return Basis("pending", {nid: ((nid,), "pending", "circular basis")},
                         set()), True
        label, why = own_state(g, nid)
        causes = {nid: ((nid,), label, why)} if label != "holds" else {}
        prem, rsn, discharged = grounds(g, nid)
        if discharged is not None:
            off = off | {discharged}
        rests_on = set() if prem or rsn else {nid}
        labels, cut = [label], False

        def absorb(b):
            for cause, (path, lab, w) in b.causes.items():
                p = (nid,) + path
                if cause not in causes or len(p) < len(causes[cause][0]):
                    causes[cause] = (p, lab, w)

        for p in prem:                                   # AND: all needed
            b, c = visit(p, stack | {nid}, off)
            cut |= c
            rests_on |= b.rests_on
            labels.append(b.label)
            if b.label != "holds":
                absorb(b)
        if rsn:                                          # OR: one suffices
            bs = []
            for r in rsn:
                b, c = visit(r, stack | {nid}, off)
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
            memo[key] = result
        return result, cut

    return {nid: visit(nid, frozenset(), frozenset())[0] for nid in g.nodes}


def grounds_closure(g, nid):
    """Everything nid rests on, directly or through others. Below a
    conditional its antecedent is discharged, so the walk skips it."""
    out, seen, todo = set(), set(), [(nid, frozenset())]
    while todo:
        x, off = todo.pop()
        prem, rsn, discharged = grounds(g, x)
        if discharged is not None:
            off = off | {discharged}
        for y in prem + rsn:
            if y != x and y not in off and (y, off) not in seen:
                seen.add((y, off))
                out.add(y)
                todo.append((y, off))
    return out


def rests_on_closure(g, nid):
    """Everything that rests on nid, directly or through others. A
    conditional that discharges nid is outside its scope, and so is
    whatever reaches nid only through that conditional."""
    up = {}
    for t, a, b in g.edges:
        if t == "depends":
            up.setdefault(b, set()).add(a)      # a needs b
        elif t == "motivates":
            up.setdefault(a, set()).add(b)      # a is a reason for b
    for x in g.nodes:
        cond = conditional(g, x)
        if cond:
            up.setdefault(cond[1], set()).add(x)  # x rests on its consequent
    seen, todo = set(), [nid]
    while todo:
        for x in up.get(todo.pop(), ()):
            if x not in seen and x in g.nodes:
                seen.add(x)
                todo.append(x)
    # the upward walk over-approximates; discharge makes it exact
    return {x for x in seen if x != nid and nid in grounds_closure(g, x)}


def has_grounds(g, nid):
    n = g.nodes[nid]
    ac = cond_args(n)
    missing_conditional = bool(
        ac and any(x not in g.nodes and IDLIKE.match(x) for x in ac))
    return bool(premises(g, nid) or reasons(g, nid)
                or conditional(g, nid) or missing_conditional)


def _render_one(g, nid, b):
    lines = [f"{g._payload_line(nid)}  {b.label}"]
    for cause, (path, lab, why) in sorted(b.causes.items(),
                                          key=lambda kv: (len(kv[1][0]), kv[0])):
        lines.append(f"  ; {' -> '.join(path)}: {why}")
    under = sorted((c for c in b.causes if g.nodes[c]["status"] == "assumed"),
                   key=g._node_key)
    if under:
        lines.append(f"  ; under: {', '.join(under)}")
    cond = conditional(g, nid)
    if cond:
        lines.append(f"  ; discharges: {cond[0]}")
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
