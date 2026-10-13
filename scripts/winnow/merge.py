#!/usr/bin/env python3
"""winnow cross-log merge (v0.3 prototype) — implements docs/hash-ids.md.

Fold each input log, compute content-hash ids for every node, and join on
the hashes: identical (frame, canonical-payload) pairs collapse to one
node with unioned provenance; edges rewire to the merged ids; term
registries union. Conflicts surface structurally — a status disagreement
becomes an open question node hung off the disputed node — never resolved
silently.

Serial ids are reassigned in the output; hashes are join keys only, so
the wire format is unchanged (spec section 7 untouched).

Usage:
    python3 merge.py A.wno B.wno [C.wno ...] [--out merged.wno]

Output is a valid .wno log (meta header + one all-adds delta at :turn 0),
foldable by fold.py. Without --out it prints to stdout.
"""
import sys

from fold import (Graph, Lit, parse, tokenize, sx, anns, ANN_ORDER,
                  FRAME_ORDER)

ID_PREFIX = {"claim": "c", "decision": "d", "question": "q",
             "constraint": "k", "def": "f", "action": "a", "artifact": "r"}


def load(path):
    g = Graph()
    for form in parse(tokenize(open(path).read())):
        if form and form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    errs = g.validate()
    if errs:
        sys.exit(f"{path}: refusing to merge an invalid log: {errs}")
    return g


def _qualify_src(src, log_id):
    """Qualify bare :src values with their source log id.
    Returns a list of [log_id, turn] pairs."""
    if src is None:
        return []
    if not log_id:
        bare = src if isinstance(src, list) else [src]
        return [[t] for t in bare]
    bare = src if isinstance(src, list) else [src]
    return [[log_id, t] for t in bare]


def _src_union(a, b):
    """Union two lists of qualified :src pairs."""
    seen = []
    keys = set()
    for item in a + b:
        key = tuple(item)
        if key not in keys:
            keys.add(key)
            seen.append(item)
    return seen


def _render_src(qualified):
    """Render qualified :src pairs back to a serializable value.
    Groups turns by log-id for compactness."""
    if not qualified:
        return None
    # all unqualified (single-element items) — stay bare
    if all(len(q) == 1 for q in qualified):
        bare = [q[0] for q in qualified]
        return bare[0] if len(bare) == 1 else bare
    # at least one qualified item — group by log-id
    groups = {}
    order = []
    for q in qualified:
        if len(q) == 1:
            lid, turns = None, [q[0]]
        else:
            lid, turns = q[0], q[1:]
        if lid not in groups:
            groups[lid] = []
            order.append(lid)
        groups[lid].extend(turns)
    parts = []
    for lid in order:
        if lid is None:
            for t in groups[lid]:
                parts.append([t])
        else:
            parts.append([lid] + groups[lid])
    return parts[0] if len(parts) == 1 else parts


