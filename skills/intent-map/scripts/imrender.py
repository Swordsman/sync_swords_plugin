"""Rendering: the mermaid column diagram, and the interactive force-graph page built from the same nodes."""
from __future__ import annotations

import html
import json
import pathlib
import re
import textwrap

from imcheck import met_needs, style_of, tested_by
from imparse import Node

COLORS = {  # fill, stroke: light enough for dark text, distinct without relying on hue alone (label says it too)
    "built": ("#d7f0d9", "#2e7d32"), "measured": ("#d6e6fb", "#1565c0"), "partial": ("#efe0f5", "#6a1b9a"),
    "design": ("#ececec", "#616161"), "untested": ("#ffe8cc", "#e65100"), "not-built": ("#fbd9d9", "#c62828"),
    "unmet": ("#fbd9d9", "#c62828"), "goal": ("#fff6c8", "#8d6e00"), "need": ("#e8eaf6", "#3949ab"),
    "test": ("#e0f2f1", "#00695c")}


ICONS = {"goal": "🎯", "need": "🧩", "test": "🧪", "unmet": "❗", "built": "✅", "measured": "📏", "partial": "🌓",
         "design": "📝", "untested": "❔", "not-built": "⛔"}


# ---------------------------------------------------------------- static: mermaid columns

def icon_of(node: Node, met: set[str]) -> str:
    return node.icon or ICONS[style_of(node, met)]


def label(node: Node, tests: dict[str, list[str]], met: set[str]) -> str:
    body = "<br/>".join(textwrap.wrap(node.text, 40)) or node.id
    extra = []
    if node.kind == "solution":
        extra.append(node.status.upper())
        if tests.get(node.id):
            extra.append("tested by " + ", ".join(tests[node.id]))
    if node.kind == "need" and node.id not in met:
        extra.append("UNMET")
    text = f"{icon_of(node, met)} {node.id} {body}" + ("<br/>" + "; ".join(extra) if extra else "")
    return text.replace('"', "#quot;")


def mermaid(title: str, nodes: list[Node]) -> str:
    tests, met = tested_by(nodes), met_needs(nodes)
    lines = ["---", f"title: {title}", "---", "flowchart LR"]
    lines += [f'  {n.id}["{label(n, tests, met)}"]' for n in nodes if n.kind == "goal"]   # first: anchors the left
    for kind, heading in (("need", "NEEDS"), ("solution", "SOLUTIONS"), ("test", "TESTS")):
        members = [n for n in nodes if n.kind == kind]
        if members:
            lines.append(f"  subgraph {heading}")
            lines += [f'    {n.id}["{label(n, tests, met)}"]' for n in members]
            lines.append("  end")
    for node in nodes:
        if node.kind in ("need", "solution"):
            lines += [f"  {target} --> {node.id}" for target in node.links]
    for node in nodes:        # tests sit right of the solution they test; no drawn edge, the label says it
        if node.kind == "test":
            lines.append(f"  {node.links[0]} ~~~ {node.id}")
    for style, (fill, stroke) in COLORS.items():
        lines.append(f"  classDef {style.replace('-', '')} fill:{fill},stroke:{stroke},color:#1a1a1a")
    for node in nodes:
        lines.append(f"  class {node.id} {style_of(node, met).replace('-', '')}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- interactive: force graph

PAGE = pathlib.Path(__file__).with_name("page.html")   # a plain file: no Python escapes inside the JS
ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"
ENGINE_ORDER = ("util", "graph", "light", "edges", "draw", "view", "tween", "drag", "attract", "behaviors", "rules", "presets", "controls", "mount")


def engine_script() -> str:
    """The engine's ES modules as one classic script: imports dropped, exports unwrapped, in dependency order."""
    lines = (line.removeprefix("export ") for name in ENGINE_ORDER
             for line in (ENGINE / f"{name}.js").read_text().splitlines() if not line.startswith("import "))
    return "\n".join(lines)


def page_data(nodes: list[Node], warnings: list[str]) -> dict:
    """Exactly what the page (and the viewer's engine) renders."""
    met, tests = met_needs(nodes), tested_by(nodes)
    direction = {"need": "serves", "solution": "meets", "test": "tests"}
    return {"nodes": [{"id": n.id, "kind": n.kind, "text": n.text, "status": n.status, "style": style_of(n, met),
                       "icon": icon_of(n, met), "testedBy": tests.get(n.id, []), "group": n.group or n.kind,
                       "priority": n.priority}
                      for n in nodes],
            "links": [{"source": target, "target": n.id, "kind": direction[n.kind]} if n.kind != "test" else
                      {"source": n.id, "target": target, "kind": "tests"} for n in nodes for target in n.links],
            "warnings": warnings}


def force_page(title: str, nodes: list[Node], warnings: list[str]) -> str:
    data = json.dumps(page_data(nodes, warnings), ensure_ascii=False).replace("</", "<\\/")   # no early </script>
    parts = {"TITLE": html.escape(title), "CSS": (ENGINE / "map.css").read_text(), "ENGINE": engine_script(), "DATA": data}
    return re.sub(r"__(TITLE|CSS|ENGINE|DATA)__", lambda m: parts[m.group(1)], PAGE.read_text())
