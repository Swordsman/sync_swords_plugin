#!/usr/bin/env python3
"""Extract the full term registry from a .wno file as a readable table.

Usage:
    python3 term-table.py runs/mega-all.wno
    python3 term-table.py runs/mega-sessions.wno

Prints one line per term: term-id | gloss | aka | canon | sources
When given a mega-fold output, also cross-references source files to
show which original .wno each term came from.
"""
import glob
import sys

from fold import Graph, Lit, parse, tokenize, anns


def load_graph(path):
    g = Graph()
    for form in parse(tokenize(open(path).read())):
        if form and form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    return g


def term_sources():
    """Map term ids to source filenames across all non-derived .wno files."""
    exclude = {
        "runs/arc-split/merged-p1p2.wno",
        "runs/arc-split/merged-3way.wno",
        "runs/mega-sessions.wno",
        "runs/mega-all.wno",
        "cbtdag/arc-split/fixtures/fixture-log.wno",
    }
    tid_files = {}
    for f in sorted(glob.glob("**/*.wno", recursive=True)):
        if f in exclude:
            continue
        g = load_graph(f)
        for tid in g.terms:
            if tid not in tid_files:
                tid_files[tid] = []
            tid_files[tid].append(f.split("/")[-1])
    return tid_files


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    g = load_graph(sys.argv[1])
    sources = term_sources()

    for tid in sorted(g.terms):
        tail = list(g.terms[tid])
        ta = anns(tail)
        gloss = ""
        for item in tail:
            if isinstance(item, Lit):
                gloss = str(item)
                break
        canon = str(ta["canon"]) if "canon" in ta else ""
        aka = str(ta["aka"]) if "aka" in ta else ""
        src = ", ".join(sources.get(tid, ["?"]))
        print(f"{tid} | {gloss} | aka={aka} | canon={canon} | sources={src}")


if __name__ == "__main__":
    main()
