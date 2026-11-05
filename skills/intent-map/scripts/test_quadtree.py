"""The engine's pure modules (Barnes-Hut repulsion, template text) run under node against reference values."""
import json
import pathlib
import subprocess

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"


def node(code: str):
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def forces(theta: float) -> dict:
    return node(f"""
import {{repelBarnesHut}} from "{ENGINE}/quadtree.js";
const mk = () => {{ let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647; return Array.from({{length: 300}}, () => ({{x: rnd() * 900, y: rnd() * 700, vx: 0, vy: 0}})); }};
const st = Array.from({{length: 300}}, (_, i) => 2000 + (i % 7) * 600);
const exact = mk(), fast = mk();
for (let i = 0; i < 300; i++) for (let j = i + 1; j < 300; j++) {{ const p = exact[i], q = exact[j];
  let dx = q.x - p.x, dy = q.y - p.y; const d2 = dx * dx + dy * dy + 0.01, f = (st[i] + st[j]) / 2 / d2, d = Math.sqrt(d2);
  dx /= d; dy /= d; p.vx -= f * dx; p.vy -= f * dy; q.vx += f * dx; q.vy += f * dy; }}
repelBarnesHut(fast, st, {theta});
const mag = exact.map(p => Math.hypot(p.vx, p.vy)), err = exact.map((p, i) => Math.hypot(p.vx - fast[i].vx, p.vy - fast[i].vy));
console.log(JSON.stringify({{meanErr: err.reduce((s, v) => s + v, 0) / 300 / (mag.reduce((s, v) => s + v, 0) / 300)}}));""")


def test_theta_zero_is_exact():
    assert forces(0)["meanErr"] < 1e-9


def test_default_theta_stays_close():
    assert forces(0.8)["meanErr"] < 0.05


def test_coincident_nodes_do_not_hang():
    out = node(f"""import {{repelBarnesHut}} from "{ENGINE}/quadtree.js";
const ns = Array.from({{length: 40}}, () => ({{x: 5, y: 5, vx: 0, vy: 0}})); repelBarnesHut(ns, ns.map(() => 3800), 0.8);
console.log(JSON.stringify({{ok: ns.every(n => Number.isFinite(n.vx))}}));""")
    assert out["ok"]


def test_template_text():
    out = node(f"""import {{fill}} from "{ENGINE}/template.js";
console.log(JSON.stringify([fill("{{id}} {{cost|usd}}", {{id: "a", cost: 0.000158}}), fill("{{n|k}} tok", {{n: 12345}}), fill("{{n|k}} tok · {{cost|usd}}", {{n: 5}}), fill("{{h|pct}}", {{h: 0.934}})]));""")
    assert out == ["a $0.0002", "12k tok", "", "93%"]
