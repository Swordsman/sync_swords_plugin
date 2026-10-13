#!/usr/bin/env python3
"""Mega-fold: merge all .wno files into one graph and fold.

Discovers .wno files across the repo, merges them via content-hash dedup
(merge.py), folds the result, and reports what collapsed and what didn't.

Usage:
    python3 mega-fold.py                        # all source .wno files
    python3 mega-fold.py --scope sessions       # sessions/ only
    python3 mega-fold.py --scope runs           # runs/ only
    python3 mega-fold.py --out mega.wno         # write merged output
    python3 mega-fold.py --digest               # print digest after stats
    python3 mega-fold.py --concepts             # print concepts after stats
    python3 mega-fold.py --overlap              # show cross-file node/term overlap detail
    python3 mega-fold.py --canon-map canon-map.json  # apply external canon anchors before merge
    python3 mega-fold.py --exclude-terms junk-terms.json  # drop extraction-noise terms
"""
import argparse
import glob
import json
import sys
from collections import Counter

from fold import Graph, Lit, parse, tokenize, anns
from merge import load, merge, render

EXCLUDE = {
    "runs/arc-split/merged-p1p2.wno",
    "runs/arc-split/merged-3way.wno",
    "runs/mega-sessions.wno",
    "runs/mega-all.wno",
    "cbtdag/arc-split/fixtures/fixture-log.wno",
}


def discover(scope):
    files = sorted(glob.glob("**/*.wno", recursive=True))
    files = [f for f in files if f not in EXCLUDE]
    if scope == "sessions":
        files = [f for f in files if f.startswith("sessions/")]
    elif scope == "runs":
        files = [f for f in files if f.startswith("runs/")]
    return files


def load_all(files):
    graphs = []
    for f in files:
        try:
            g = load(f)
            graphs.append((f, g))
        except SystemExit as e:
            print(f"  SKIP {f}: {e}", file=sys.stderr)
    return graphs


def apply_canon_map(graphs, canon_map):
    """Inject external :canon values into graphs' term registries."""
    patched = 0
    for g in graphs:
        for tid, tail in g.terms.items():
            if tid not in canon_map:
                continue
            ta = anns(list(tail))
            if "canon" in ta:
                continue
            g.terms[tid] = list(tail) + [":canon", Lit(canon_map[tid])]
            patched += 1
    return patched


def apply_exclude_terms(graphs, exclude_set):
    """Remove junk term IDs from graphs' term registries."""
    removed = 0
    for g in graphs:
        to_drop = [tid for tid in g.terms if tid in exclude_set]
        for tid in to_drop:
            del g.terms[tid]
            removed += 1
    return removed


def load_exclude_terms(path):
    """Load junk-terms.json: values are lists of term IDs, keyed by category."""
    with open(path) as f:
        data = json.load(f)
    exclude = set()
    for k, v in data.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            exclude.update(v)
    return exclude


def overlap_report(files, graphs):
    hash_to_files = {}
    for f, g in zip(files, graphs):
        for nid in g.nodes:
            h = g.hash_id(nid)
            if h not in hash_to_files:
                hash_to_files[h] = []
            hash_to_files[h].append((f, nid, g.nodes[nid]))

    shared = {h: entries for h, entries in hash_to_files.items()
              if len(entries) > 1}

    tid_to_files = {}
    for f, g in zip(files, graphs):
        for tid in g.terms:
            if tid not in tid_to_files:
                tid_to_files[tid] = []
            tid_to_files[tid].append(f)
    shared_terms = {t: fs for t, fs in tid_to_files.items() if len(fs) > 1}

    lines = []
    lines.append(f"\n--- overlap detail ---")
    lines.append(f"nodes with identical content-hash in 2+ files: {len(shared)}")
    for h, entries in sorted(shared.items(), key=lambda x: -len(x[1])):
        n = entries[0][2]
        lines.append(f"  {n['frame']} {repr(n['payload'])[:70]}")
        for f, nid, _ in entries:
            lines.append(f"    {f} ({nid})")

    lines.append(f"\nterm ids registered in 2+ files: {len(shared_terms)}")
    for t in sorted(shared_terms, key=lambda x: -len(shared_terms[x])):
        lines.append(f"  {t}: {', '.join(f.split('/')[-1] for f in shared_terms[t])}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scope", choices=["all", "sessions", "runs"],
                    default="all")
    ap.add_argument("--out", help="write merged .wno here")
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--concepts", action="store_true")
    ap.add_argument("--overlap", action="store_true",
                    help="show cross-file overlap detail")
    ap.add_argument("--canon-map",
                    help="JSON file mapping term-id -> canon value")
    ap.add_argument("--exclude-terms",
                    help="JSON file listing junk term IDs to drop")
    ns = ap.parse_args()

    files = discover(ns.scope)
    if len(files) < 2:
        ap.error(f"need at least 2 .wno files, found {len(files)}")

    print(f"scope: {ns.scope} ({len(files)} files)")
    pairs = load_all(files)
    loaded_files = [f for f, _ in pairs]
    graphs = [g for _, g in pairs]

    if ns.exclude_terms:
        exclude = load_exclude_terms(ns.exclude_terms)
        removed = apply_exclude_terms(graphs, exclude)
        print(f"exclude terms: {len(exclude)} in list, {removed} removed")

    if ns.canon_map:
        with open(ns.canon_map) as f:
            cmap = {k: v for k, v in json.load(f).items()
                    if not k.startswith("_")}
        patched = apply_canon_map(graphs, cmap)
        print(f"canon map: {len(cmap)} entries, {patched} terms patched")

    sum_n = sum(len(g.nodes) for g in graphs)
    sum_e = sum(len(g.edges) for g in graphs)
    sum_t = sum(len(g.terms) for g in graphs)
    print(f"loaded: {len(graphs)} files, {sum_n} nodes, "
          f"{sum_e} edges, {sum_t} terms (sum)")

    terms, nodes, edges, conflicts = merge(graphs)
    text = render(terms, nodes, edges, conflicts)

    # fold the merged output
    g = Graph()
    for form in parse(tokenize(text)):
        if form and form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    errs = g.validate()

    print(f"\n--- mega-fold result ---")
    print(f"nodes  : {len(nodes):>5}  (was {sum_n}, deduped {sum_n - len(nodes) + len(conflicts)})")
    print(f"edges  : {len(edges):>5}  (was {sum_e})")
    print(f"terms  : {len(terms):>5}  (was {sum_t}, deduped {sum_t - len(terms)})")
    print(f"conflicts: {len(conflicts)}")
    snap = g.snapshot()
    print(f"snapshot : {len(snap)} chars (~{len(snap)//4} tokens)")
    print(f"valid    : {'OK' if not errs else errs}")
    if g.warnings:
        print(f"warnings : {len(g.warnings)}")
        for w in g.warnings:
            print(f"  ! {w}")

    print(f"\n{g.stats()}")

    if ns.overlap:
        print(overlap_report(loaded_files, graphs))

    if ns.digest:
        print(f"\n--- digest ---")
        print(g.digest())

    if ns.concepts:
        print(f"\n--- concepts ---")
        print(g.concepts())

    if ns.out:
        with open(ns.out, "w") as f:
            f.write(text)
        print(f"\nwrote {ns.out}")


if __name__ == "__main__":
    main()
