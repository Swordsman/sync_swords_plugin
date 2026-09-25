#!/usr/bin/env python3
"""Deterministic validator for a taskdagger design suite.

Checks the mechanical half of Phase 0: CHL companion integrity, node/section
correspondence, cross-document coverage, and version consistency. Everything it
reports is countable — which is exactly why it runs *before* the wash rather
than inside it. A wash is for what no check can enumerate; feeding it defects a
script can find both wastes the sweep and suppresses it where it was meant to
sharpen. See design_phase.md steps 4-5.

    python3 design_suite_check.py design/
    python3 design_suite_check.py design/ --version v0.4.2
    python3 design_suite_check.py design/ --stale "old-component-name" --stale "§9.2"

Exit 0 when clean, 1 when any defect is found, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

CATEGORIES = {
    "notation", "component", "mechanism", "invariant", "form", "protocol",
    "record", "strategy", "thesis", "constraint", "metric", "role", "model",
}

TAGS = {
    "root", "frozen", "evolvable", "safety", "primitive", "derived",
    "external", "internal", "durable", "volatile", "optional", "aspirational",
}

VERBS = {
    "defines", "enforces", "provides", "constrains", "enables",
    "gates", "dispatches", "serializes", "journals", "evolves",
    "contains", "maps", "compresses", "isolates", "surfaces",
    "mediates", "bounds", "tracks", "imports", "exports",
}

QUALIFIER_KEYWORDS = {"via", "for", "when", "unless", "from", "to", "within", "at"}

SYMBOL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NODE_ID_RE = re.compile(r"^\d+(?:\.\d+)*$")

#: The four prose documents a complete suite carries, in write order.
DOCUMENTS = ("mission", "spec", "scenarios", "walkthrough")

STRUCTURAL, REFERENCE, FORWARD = "structural", "reference", "forward"
EDGE_SYMBOLS = {"●": STRUCTURAL, "○": REFERENCE, "↗": FORWARD}


class Defect:
    """One finding. `kind` groups findings for the integrity report."""

    def __init__(self, kind: str, where: str, message: str) -> None:
        self.kind = kind
        self.where = where
        self.message = message

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


class Node:
    def __init__(self, nid, cat, term, gloss, tags, fields, line):
        self.id = nid
        self.cat = cat
        self.term = term
        self.gloss = gloss
        self.tags = tags
        self.fields = fields          # extra fields: corresponds-to, validates
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<node {self.id} {self.term}>"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _tokenize(text: str):
    """Yield s-expression tokens as (token, line_number)."""
    line = 1
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
        elif ch.isspace():
            i += 1
        elif ch == ";":
            while i < n and text[i] != "\n":
                i += 1
        elif ch in "()":
            yield ch, line
            i += 1
        elif ch == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                if text[j] == "\n":
                    line += 1
                buf.append(text[j])
                j += 1
            yield ("str", "".join(buf)), line
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '();"':
                j += 1
            yield text[i:j], line
            i = j


def _parse_sexprs(text: str):
    """Parse every top-level s-expression, tolerating prose between them."""
    stack, out = [], []
    for tok, line in _tokenize(text):
        if tok == "(":
            stack.append(([], line))
        elif tok == ")":
            if not stack:
                continue
            items, start = stack.pop()
            if stack:
                stack[-1][0].append(items)
            else:
                out.append((items, start))
        elif stack:
            stack[-1][0].append(tok)
    return out


def parse_nodes(text: str, defects: list, where: str):
    """Extract (node ...) forms. Malformed nodes are reported, not raised."""
    nodes = []
    for items, line in _parse_sexprs(text):
        if not items or items[0] != "node":
            continue
        if len(items) < 2 or not isinstance(items[1], str):
            defects.append(Defect("malformed", f"{where}:{line}", "node has no ID"))
            continue
        nid = items[1]
        fields, i = {}, 2
        while i < len(items):
            key = items[i]
            if not isinstance(key, str) or not key.startswith(":"):
                defects.append(
                    Defect("malformed", f"{where}:{line}",
                           f"node {nid}: expected a :field, found {key!r}"))
                break
            if i + 1 >= len(items):
                defects.append(
                    Defect("malformed", f"{where}:{line}",
                           f"node {nid}: {key} has no value"))
                break
            fields[key[1:]] = items[i + 1]
            i += 2

        gloss = fields.get("gloss")
        if isinstance(gloss, tuple) and gloss and gloss[0] == "str":
            gloss = gloss[1]
        tags = fields.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        extra = {k: v for k, v in fields.items()
                 if k not in {"cat", "term", "gloss", "tags"}}
        nodes.append(Node(nid, fields.get("cat"), fields.get("term"),
                          gloss, list(tags), extra, line))
    return nodes


_EDGE_LIST_RE = re.compile(r"^\s*;;\s*(\d+(?:\.\d+)*)\s*←\s*(.+?)\s*$")


def parse_edges(text: str, defects: list, where: str):
    """Collect dependency edges from edge lists and adjacency matrices.

    Returns a list of (source, target, kind, line) where `source` depends on
    `target`. Both forms are supported; edge lists are the robust one and the
    doctrine prefers them once a section stops fitting a readable matrix.
    """
    edges = []
    lines = text.splitlines()

    for lineno, raw in enumerate(lines, 1):
        m = _EDGE_LIST_RE.match(raw)
        if not m:
            continue
        src, rest = m.group(1), m.group(2)
        for chunk in rest.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            kind = STRUCTURAL
            for sym, k in EDGE_SYMBOLS.items():
                if chunk.startswith(sym):
                    kind = k
                    chunk = chunk[len(sym):].strip()
                    break
            if not NODE_ID_RE.match(chunk):
                defects.append(
                    Defect("malformed", f"{where}:{lineno}",
                           f"edge list target {chunk!r} is not a node ID"))
                continue
            edges.append((src, chunk, kind, lineno))

    edges.extend(_parse_matrices(lines, defects, where))
    return edges


def _label_columns(raw: str):
    """Header labels and the column each starts at."""
    return [(m.group(0), m.start()) for m in
            re.finditer(r"§?\d+(?:\.\d+)*|[A-Z]", raw)]


def _parse_matrices(lines, defects, where):
    """Read `;;` adjacency matrices by aligning cells under header columns."""
    edges = []
    header = None
    for lineno, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped.startswith(";;"):
            header = None
            continue
        body = raw[raw.index(";;") + 2:]
        if not body.strip():
            continue

        cells = [(m.group(0), m.start()) for m in
                 re.finditer("[" + "".join(EDGE_SYMBOLS) + "]", body)]
        labels = _label_columns(body)

        if not cells and labels and len(labels) >= 2 and "←" not in body:
            # A row of bare labels with no dependency marks: a header.
            header = labels
            continue

        if not cells or header is None:
            continue

        row_label = labels[0][0] if labels else None
        if row_label is None:
            continue
        row_id = row_label.lstrip("§")

        for sym, col in cells:
            target = _nearest_label(header, col)
            if target is None:
                defects.append(
                    Defect("malformed", f"{where}:{lineno}",
                           f"matrix cell {sym!r} at column {col} matches no header column"))
                continue
            tid = target.lstrip("§")
            if tid == row_id:
                continue
            edges.append((row_id, tid, EDGE_SYMBOLS[sym], lineno))
    return edges


def _nearest_label(header, col, tolerance=2):
    best, best_dist = None, None
    for label, start in header:
        dist = abs(start - col)
        if dist <= tolerance and (best_dist is None or dist < best_dist):
            best, best_dist = label, dist
    return best


def parse_sections(text: str):
    """Section numbers from ATX headings, in document order."""
    out = []
    for raw in text.splitlines():
        m = re.match(r"^#{1,6}\s+§?(\d+(?:\.\d+)*)\s*[.—:-]?\s+\S", raw)
        if m:
            out.append(m.group(1))
    return out


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_gloss(gloss):
    """Return None when the gloss parses, else why it doesn't."""
    if not isinstance(gloss, str) or not gloss.strip():
        return "missing gloss"
    tokens = gloss.split()
    if tokens[0] not in VERBS:
        return f"{tokens[0]!r} is not a VERB"
    if len(tokens) < 2:
        return "gloss has no OBJECT"
    if not SYMBOL_RE.match(tokens[1]):
        return f"OBJECT {tokens[1]!r} is not a hyphenated lowercase symbol"
    i = 2
    while i < len(tokens):
        kw = tokens[i]
        if kw not in QUALIFIER_KEYWORDS:
            return (f"{kw!r} is not a QUALIFIER keyword "
                    f"({'/'.join(sorted(QUALIFIER_KEYWORDS))})")
        if i + 1 >= len(tokens):
            return f"qualifier {kw!r} has no operand"
        if not SYMBOL_RE.match(tokens[i + 1]):
            return f"qualifier operand {tokens[i + 1]!r} is not a hyphenated lowercase symbol"
        i += 2
    return None


