#!/usr/bin/env python3
"""winnow log splitter — procedural graph slicing.

Split is merge's cheaper sibling: where merge needed content hashes to
decide identity, split needs no semantics at all — every useful slicing
criterion is already queryable structure. This tool extracts a valid
sub-log from a folded log:

  seeds     — from --query (spec 12 query syntax), --seed ids, or both
  expansion — --hops N over the profile's protected edge set
              (--component expands to the full connected component)
  closure   — payload node-references are always pulled in (validity);
              live hard constraints ride along by default, because
              spec 10.6 makes them temperature-exempt machinery config
  boundary  — edges survive only if both endpoints made the slice; cut
              edges are recorded as comments (the parent log keeps the
              archaeology)

Node ids are KEPT, not renumbered: a slice is the same lineage as its
parent, so cross-references back to the parent log stay meaningful.
(Merge renumbers only because two lineages collide.)

Usage:
    python3 split.py LOG.wno --query "frame=claim status=live" --out slice.wno
    python3 split.py LOG.wno --seed d3,q2 --hops 2 --out topic.wno
    python3 split.py LOG.wno --seed d3 --component --out cluster.wno
    python3 split.py LOG.wno --query "status=superseded" --rest live.wno --out dormant.wno

--rest writes the complement slice (each side gets its own validity
closure, so the two outputs may overlap on referenced nodes — a slice
pair is a cover, not a partition).
"""
import argparse
import sys

from fold import Graph, parse, tokenize, sx, ANN_ORDER, _symbols


def load(path):
    g = Graph()
    for form in parse(tokenize(open(path).read())):
        if form and form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    errs = g.validate()
    if errs:
        sys.exit(f"{path}: refusing to split an invalid log: {errs}")
    return g


def _node_refs(g, payload):
    return [s for s in _symbols(payload) if s in g.nodes]


def slice_ids(g, seeds, hops=1, carry_constraints=True):
    """Selected node ids for a slice: seeds -> edge expansion ->
    side-effect-state carry -> reference-validity closure (fixpoint)."""
    protect = g.profile["protect"]
    adj = {}
    for t, a, b in g.edges:
        if t in protect:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    # payload node-refs are first-class connections (spec section 4):
    # expansion treats them as adjacency in both directions
    for nid, n in g.nodes.items():
        for ref in _node_refs(g, n["payload"]):
            adj.setdefault(nid, set()).add(ref)
            adj.setdefault(ref, set()).add(nid)
    sel = {s for s in seeds if s in g.nodes}
    frontier, step = set(sel), 0
    while frontier and (hops < 0 or step < hops):
        nxt = {nb for x in frontier for nb in adj.get(x, ())} - sel
        sel |= nxt
        frontier = nxt
        step += 1
    if carry_constraints:
        sel |= {nid for nid, n in g.nodes.items()
                if n["frame"] == "constraint" and n["status"] == "live"
                and n.get("strength") == "hard"}
    changed = True
    while changed:                       # validity closure over payload refs
        changed = False
        for nid in list(sel):
            for ref in _node_refs(g, g.nodes[nid]["payload"]):
                if ref not in sel:
                    sel.add(ref)
                    changed = True
    return sel


def split(g, sel):
    """Return (terms, node_ids, kept_edges, cut_edges) for the slice."""
    kept, cut = [], []
    for e in g.edges:
        t, a, b = e
        n_in = (a in sel) + (b in sel)
        if n_in == 2:
            kept.append(e)
        elif n_in == 1:
            cut.append(e)
    used = set()
    for nid in sel:
        used.update(_symbols(g.nodes[nid]["payload"]))
    terms = {tid: tail for tid, tail in g.terms.items() if tid in used}
    ordered = [nid for nid in sorted(sel, key=g._node_key)]
    return terms, ordered, sorted(set(kept)), sorted(set(cut))


def render(g, terms, node_ids, edges, cut):
    if g.meta:
        meta_parts = ["meta"]
        for k, v in g.meta.items():
            meta_parts += [":" + k, v]
        header = sx(meta_parts)
    else:
        header = '(meta :winnow-version "0.2" :semantic-rep "registry-v0.1")'
    lines = [header, ""]
    lines.append(f"; slice of parent log: {len(node_ids)} of "
                 f"{len(g.nodes)} nodes; ids preserved from parent")
    for t, a, b in cut:
        lines.append(f"; cut edge ({t} {a} {b}) — far endpoint in parent")
    lines.append("(delta :turn 0")
    for tid in sorted(terms):
        lines.append("  " + sx(["term", tid] + list(terms[tid])))
    for nid in node_ids:
        n = g.nodes[nid]
        parts = [n["frame"], nid]
        parts += n["payload"] if n["frame"] == "def" else [n["payload"]]
        for k in ANN_ORDER:
            if k in n:
                parts += [":" + k, n[k]]
        lines.append("  " + sx(["add", parts]))
    for e in edges:
        lines.append("  " + sx(["add", ["edge", list(e)]]))
    lines[-1] += ")"
    return "\n".join(lines) + "\n"


def _write(path, text, label):
    with open(path, "w") as f:
        f.write(text)
    g = Graph()
    for form in parse(tokenize(text)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    errs = g.validate()
    print(f"wrote {path} ({label}): {len(g.nodes)} nodes, "
          f"{len(g.edges)} edges, {len(g.terms)} terms; validation "
          f"{'OK' if not errs else errs}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log")
    ap.add_argument("--query", help="seed selector (spec 12 query syntax)")
    ap.add_argument("--seed", help="comma-separated node ids to seed from")
    ap.add_argument("--hops", type=int, default=1,
                    help="edge-expansion radius from seeds (default 1)")
    ap.add_argument("--component", action="store_true",
                    help="expand to the full connected component")
    ap.add_argument("--no-constraints", action="store_true",
                    help="don't carry live hard constraints")
    ap.add_argument("--out", required=True, help="slice output path")
    ap.add_argument("--rest", help="also write the complement slice here")
    ns = ap.parse_args()

    g = load(ns.log)
    seeds = []
    if ns.query:
        seeds += g.query_ids(ns.query)
    if ns.seed:
        seeds += ns.seed.split(",")
    if not seeds:
        sys.exit("no seeds: pass --query and/or --seed")
    unknown = [s for s in seeds if s not in g.nodes]
    if unknown:
        sys.exit(f"unknown seed ids: {' '.join(unknown)}")

    hops = -1 if ns.component else ns.hops
    carry = not ns.no_constraints
    sel = slice_ids(g, seeds, hops=hops, carry_constraints=carry)
    _write(ns.out, render(g, *split(g, sel)), "slice")

    if ns.rest:
        rest_seeds = set(g.nodes) - sel
        rest = slice_ids(g, rest_seeds, hops=0, carry_constraints=carry)
        _write(ns.rest, render(g, *split(g, rest)), "rest")


if __name__ == "__main__":
    main()
