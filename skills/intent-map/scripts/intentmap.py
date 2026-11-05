#!/usr/bin/env python3
"""Intent maps from one s-expression: a static column diagram (mermaid -> PNG), an interactive force graph with
animated edges showing flow direction (one HTML page in artifact form, no libraries: publish it with the Artifact
tool), and optionally a doc in an artifact db for the Intent Maps viewer. Checks the map's contract first.

usage: intentmap.py MAP.sexpr [--out DIR] [--no-png] [--store ARTIFACT_URL]

  (intent-map "title"
    (project "name")                      ; optional: groups maps in the viewer
    (ref other-slug "why")                ; optional, repeatable: this map refers to another stored map
    (goal G "what Joe wants")
    (need N1 "a need" :serves G)
    (solution S1 "how it is met" :meets N1 :status built)
    (test T1 "what would show it works" :tests (S1)))

Statuses: built measured partial design untested not-built. Contract: every need serves a known goal; every
solution meets known needs; every test tests known solutions; ids are unique. A need with no solution is drawn as
UNMET and reported, since a goal with an unmet need isn't mapped to an implementation yet.
--store writes the map to maps/<file stem> in the artifact's db (needs a claude.ai/code session; see the lsdb skill).
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

from imcheck import check, met_needs, status_counts, style_of, tested_by    # noqa: F401  (re-exported)
from imparse import KINDS, STATUSES, IntentMap, Node, Ref, parse, read, read_map, tokens    # noqa: F401
from imrender import force_page, mermaid, page_data    # noqa: F401
from imstore import payload, store    # noqa: F401


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("map", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--no-png", action="store_true")
    parser.add_argument("--store", metavar="URL", help="also write the map to maps/<slug> in this artifact's db")
    args = parser.parse_args()
    source = args.map.read_text()
    parsed = read_map(source)
    warnings = check(parsed.nodes, parsed.refs)
    out = args.out or args.map.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = args.map.stem
    (out / f"{stem}.mmd").write_text(mermaid(parsed.title, parsed.nodes))
    (out / f"{stem}.html").write_text(force_page(parsed.title, parsed.nodes, warnings))
    made = [out / f"{stem}.mmd", out / f"{stem}.html"]
    if not args.no_png:
        if not shutil.which("mmdc"):
            raise SystemExit("mmdc (mermaid CLI) not found: install it, or pass --no-png")
        subprocess.run(["mmdc", "-i", str(out / f"{stem}.mmd"), "-o", str(out / f"{stem}.png"), "-b", "white",
                        "-s", "2"], check=True, capture_output=True)
        made.append(out / f"{stem}.png")
    for warning in warnings:
        print(warning, file=sys.stderr)
    print("\n".join(map(str, made)))
    if args.store:
        doc = store(args.store, stem, source)
        print(f"stored maps/{stem}: {len(doc['data']['nodes'])} nodes, project {doc['project'] or '-'}, "
              f"{len(doc['refs'])} refs, counts {doc['counts']}")


if __name__ == "__main__":
    main()