def find_cycles(adjacency):
    """Every elementary cycle reachable by DFS, as node-ID paths."""
    cycles, path, on_path, seen = [], [], set(), set()

    def walk(node):
        path.append(node)
        on_path.add(node)
        for nxt in adjacency.get(node, ()):
            if nxt in on_path:
                cycles.append(path[path.index(nxt):] + [nxt])
            elif nxt not in seen:
                walk(nxt)
        on_path.discard(node)
        path.pop()
        seen.add(node)

    for node in list(adjacency):
        if node not in seen:
            walk(node)
    return cycles


def document_order(nodes):
    return {n.id: i for i, n in enumerate(nodes)}


class Companion:
    def __init__(self, name, path, defects):
        self.name = name
        self.path = path
        text = path.read_text(encoding="utf-8")
        self.text = text
        where = path.name
        self.nodes = parse_nodes(text, defects, where)
        self.edges = parse_edges(text, defects, where)
        self.by_id = {}
        for node in self.nodes:
            if node.id in self.by_id:
                defects.append(Defect("malformed", f"{where}:{node.line}",
                                      f"duplicate node ID {node.id}"))
            else:
                self.by_id[node.id] = node


def check_companion(comp, defects):
    where = comp.path.name
    order = document_order(comp.nodes)
    terms = defaultdict(list)

    for node in comp.nodes:
        at = f"{where}:{node.line}"
        if not NODE_ID_RE.match(node.id):
            defects.append(Defect("malformed", at, f"node ID {node.id!r} is not dotted-numeric"))
        if node.cat not in CATEGORIES:
            defects.append(Defect("grammar", at, f"node {node.id}: :cat {node.cat!r} is not a category"))
        if not isinstance(node.term, str) or not SYMBOL_RE.match(node.term or ""):
            defects.append(Defect("grammar", at, f"node {node.id}: :term {node.term!r} is not a hyphenated lowercase symbol"))
        else:
            terms[node.term].append(node.id)
        for tag in node.tags:
            if tag not in TAGS:
                defects.append(Defect("grammar", at, f"node {node.id}: tag {tag!r} is not in the tag vocabulary"))
        problem = check_gloss(node.gloss)
        if problem:
            defects.append(Defect("grammar", at, f"node {node.id}: {problem}"))

    for term, ids in sorted(terms.items()):
        if len(ids) > 1:
            defects.append(Defect("grammar", where,
                                  f"term {term!r} is defined by more than one node: {', '.join(ids)}"))

    seen_edges = {}
    adjacency = defaultdict(set)
    incoming = defaultdict(set)
    for src, dst, kind, line in comp.edges:
        at = f"{where}:{line}"
        if src not in comp.by_id:
            defects.append(Defect("unsafe", at, f"edge source {src} is not a defined node"))
            continue
        if dst not in comp.by_id:
            defects.append(Defect("unsafe", at, f"node {src} depends on {dst}, which no node defines"))
            continue
        if (src, dst) in seen_edges:
            defects.append(Defect("duplicate-edge", at,
                                  f"edge {src} ← {dst} is stated twice "
                                  f"(also at line {seen_edges[(src, dst)]}); state each edge exactly once"))
            continue
        seen_edges[(src, dst)] = line
        adjacency[src].add(dst)
        incoming[dst].add(src)
        if order.get(dst, -1) > order.get(src, -1) and kind != FORWARD:
            defects.append(Defect("unmarked-forward", at,
                                  f"node {src} depends on later node {dst} without a ↗ forward mark"))

    for node in comp.nodes:
        if "root" in node.tags:
            continue
        if not incoming.get(node.id):
            defects.append(Defect("orphan", f"{where}:{node.line}",
                                  f"node {node.id} ({node.term}) is defined but nothing depends on it"))

    for cycle in find_cycles({k: sorted(v) for k, v in adjacency.items()}):
        defects.append(Defect("cycle", where, "circular dependency: " + " → ".join(cycle)))

    return {
        "nodes": len(comp.nodes),
        "edges": len(seen_edges),
        "categories": len({n.cat for n in comp.nodes} & CATEGORIES),
        "tags": len({t for n in comp.nodes for t in n.tags} & TAGS),
        "forward": sum(1 for _, _, k, _ in comp.edges if k == FORWARD),
    }


