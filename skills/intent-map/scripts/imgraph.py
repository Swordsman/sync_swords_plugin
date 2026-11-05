"""Storing a generic graph (any source's nodes + links + rules) beside the intent maps, as maps/<slug> with kind "graph"."""
from __future__ import annotations

import datetime
import json

from imparse import SLUG
from imstore import COLLECTION, DESCRIPTION, load_lsdb

LIMIT = 250 * 1024   # lsdb allows 256 KiB a doc; the rest is headroom for the doc's own fields


def payload(slug: str, title: str, data: dict, presets: dict, modes: list[str], *, project: str = "", goal: str = "",
            source: str = "", opts: dict | None = None, stats: dict | None = None) -> dict:
    """The doc the viewer renders with the given rulesets. `data` is mountMap's {nodes, links, warnings}; `presets` maps
    mode name -> ruleset (engine/rules.js), `modes` is the order offered; `opts` are extra mountMap options (flow, reach)."""
    if not SLUG.fullmatch(slug):
        raise ValueError(f"slug {slug!r}: use letters, digits and hyphens")
    ids = [n["id"] for n in data["nodes"]]
    if len(set(ids)) != len(ids):
        raise ValueError("node ids must be unique")
    known = set(ids)
    for link in data["links"]:
        if link["source"] not in known or link["target"] not in known:
            raise ValueError(f"link {link['source']} -> {link['target']} names a node that is not in the graph")
    doc = {"slug": slug, "kind": "graph", "title": title, "project": project, "goal": goal, "source": source,
           "data": {"warnings": [], **data}, "presets": presets, "modes": modes, "opts": opts or {}, "refs": [], "counts": {},
           "stats": {"nodes": len(ids), "links": len(data["links"]), **(stats or {})},
           "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    size = len(json.dumps(doc, ensure_ascii=False).encode())
    if size > LIMIT:
        raise ValueError(f"{slug}: {size} bytes is over the {LIMIT} limit of one doc; trim the graph or store labels only")
    return doc


def store(url: str, doc: dict) -> dict:
    lsdb = load_lsdb()
    lsdb.set_doc(url, f"{COLLECTION}/{doc['slug']}", doc)
    lsdb.register(url, COLLECTION, DESCRIPTION)
    return doc
