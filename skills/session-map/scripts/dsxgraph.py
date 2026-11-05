#!/usr/bin/env python3
"""A dsx tree as a graph the Intent Maps viewer draws, or as a JSON file.

usage: dsxgraph.py [--root ID|PREFIX|TAG] [--nodes N] [--out FILE.json]
                   [--store URL --slug NAME [--title T] [--project P]]
  --root   subtree to draw: a node id or prefix, or an agent tag (b0001); default the largest root of the last 14 days
  --nodes  most real nodes to keep (default 400); the costliest branches stay, the rest fold into one "+N more" node per fork
  --store  write the graph as maps/NAME in the Intent Maps store at URL (lsdb; needs a claude.ai/code session)
Prints one line: root, nodes shown of total, spend, doc size. A doc must stay under 250 KiB, so --nodes shrinks until it fits.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import dsx
import dsxrules
import dsxtree

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "intent-map" / "scripts"))
import imgraph   # noqa: E402

OPTS = {"flow": False, "reach": "flow"}


def build(db, root: str | None, nodes: int, slug: str, title: str | None, project: str) -> dict:
    """The graph doc, shrinking the node budget until it fits one lsdb doc."""
    while True:
        graph = dsxtree.graph(db, root, nodes)
        stats = graph.pop("stats")
        depth = 1 + max(n["depth"] for n in graph["nodes"])
        try:
            return imgraph.payload(
                slug, title or f"dsx tree {stats['root']}", graph, dsxrules.presets(depth), ["nodes", "cards"], project=project, opts=OPTS,
                goal=f"{stats['shown']} of {stats['total']} messages; {stats['calls']} calls cost ${stats['spent']:.4f}",
                source=f"dsx tree store {dsx.DB}, subtree under {stats['root']}; costliest branches kept, the rest folded into rollup nodes",
                stats={"total": stats["total"], "spent": stats["spent"], "calls": stats["calls"]})
        except ValueError as error:
            if "over the" not in str(error) or nodes <= 20:
                raise
            nodes = int(nodes * 0.85)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root"); ap.add_argument("--nodes", type=int, default=400); ap.add_argument("--out")
    ap.add_argument("--store"); ap.add_argument("--slug"); ap.add_argument("--title"); ap.add_argument("--project", default="dsx")
    args = ap.parse_args()
    if args.store and not args.slug:
        ap.error("--store needs --slug")
    doc = build(dsx.open_db(), args.root, args.nodes, args.slug or "dsx-tree", args.title, args.project)
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(doc, ensure_ascii=False))
    if args.store:
        imgraph.store(args.store, doc)
    print(f"{doc['title']}: {doc['stats']['nodes']} of {doc['stats']['total']} nodes, ${doc['stats']['spent']:.4f}, "
          f"{len(json.dumps(doc, ensure_ascii=False)) // 1024} KiB" + (f" -> maps/{doc['slug']}" if args.store else ""))


if __name__ == "__main__":
    main()
