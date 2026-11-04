#!/usr/bin/env python3
"""winnow query views over a folded graph: query, concepts, stale, hashes.

    query     nodes matching key=value criteria over
              (frame, status, term, by, src), in full
    concepts  the term registry sorted by usage mass
    stale     open questions, proposed decisions and doing actions
              untouched for N deltas (maintenance surface)
    hashes    content-hash id table (docs/hash-ids.md)

Usage:
    python3 query.py LOG.wno "frame=claim status=live by=user" [--upto N]
    python3 query.py LOG.wno --concepts
    python3 query.py LOG.wno --stale [N]       # default 3
    python3 query.py LOG.wno --hashes
"""
import sys

from fold import load, flag_value
from sexpr import _symbols, anns


def query_ids(g, expr):
    """Trivial query layer (spec 12): space-separated key=value pairs
    over (frame, status, term, by, src). term matches any symbol
    appearing in the payload. Returns matching node ids."""
    crit = dict(p.split("=", 1) for p in expr.split())
    out = []
    for nid in sorted(g.nodes, key=g._node_key):
        n = g.nodes[nid]
        ok = True
        for k, v in crit.items():
            if k == "term":
                ok = v in _symbols(n["payload"])
            elif k == "src":
                val = n.get("src")
                ok = (v == val or
                      (isinstance(val, list) and v in val))
            else:
                ok = str(n.get(k)) == v
            if not ok:
                break
        if ok:
            out.append(nid)
    return out


def query(g, expr):
    return "\n".join(g._full_line(i) for i in query_ids(g, expr))


def concepts(g):
    """Registry sorted by usage mass (desc), then id."""
    usage, mass = g.term_usage(), g.term_mass()
    lines = []
    for tid in sorted(g.terms, key=lambda t: (-mass[t], t)):
        refs = usage[tid]
        gloss = anns(list(g.terms[tid])).get("gloss", "")
        gl = str(gloss)
        lines.append(f"{tid:<24} mass={mass[tid]:<3} "
                     f"refs={len(refs):<3} "
                     f"{gl[:60]}{'...' if len(gl) > 60 else ''}")
    return "\n".join(lines)


def stale(g, min_age=3):
    """Open questions, proposed decisions, doing actions untouched for at
    least min_age deltas. Maintenance surface, not residency input."""
    want = {("question", "open"), ("decision", "proposed"),
            ("action", "doing")}
    lines = []
    for nid in sorted(g.nodes, key=g._node_key):
        n = g.nodes[nid]
        if (n["frame"], n["status"]) not in want:
            continue
        age = g.deltas - g.last_touch.get(nid, 0)
        if age >= min_age:
            lines.append(f"; stale {age:>3} deltas: "
                         f"{g._payload_line(nid)} :status {n['status']}")
    return "\n".join(lines) if lines else "; no stale nodes"


def hashes(g):
    lines = []
    for nid in sorted(g.nodes, key=g._node_key):
        lines.append(f"{nid:<4} {g.hash_id(nid)}  "
                     f"{g._payload_line(nid)}")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        sys.exit(1)
    upto = flag_value(argv, "--upto")
    g = load(argv[0], int(upto) if upto is not None else None)
    if "--concepts" in argv:
        print(concepts(g))
    elif "--hashes" in argv:
        print(hashes(g))
    elif "--stale" in argv:
        n = flag_value(argv, "--stale")
        print(stale(g, int(n) if n and n.isdigit() else 3))
    else:
        rest = [a for i, a in enumerate(argv[1:], 1)
                if a != "--upto" and argv[i - 1] != "--upto"]
        if not rest:
            print(__doc__)
            sys.exit(1)
        print(query(g, rest[0]))


if __name__ == "__main__":
    main()