def check_correspondence(name, comp, source_path, defects):
    """Node IDs must match the source document's section numbering."""
    sections = parse_sections(source_path.read_text(encoding="utf-8"))
    section_set = set(sections)
    node_ids = set(comp.by_id)
    for missing in sorted(section_set - node_ids, key=_id_key):
        defects.append(Defect("coverage", source_path.name,
                              f"§{missing} has no node in {comp.path.name}"))
    for phantom in sorted(node_ids - section_set, key=_id_key):
        defects.append(Defect("coverage", comp.path.name,
                              f"node {phantom} matches no section in {source_path.name}"))


def _id_key(nid):
    return [int(part) for part in nid.split(".")]


def check_walkthrough(companions, defects):
    walk = companions.get("walkthrough")
    spec = companions.get("spec")
    if not walk or not spec:
        return
    covered = set()
    for node in walk.nodes:
        at = f"{walk.path.name}:{node.line}"
        target = node.fields.get("corresponds-to")
        if target is None:
            defects.append(Defect("coverage", at,
                                  f"walkthrough node {node.id} has no :corresponds-to"))
            continue
        if isinstance(target, tuple) and target and target[0] == "str":
            target = target[1]
        target = str(target).lstrip("§")
        if target not in spec.by_id:
            defects.append(Defect("coverage", at,
                                  f"walkthrough node {node.id} corresponds to §{target}, "
                                  f"which is not a spec node"))
        else:
            covered.add(target)
        if "validates" not in node.fields:
            defects.append(Defect("coverage", at,
                                  f"walkthrough node {node.id} has no :validates"))
    for missing in sorted(set(spec.by_id) - covered, key=_id_key):
        node = spec.by_id[missing]
        defects.append(Defect("coverage", walk.path.name,
                              f"spec §{missing} ({node.term}) is not covered by the walkthrough"))


