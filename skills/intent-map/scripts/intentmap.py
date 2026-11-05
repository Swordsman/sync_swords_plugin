#!/usr/bin/env python3
"""Intent maps from one s-expression: a static column diagram (mermaid -> PNG) and an interactive force graph (one
self-contained HTML file, no libraries). Checks the map's contract before drawing anything.

usage: intentmap.py MAP.sexpr [--out DIR] [--no-png]

  (intent-map "title"
    (goal G "what Joe wants")
    (need N1 "a need" :serves G)
    (solution S1 "how it is met" :meets N1 :status built)
    (test T1 "what would show it works" :tests (S1)))

Statuses: built measured partial design untested not-built. Contract: every need serves a known goal; every
solution meets known needs; every test tests known solutions; ids are unique. A need with no solution is drawn as
UNMET and reported, since a goal with an unmet need isn't mapped to an implementation yet.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import shutil
import subprocess
import sys
import textwrap
from typing import NamedTuple

KINDS = ("goal", "need", "solution", "test")
STATUSES = ("built", "measured", "partial", "design", "untested", "not-built")
COLORS = {  # fill, stroke: light enough for dark text, distinct without relying on hue alone (label says it too)
    "built": ("#d7f0d9", "#2e7d32"), "measured": ("#d6e6fb", "#1565c0"), "partial": ("#efe0f5", "#6a1b9a"),
    "design": ("#ececec", "#616161"), "untested": ("#ffe8cc", "#e65100"), "not-built": ("#fbd9d9", "#c62828"),
    "unmet": ("#fbd9d9", "#c62828"), "goal": ("#fff6c8", "#8d6e00"), "need": ("#e8eaf6", "#3949ab"),
    "test": ("#e0f2f1", "#00695c")}


class Node(NamedTuple):
    kind: str
    id: str
    text: str
    links: tuple[str, ...]      # serves / meets / tests targets
    status: str | None


# ---------------------------------------------------------------- reading

def tokens(source: str):
    """Parens, quoted strings (with \\" escapes), ;-comments and bare atoms."""
    position = 0
    while position < len(source):
        char = source[position]
        if char.isspace():
            position += 1
        elif char == ";":
            end = source.find("\n", position)
            position = len(source) if end == -1 else end
        elif char in "()":
            yield char
            position += 1
        elif char == '"':
            end, parts = position + 1, []
            while end < len(source) and source[end] != '"':
                if source[end] == "\\" and end + 1 < len(source):
                    end += 1
                parts.append(source[end])
                end += 1
            if end >= len(source):
                raise ValueError(f"unterminated string at offset {position}")
            yield ("str", "".join(parts))
            position = end + 1
        else:
            end = position
            while end < len(source) and not source[end].isspace() and source[end] not in '()";':
                end += 1
            yield source[position:end]
            position = end


def parse(source: str):
    stack: list[list] = [[]]
    for token in tokens(source):
        if token == "(":
            stack.append([])
        elif token == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')'")
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(token)
    if len(stack) != 1:
        raise ValueError("unbalanced '(': missing ')'")
    if len(stack[0]) != 1 or not isinstance(stack[0][0], list) or stack[0][0][:1] != ["intent-map"]:
        raise ValueError("the file must hold exactly one (intent-map \"title\" ...) form")
    return stack[0][0]


def text_of(value) -> str:
    if isinstance(value, tuple) and value[0] == "str":
        return value[1]
    raise ValueError(f"expected a quoted string, got {value!r}")


def read(source: str) -> tuple[str, list[Node]]:
    form = parse(source)
    title, nodes = text_of(form[1]), []
    link_key = {"need": ":serves", "solution": ":meets", "test": ":tests"}
    for item in form[2:]:
        if not isinstance(item, list) or not item or item[0] not in KINDS:
            raise ValueError(f"unknown form {item!r}: expected one of {KINDS}")
        kind, node_id, text, rest = item[0], item[1], text_of(item[2]), item[3:]
        options = dict(zip(rest[::2], rest[1::2]))
        allowed = {":status", link_key.get(kind)} - {None}
        if len(rest) % 2 or set(options) - allowed:
            raise ValueError(f"{node_id}: bad options {rest!r}")
        target = options.get(link_key.get(kind))
        links = tuple(target) if isinstance(target, list) else (target,) if target else ()
        nodes.append(Node(kind, node_id, text, links, options.get(":status")))
    return title, nodes


# ---------------------------------------------------------------- contract

def check(nodes: list[Node]) -> list[str]:
    """Hard errors raise; returns warnings (unmet needs)."""
    by_id: dict[str, Node] = {}
    for node in nodes:
        if node.id in by_id:
            raise ValueError(f"duplicate id {node.id}")
        by_id[node.id] = node
    wants = {"need": "goal", "solution": "need", "test": "solution"}
    for node in nodes:
        if node.kind == "goal":
            continue
        if not node.links:
            raise ValueError(f"{node.kind} {node.id} links to nothing: every {node.kind} needs a {wants[node.kind]}")
        for target in node.links:
            if target not in by_id or by_id[target].kind != wants[node.kind]:
                raise ValueError(f"{node.id} -> {target}: expected an existing {wants[node.kind]}")
        if node.kind == "solution" and node.status not in STATUSES:
            raise ValueError(f"solution {node.id}: :status must be one of {STATUSES}")
    met = {target for node in nodes if node.kind == "solution" for target in node.links}
    warnings = [f"UNMET: need {node.id} has no solution ({node.text})" for node in nodes
                if node.kind == "need" and node.id not in met]
    served = {target for node in nodes if node.kind == "need" for target in node.links}
    warnings += [f"goal {node.id} has no needs" for node in nodes if node.kind == "goal" and node.id not in served]
    return warnings


def tested_by(nodes: list[Node]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in nodes:
        if node.kind == "test":
            for target in node.links:
                result.setdefault(target, []).append(node.id)
    return result


def style_of(node: Node, met: set[str]) -> str:
    if node.kind == "solution":
        return node.status
    if node.kind == "need" and node.id not in met:
        return "unmet"
    return node.kind


# ---------------------------------------------------------------- static: mermaid columns

def label(node: Node, tests: dict[str, list[str]], met: set[str]) -> str:
    body = "<br/>".join(textwrap.wrap(node.text, 40)) or node.id
    extra = []
    if node.kind == "solution":
        extra.append(node.status.upper())
        if tests.get(node.id):
            extra.append("tested by " + ", ".join(tests[node.id]))
    if node.kind == "need" and node.id not in met:
        extra.append("UNMET")
    text = f"{node.id} {body}" + ("<br/>" + "; ".join(extra) if extra else "")
    return text.replace('"', "#quot;")


def mermaid(title: str, nodes: list[Node]) -> str:
    tests, met = tested_by(nodes), {t for n in nodes if n.kind == "solution" for t in n.links}
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

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#fafafa;--fg:#1a1a1a;--muted:#666;--edge:#9e9e9e;--panel:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e8e8e8;--muted:#aaa;--edge:#5f5f5f;--panel:#222}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
header{padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0}label{color:var(--muted)}svg{width:100vw;height:calc(100vh - 92px);display:block}
#info{position:fixed;right:16px;bottom:16px;max-width:min(420px,calc(100vw - 32px));background:var(--panel);
border:1px solid var(--edge);border-radius:8px;padding:10px 12px;display:none;white-space:pre-wrap}
#warn{color:#c62828;padding:0 16px}text{pointer-events:none;font-size:11px}
</style></head><body>
<header><h1>__TITLE__</h1><label><input type="checkbox" id="columns" checked> keep columns</label>
<label><input type="checkbox" id="labels" checked> labels</label><span id="legend"></span></header>
<div id="warn"></div><svg id="graph"></svg><div id="info"></div>
<script>
const DATA = __DATA__;
const svg = document.getElementById("graph"), NS = "http://www.w3.org/2000/svg";
const column = {goal: 0, need: 1, solution: 2, test: 3};
const nodes = DATA.nodes.map((n, i) => ({...n, x: 0, y: 0, vx: 0, vy: 0, index: i}));
const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
const links = DATA.links.map(l => ({...l, s: byId[l.source], t: byId[l.target]}));
document.getElementById("warn").textContent = DATA.warnings.join("  ·  ");
document.getElementById("legend").innerHTML = Object.entries(DATA.colors).map(([k, [f, s]]) =>
  `<span style="display:inline-block;width:10px;height:10px;background:${f};border:2px solid ${s};margin:0 3px 0 8px"></span>${k}`).join("");
function size() { const r = svg.getBoundingClientRect(); return [r.width, r.height]; }
let [W, H] = size();
const ranks = {};   // start evenly spaced down each column, in file order, so edges begin mostly uncrossed
nodes.forEach(n => { n.rank = ranks[n.kind] = (ranks[n.kind] ?? -1) + 1; });
nodes.forEach(n => { const count = ranks[n.kind] + 1;
  n.x = W * (0.06 + 0.25 * column[n.kind]); n.y = H * (count === 1 ? 0.5 : 0.06 + 0.88 * n.rank / (count - 1)); });
const defs = document.createElementNS(NS, "defs");
defs.innerHTML = '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#9e9e9e"/></marker>';
svg.appendChild(defs);
const edgeEls = links.map(l => { const e = document.createElementNS(NS, "line");
  e.style.stroke = "var(--edge)"; e.setAttribute("stroke-width", "1.5");
  if (l.kind === "tests") e.setAttribute("stroke-dasharray", "4 3");
  e.setAttribute("marker-end", "url(#arrow)"); svg.appendChild(e); return e; });
const nodeEls = nodes.map(n => { const g = document.createElementNS(NS, "g");
  const c = document.createElementNS(NS, "circle"); const [fill, stroke] = DATA.colors[n.style];
  c.setAttribute("r", n.kind === "goal" ? 16 : 11); c.setAttribute("fill", fill);
  c.setAttribute("stroke", stroke); c.setAttribute("stroke-width", "2.5");
  const t = document.createElementNS(NS, "text"); t.setAttribute("dx", 15); t.setAttribute("dy", 4);
  t.style.fill = "var(--fg)"; t.textContent = n.id + "  " + (n.text.length > 42 ? n.text.slice(0, 40) + "…" : n.text);
  g.append(c, t); g.style.cursor = "grab"; svg.appendChild(g); g.label = t;
  g.addEventListener("pointerdown", ev => { drag = n; g.setPointerCapture(ev.pointerId); show(n); });
  g.addEventListener("pointerenter", () => show(n)); return g; });
const info = document.getElementById("info");
function show(n) { info.style.display = "block";
  info.textContent = `${n.id} (${n.kind}${n.status ? ", " + n.status : ""}${n.style === "unmet" ? ", UNMET" : ""})\n\n${n.text}`; }
let drag = null, heat = 1;
svg.addEventListener("pointermove", ev => { if (!drag) return; const r = svg.getBoundingClientRect();
  drag.x = ev.clientX - r.left; drag.y = ev.clientY - r.top; drag.vx = drag.vy = 0; heat = Math.max(heat, .3); });
svg.addEventListener("pointerup", () => { drag = null; });
document.getElementById("columns").onchange = () => { heat = 1; };
document.getElementById("labels").onchange = ev => nodeEls.forEach(g => g.label.style.display = ev.target.checked ? "" : "none");
addEventListener("resize", () => { [W, H] = size(); heat = 1; });
function tick() {
  const keep = document.getElementById("columns").checked;
  for (const a of nodes) for (const b of nodes) { if (a.index >= b.index) continue;
    let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy + 0.01, f = 5200 / d2;
    const d = Math.sqrt(d2); dx /= d; dy /= d; a.vx -= f * dx; a.vy -= f * dy; b.vx += f * dx; b.vy += f * dy; }
  for (const l of links) { let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.hypot(dx, dy) || 1, f = (d - 180) * 0.006;
    dx /= d; dy /= d; l.s.vx += f * dx; l.s.vy += f * dy; l.t.vx -= f * dx; l.t.vy -= f * dy; }
  for (const n of nodes) {
    if (keep) n.vx += (W * (0.06 + 0.25 * column[n.kind]) - n.x) * 0.15;
    if (n !== drag) { n.x += n.vx * heat; n.y += n.vy * heat; }
    n.vx *= 0.6; n.vy *= 0.6;
    n.x = Math.max(20, Math.min(W - 20, n.x)); n.y = Math.max(20, Math.min(H - 20, n.y)); }
  heat = Math.max(0.02, heat * 0.985);
  links.forEach((l, i) => { const e = edgeEls[i], dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.hypot(dx, dy) || 1,
    r = l.t.kind === "goal" ? 18 : 13;
    e.setAttribute("x1", l.s.x); e.setAttribute("y1", l.s.y);
    e.setAttribute("x2", l.t.x - dx / d * r); e.setAttribute("y2", l.t.y - dy / d * r); });
  nodes.forEach((n, i) => nodeEls[i].setAttribute("transform", `translate(${n.x},${n.y})`));
  requestAnimationFrame(tick); }
tick();
</script></body></html>
"""


def force_page(title: str, nodes: list[Node], warnings: list[str]) -> str:
    met = {t for n in nodes if n.kind == "solution" for t in n.links}
    direction = {"need": "serves", "solution": "meets", "test": "tests"}
    data = {"nodes": [{"id": n.id, "kind": n.kind, "text": n.text, "status": n.status, "style": style_of(n, met)}
                      for n in nodes],
            "links": [{"source": target, "target": n.id, "kind": direction[n.kind]} if n.kind != "test" else
                      {"source": n.id, "target": target, "kind": "tests"} for n in nodes for target in n.links],
            "colors": COLORS, "warnings": warnings}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")   # no early </script>
    return PAGE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload)


# ---------------------------------------------------------------- run

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("map", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--no-png", action="store_true")
    args = parser.parse_args()
    title, nodes = read(args.map.read_text())
    warnings = check(nodes)
    out = args.out or args.map.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = args.map.stem
    (out / f"{stem}.mmd").write_text(mermaid(title, nodes))
    (out / f"{stem}.html").write_text(force_page(title, nodes, warnings))
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


if __name__ == "__main__":
    main()
