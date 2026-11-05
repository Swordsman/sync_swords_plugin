#!/usr/bin/env python3
"""Print the examples' map docs as a JSON list: the seed for check.js. usage: seed.py [SLUG ...] (default: all)"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import imstore

examples = pathlib.Path(__file__).resolve().parents[2] / "examples"
wanted = set(sys.argv[1:])
print(json.dumps([imstore.payload(p.stem, p.read_text()) for p in sorted(examples.glob("*.sexpr")) if not wanted or p.stem in wanted]))
