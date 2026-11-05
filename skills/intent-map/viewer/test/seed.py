#!/usr/bin/env python3
"""Print the examples' map docs as a JSON list: the seed for check.js. usage: seed.py [SLUG | GRAPH.json ...] (default: all examples;
a GRAPH.json is a stored graph doc, e.g. from dsxgraph.py --out)"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import imstore

examples = pathlib.Path(__file__).resolve().parents[2] / "examples"
args = sys.argv[1:]
graphs = [json.loads(pathlib.Path(a).read_text()) for a in args if a.endswith(".json")]
wanted = {a for a in args if not a.endswith(".json")}
print(json.dumps([imstore.payload(p.stem, p.read_text()) for p in sorted(examples.glob("*.sexpr")) if not wanted or p.stem in wanted] + graphs))