def check_scenarios(companions, defects):
    """Scenarios introduce no mechanisms: their terms come from the spec."""
    scen = companions.get("scenarios")
    spec = companions.get("spec")
    if not scen or not spec:
        return
    spec_terms = {n.term for n in spec.nodes}
    own_terms = {n.term for n in scen.nodes}
    for node in scen.nodes:
        if node.cat in {"mechanism", "protocol", "form", "component", "record"} \
                and node.term not in spec_terms and node.term in own_terms:
            defects.append(Defect("scope", f"{scen.path.name}:{node.line}",
                                  f"scenario node {node.id} introduces {node.cat} "
                                  f"{node.term!r}, which the spec does not define"))


def check_stale(paths, terms, defects):
    for path in paths:
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for term in terms:
                if term in raw:
                    defects.append(Defect("stale", f"{path.name}:{lineno}",
                                          f"stale text {term!r}: {raw.strip()[:80]}"))


# --------------------------------------------------------------------------
# Discovery and driver
# --------------------------------------------------------------------------

_VERSIONED_RE = re.compile(r"^(?P<stem>.+?)_v(?P<version>[0-9][0-9A-Za-z.]*)\.md$")


def discover(directory: Path, version=None):
    """Map document/companion names to paths, and report the version in use."""
    found, versions = {}, set()
    for path in sorted(directory.glob("*.md")):
        m = _VERSIONED_RE.match(path.name)
        if not m:
            continue
        stem, ver = m.group("stem"), m.group("version")
        if version and ver != version:
            continue
        versions.add(ver)
        found[stem] = path
    return found, versions


