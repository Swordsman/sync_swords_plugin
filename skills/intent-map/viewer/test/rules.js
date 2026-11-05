// Measures the engine's edge rules on a real map. usage: node rules.js SEED.json [SLUG]   (SEED from seed.py)
// Mounts the engine with test rulesets, runs the layout offline, and prints before/after numbers for each rule.
const { chromium } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const [seedFile, slug] = process.argv.slice(2);
const seed = JSON.parse(fs.readFileSync(seedFile, "utf8")), doc = seed.find(m => !slug || m.slug === slug);
const engine = path.resolve(__dirname, "../../engine");
const page = '<!doctype html><meta charset=utf-8><link rel=stylesheet href="/engine/map.css"><div id=app style="width:1200px;height:800px"></div>' +
  '<script type=module>import {mountMap} from "/engine/mount.js"; import {tick} from "/engine/rules.js"; import {PRESETS} from "/engine/presets.js"; window.lab = {mountMap, tick, PRESETS};</script>';
const server = http.createServer((req, res) => {
  const file = path.join(engine, "..", req.url.split("?")[0]);
  if (req.url === "/") { res.writeHead(200, { "content-type": "text/html" }); return res.end(page); }
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": file.endsWith(".css") ? "text/css" : "text/javascript" }); res.end(fs.readFileSync(file));
});

// runs inside the page: lay `rules` out for `ticks`, then measure
const measure = ({ data, rules, ticks, priorities, preset, ablate }) => {
  const app = document.getElementById("app"); app.replaceChildren();
  if (priorities) data.nodes.forEach((n, i) => { n.priority = priorities[i % priorities.length]; });
  const look = { id: "look", on: {}, do: [["shape", { as: "dot" }]] };
  if (ablate) rules = [];   // the shipped nodes preset without one of its new rules: ablate "fan" drops it, "springs" makes them flat
  const set = preset ? { ...lab.PRESETS.nodes, seed: true, rules: lab.PRESETS.nodes.rules.filter(r => ablate !== "fan" || r.id !== "fan").map(r => ablate !== "springs" || r.id !== "physics" ? r :
      { ...r, do: r.do.map(([n, q]) => n === "spring" ? [n, { ...q, length: 150, k: 0.004 }] : [n, q]) }).concat(rules) } : { live: true, seed: true, fit: "all", rules: [look, ...rules] };
  const h = lab.mountMap(app, data, { presets: { t: set }, modes: ["t"], storeKey: "lab" });
  h.cx.alive = false;
  for (let i = 0; i < ticks; i++) lab.tick(h.cx);
  const cx = h.cx, len = l => Math.hypot(l.t.x - l.s.x, l.t.y - l.s.y), mean = a => a.reduce((s, v) => s + v, 0) / a.length;
  const cv = a => Math.sqrt(mean(a.map(v => (v - mean(a)) ** 2))) / mean(a);
  const gaps = n => { const th = cx.neighbors.get(n).map(m => Math.atan2(m.y - n.y, m.x - n.x)).sort((p, q) => p - q);
    return th.map((t, i) => (i + 1 < th.length ? th[i + 1] - t : th[0] + 2 * Math.PI - t)); };
  const resolution = n => { const g = gaps(n); return Math.min(...g) / (2 * Math.PI / g.length); };   // 1 is even all round
  const hubs = cx.nodes.filter(n => cx.neighbors.get(n).length >= 3), top = hubs.reduce((b, n) => cx.neighbors.get(n).length > cx.neighbors.get(b).length ? n : b);
  const byPriority = {};
  for (const l of cx.links) (byPriority[Math.max(l.s.priority, l.t.priority)] ||= []).push(len(l));
  const kinds = {}; for (const l of cx.links) (kinds[l.kind] ||= []).push(len(l));
  return { warnings: cx.warnings.slice(cx.data.warnings.length), edgeCV: cv(cx.links.map(len)), meanLen: mean(cx.links.map(len)),
    hub: top.id, hubDegree: cx.neighbors.get(top).length, hubGapCV: cv(gaps(top)), hubMinGap: Math.min(...gaps(top)) * 180 / Math.PI,
    allGapCV: mean(hubs.map(n => cv(gaps(n)))), resolution: mean(hubs.map(resolution)), hubs: hubs.length, byPriority: Object.fromEntries(Object.entries(byPriority).map(([k, v]) => [k, mean(v)])),
    byKind: Object.fromEntries(Object.entries(kinds).map(([k, v]) => [k, mean(v)])),
    forward: mean(cx.links.map(l => (l.t.x > l.s.x ? 1 : 0))) };
};

const base = [["repel", { strength: 3800 }], ["spring", { length: 150, k: 0.004 }], ["gravity", { k: 0.0015 }]];
const rule = (id, ...doing) => ({ id, on: {}, do: doing });
const round = o => JSON.parse(JSON.stringify(o, (k, v) => typeof v === "number" ? Math.round(v * 1000) / 1000 : v));
const fmt = (n, v) => console.log(n.padEnd(34), JSON.stringify(round(v)));
const checks = [], expect = (name, ok) => checks.push(`${ok ? "ok  " : "FAIL"} ${name}`);
const ratio = (a, b) => Object.fromEntries(Object.keys(a).map(k => [k, a[k] / b[k]]));