def merge(graphs):
    """Return (terms, nodes, edges, conflicts) of the merged graph.
    nodes is an ordered dict new_id -> node dict; edges a sorted list of
    (etype, src, dst) over new ids; conflicts a list of
    (new_id, kept_status, other_status).
    When input graphs carry :log-id in their meta header, :src values in
    the merged output are qualified with the source log's id."""
    by_hash = {}          # hash -> merged node dict (src already qualified)
    hash_order = []       # first-seen order
    conflicts = []
    terms = {}
    per_graph_map = []    # per graph: old nid -> hash

    canon_to_tid = {}     # canon anchor -> chosen term id
    term_remap = {}       # old tid -> merged tid (when canon anchors join)

    for g in graphs:
        log_id = g.meta.get("log-id") if g.meta else None
        if isinstance(log_id, Lit):
            log_id = str(log_id)
        nid_to_hash = {}
        for tid, tail in g.terms.items():
            ta = anns(list(tail))
            canon = str(ta["canon"]) if "canon" in ta else None
            if canon and canon in canon_to_tid:
                term_remap[tid] = canon_to_tid[canon]
            elif tid not in terms:
                terms[tid] = tail
                if canon:
                    canon_to_tid[canon] = tid
            # tid already present and no canon conflict — skip
        for nid in sorted(g.nodes, key=g._node_key):
            h = g.hash_id(nid)
            nid_to_hash[nid] = h
            n = g.nodes[nid]
            q_src = _qualify_src(n.get("src"), log_id)
            if h not in by_hash:
                merged = dict(n)
                merged["_qsrc"] = q_src
                by_hash[h] = merged
                hash_order.append(h)
                continue
            m = by_hash[h]
            m["_qsrc"] = _src_union(m["_qsrc"], q_src)
            if n["status"] != m["status"]:
                conflicts.append((h, m["status"], n["status"]))
            for k, v in n.items():
                m.setdefault(k, v)
        per_graph_map.append(nid_to_hash)

    # render qualified :src back to serializable values
    for h in hash_order:
        m = by_hash[h]
        rendered = _render_src(m.pop("_qsrc"))
        if rendered is not None:
            m["src"] = rendered

    # assign fresh serials, frame-grouped, in first-seen order
    serial = {f: 0 for f in ID_PREFIX}
    hash_to_id = {}
    for f in FRAME_ORDER:
        for h in hash_order:
            if by_hash[h]["frame"] == f:
                serial[f] += 1
                hash_to_id[h] = f"{ID_PREFIX[f]}{serial[f]}"

    def rewrite(payload, nid_to_hash):
        """Node-id and term-id args in payloads point at merged ids."""
        if isinstance(payload, list):
            return [rewrite(x, nid_to_hash) for x in payload]
        if isinstance(payload, Lit):
            return payload
        if payload in nid_to_hash:
            return hash_to_id[nid_to_hash[payload]]
        if payload in term_remap:
            return term_remap[payload]
        return payload

    nodes = {}
    rewritten = set()
    for g, nid_to_hash in zip(graphs, per_graph_map):
        for nid, h in nid_to_hash.items():
            new_id = hash_to_id[h]
            if new_id not in rewritten:
                node = by_hash[h]
                node["payload"] = rewrite(node["payload"], nid_to_hash)
                nodes[new_id] = node
                rewritten.add(new_id)

    edges = set()
    for g, nid_to_hash in zip(graphs, per_graph_map):
        for t, a, b in g.edges:
            new_a = hash_to_id[nid_to_hash[a]] if a in nid_to_hash else None
            if b in nid_to_hash:
                new_b = hash_to_id[nid_to_hash[b]]
            elif t == "about" and (b in terms or b in term_remap):
                new_b = term_remap.get(b, b)
            else:
                new_b = None
            if new_a and new_b:
                edges.add((t, new_a, new_b))

    # status conflicts become open questions about the disputed node;
    # the first-seen status stands until a human or later delta resolves it
    conflict_ops = []
    for h, kept, other in conflicts:
        serial["question"] += 1
        qid = f"q{serial['question']}"
        target = hash_to_id[h]
        conflict_ops.append((qid, target, kept, other))
        edges.add(("about", qid, target))

    ordered = {nid: nodes[nid] for h in hash_order
               for nid in [hash_to_id[h]]}
    return terms, ordered, sorted(edges), conflict_ops


def render(terms, nodes, edges, conflict_ops):
    lines = ['(meta :winnow-version "0.2" :semantic-rep "registry-v0.1")',
             '', '(delta :turn 0']
    for tid in sorted(terms):
        lines.append("  " + sx(["term", tid] + list(terms[tid])))
    for nid, n in nodes.items():
        parts = [n["frame"], nid]
        parts += n["payload"] if n["frame"] == "def" else [n["payload"]]
        for k in ANN_ORDER:
            if k in n:
                parts += [":" + k, n[k]]
        lines.append("  " + sx(["add", parts]))
    for qid, target, kept, other in conflict_ops:
        lines.append("  " + sx(["add", ["question", qid,
                                        ["reconcile-status", target,
                                         kept, other],
                                        ":status", "open",
                                        ":by", "merge-tool",
                                        ":src", "t0"]]))
    for e in edges:
        lines.append("  " + sx(["add", ["edge", list(e)]]))
    lines[-1] += ")"
    return "\n".join(lines) + "\n"


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logs", nargs="+", help="two or more .wno logs")
    ap.add_argument("--out", help="write merged log here (default stdout)")
    ns = ap.parse_args()
    if len(ns.logs) < 2:
        ap.error("need at least two logs to merge")
    out = ns.out
    text = render(*merge([load(p) for p in ns.logs]))
    if out:
        with open(out, "w") as f:
            f.write(text)
        # sanity: the merged log must fold clean
        g = Graph()
        for form in parse(tokenize(text)):
            if form[0] == "meta":
                g.set_meta(form)
            else:
                g.apply(form)
        errs = g.validate()
        print(f"wrote {out}: {len(g.nodes)} nodes, {len(g.edges)} edges, "
              f"{len(g.terms)} terms; validation "
              f"{'OK' if not errs else errs}", file=sys.stderr)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