def run(directory: Path, version=None, stale=()):
    defects = []
    found, versions = discover(directory, version)

    if not found:
        defects.append(Defect("missing", str(directory),
                              "no versioned suite documents found "
                              "(expected <name>_v<version>.md)"))
        return defects, {}

    if len(versions) > 1:
        defects.append(Defect("version", str(directory),
                              "documents carry different versions: "
                              + ", ".join(sorted(versions))
                              + " — every document in a suite shares one version"))

    companions, summaries = {}, {}
    for name in DOCUMENTS:
        source = found.get(name)
        companion = found.get(f"{name}_chl")
        if source is None:
            defects.append(Defect("missing", str(directory),
                                  f"the suite has no {name} document"))
        if companion is None:
            defects.append(Defect("missing", str(directory),
                                  f"the suite has no CHL companion for {name}"))
        if source is None or companion is None:
            continue
        comp = Companion(name, companion, defects)
        companions[name] = comp
        summaries[name] = check_companion(comp, defects)
        check_correspondence(name, comp, source, defects)

    check_walkthrough(companions, defects)
    check_scenarios(companions, defects)
    if stale:
        check_stale(sorted(found.values()), stale, defects)

    return defects, summaries


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate a taskdagger design suite before the Phase 0 wash.")
    ap.add_argument("directory", nargs="?", default="design",
                    help="the suite directory (default: design)")
    ap.add_argument("--version", help="only consider documents at this version, e.g. v0.4.2")
    ap.add_argument("--stale", action="append", default=[], metavar="TEXT",
                    help="fail if this text appears anywhere in the suite; repeatable")
    ap.add_argument("--quiet", action="store_true", help="print the summary only")
    args = ap.parse_args(argv)

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"design_suite_check: {directory} is not a directory", file=sys.stderr)
        return 2

    defects, summaries = run(directory, args.version, args.stale)

    if not args.quiet:
        for name in DOCUMENTS:
            s = summaries.get(name)
            if not s:
                continue
            print(f"{name:12s} {s['nodes']:4d} nodes  {s['edges']:4d} edges  "
                  f"{s['forward']:2d} forward  "
                  f"categories {s['categories']}/{len(CATEGORIES)}  "
                  f"tags {s['tags']}/{len(TAGS)}")
        if summaries:
            print()

    if defects:
        by_kind = defaultdict(list)
        for d in defects:
            by_kind[d.kind].append(d)
        for kind in sorted(by_kind):
            print(f"{kind} ({len(by_kind[kind])})")
            for d in by_kind[kind]:
                print(f"  {d}")
        print(f"\ndesign_suite_check: {len(defects)} defect(s). "
              f"Fix these before the wash — they are not what a wash is for.")
        return 1

    print("design_suite_check: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