(async () => {
  await new Promise(r => server.listen(0, r));
  const browser = await chromium.launch(), p = await browser.newPage(), errors = [];
  p.on("pageerror", e => errors.push(String(e))); p.on("console", m => m.type() === "error" && errors.push(m.text()));
  await p.goto(`http://localhost:${server.address().port}/`); await p.waitForFunction(() => window.lab);
  const run = (rules, extra = {}) => p.evaluate(measure, { data: structuredClone(doc.data), rules, ticks: 600, ...extra });
  const plain = await run([rule("physics", ...base)]), physics = (...more) => run([rule("physics", ...base), ...more]);

  // spread: angular resolution = smallest angle between a node's edges over the even share (1 is even all round), over nodes of degree 3+
  const fanned = await physics(rule("fan", ["spread", { k: 0.1 }]));
  fmt("angular resolution: plain / spread", { plain: plain.resolution, spread: fanned.resolution, plainCV: plain.allGapCV, spreadCV: fanned.allGapCV });
  expect("spread evens the angles around nodes", fanned.resolution > plain.resolution * 1.5 && fanned.allGapCV < plain.allGapCV);

  // field-bound params: a spring whose length follows priority, against the same priorities with a fixed spring
  const prio = [0, 1, 2, 3], follow = { scale: "priority", from: [0, 3], to: [200, 60] };
  const fixed = await run([rule("physics", base[0], base[1], base[2])], { priorities: prio });
  const bound = await run([rule("physics", base[0], ["spring", { length: follow, k: 0.004 }], base[2])], { priorities: prio });
  const r = ratio(bound.byPriority, fixed.byPriority);
  fmt("mean edge length by priority: fixed", fixed.byPriority); fmt("  follows priority", bound.byPriority); fmt("  ratio (1 = no effect)", r);
  expect("higher priority, shorter edges: the ratio falls 0 > 1 > 2 > 3", r[0] > r[1] && r[1] > r[2] && r[2] > r[3] && r[3] < r[0] * 0.85);

  // edge rules
  const balanced = await physics(rule("equal", ["balance", { k: 0.05 }]));
  fmt("edge length CV: plain / balance", { plain: plain.edgeCV, balanced: balanced.edgeCV });
  expect("balance-length cuts the spread of edge lengths", balanced.edgeCV < plain.edgeCV * 0.8);
  const picked = await physics({ id: "tight", on: {}, edges: { kind: "tests" }, do: [["spring", { length: 40, k: 0.02 }]] });
  fmt("mean length by kind: plain", plain.byKind); fmt("  tests links tightened", picked.byKind);
  expect("an edge selector by kind reaches only that kind", picked.byKind.tests < plain.byKind.tests * 0.7 && Math.abs(picked.byKind.meets - plain.byKind.meets) < plain.byKind.meets * 0.35);
  const ends = await physics({ id: "tight", on: {}, edges: { from: { kind: "need" } }, do: [["spring", { length: 40, k: 0.02 }]] });
  fmt("  links from a need tightened", ends.byKind);
  expect("an edge selector can test a field at one end", ends.byKind.meets < plain.byKind.meets * 0.7 && ends.byKind.tests > plain.byKind.tests * 0.65);
  const flowing = await physics(rule("flow", ["direction", { axis: "x", gap: 60, k: 0.02 }]));
  fmt("links pointing right: plain / direction", { plain: plain.forward, direction: flowing.forward });
  expect("direction orders the links", flowing.forward > Math.max(0.9, plain.forward));
  const warned = await physics(rule("bad", ["stack", { gap: { scale: "priority", from: [0, 3], to: [8, 30] } }]));
  expect("a param that cannot follow a field says so", warned.warnings.some(w => /gap cannot follow a field/.test(w)));

  // the shipped nodes preset, against itself with flat springs and no fan
  const shipped = await run([], { preset: true }), noFan = await run([], { preset: true, ablate: "fan" }), flat = await run([], { preset: true, ablate: "springs" });
  fmt("nodes preset: angular resolution", { noFan: noFan.resolution, shipped: shipped.resolution });
  expect("the nodes preset fans its edges", shipped.resolution > noFan.resolution * 1.5);
  if (Object.keys(shipped.byPriority).length > 1) { const q = ratio(shipped.byPriority, flat.byPriority); fmt("nodes preset: edge length against flat springs, by priority", q);
    const ks = Object.keys(q).map(Number).sort((a, b) => a - b); expect("the nodes preset shortens edges of higher priority", q[ks[ks.length - 1]] < q[ks[0]] * 0.9); }
  expect("no page errors", errors.length === 0);
  console.log(checks.join("\n")); await browser.close(); server.close();
  process.exit(checks.some(c => c.startsWith("FAIL")) ? 1 : 0);
})();
