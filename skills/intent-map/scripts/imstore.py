"""Storing a map in an artifact db (via lsdb) as maps/<slug>, for the Intent Maps viewer to render."""
from __future__ import annotations

import datetime
import pathlib
import sys

from imcheck import check, status_counts
from imparse import SLUG, read_map
from imrender import page_data

COLLECTION = "maps"
DESCRIPTION = ("Intent maps, one doc per map: title, project, goal, sexpr (source), data (what the viewer renders), "
               "refs to other maps, counts by status. Written by intentmap.py --store. Docs with kind \"graph\" are generic graphs "
               "(data, presets, modes, stats) from other sources, written by imgraph.py.")


def load_lsdb():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
    import lsdb
    return lsdb


def payload(slug: str, source: str) -> dict:
    if not SLUG.fullmatch(slug):
        raise ValueError(f"slug {slug!r}: use letters, digits and hyphens (it is the file name without .sexpr)")
    parsed = read_map(source)
    warnings = check(parsed.nodes, parsed.refs)
    if any(ref.slug == slug for ref in parsed.refs):
        raise ValueError(f"{slug}: a map cannot refer to itself")
    return {"slug": slug, "title": parsed.title, "project": parsed.project or "",
            "goal": " / ".join(n.text for n in parsed.nodes if n.kind == "goal"), "sexpr": source,
            "data": page_data(parsed.nodes, warnings), "refs": [ref._asdict() for ref in parsed.refs],
            "counts": status_counts(parsed.nodes),
            "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}


def store(url: str, slug: str, source: str) -> dict:
    doc, lsdb = payload(slug, source), load_lsdb()
    lsdb.set_doc(url, f"{COLLECTION}/{slug}", doc)
    lsdb.register(url, COLLECTION, DESCRIPTION)
    return doc
