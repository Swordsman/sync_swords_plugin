// The rule engine. A ruleset is {live, settle, top, fit, seed, sweep, rules}; a rule is {id, on, do: [[behavior, params], ...],
// enabled}. `on` selects nodes: {} is all; each key narrows it (kind/status/style/group/id take a value or a list; priority
// takes [op, number]). Live rulesets tick every frame; others settle for `settle` ticks and then hold still. `seed` spreads
// nodes on a spiral first (force layouts need distinct starting places). `sweep: {key, order}` runs the constraints one group
// at a time (Gauss-Seidel), so each group settles against its neighbours' latest positions.
import {CARD_W, R, matches, partition, rankIn} from "./util.js";
import {BEHAVIORS} from "./behaviors.js";

export const showWarnings = cx => { cx.warnEl.textContent = cx.warnings.join("  ·  "); };

function seed(cx) {   // phyllotaxis: deterministic, evenly spread
  cx.nodes.forEach((n, i) => { const a = i * 2.39996, r = 60 * Math.sqrt(i + 1); n.x = Math.cos(a) * r; n.y = Math.sin(a) * r; });
}

function activate(cx, next) {
  cx.active = [];
  for (const rule of next.rules) { if (rule.enabled === false) continue;
    for (const [name, params] of rule.do) { const b = BEHAVIORS[name];
      if (!b) { cx.warnings.push(`rule ${rule.id}: no behavior called "${name}"`); continue; }
      cx.active.push({cx, rule, name, b, p: {...b.defaults, ...params}, sel: cx.nodes.filter(n => matches(n, rule.on)), state: {}}); } }
}

function look(cx) {
  cx.active.filter(a => a.b.phase === "look").forEach(a => a.b.run(a));
  cx.nodes.forEach(n => { const card = n.shape === "card";
    n.card.hidden = !card; n.dot.style.display = card ? "none" : "";
    n.card.className = `card ${n.kind} s-${n.style} ${n.classes.join(" ")}`;
    n.dot.setAttribute("class", `dot ${n.kind} s-${n.style} ${n.classes.join(" ")}`);
    n.circle.setAttribute("r", n.r); n.label.setAttribute("dx", n.r + 6);
    n.w = card ? CARD_W : 2 * n.r; n.h = card ? n.cardH : 2 * n.r; });
}

export function applyRuleset(cx, next) {
  for (const a of cx.active) a.b.unmount?.(a);
  cx.decor.innerHTML = ""; cx.anchors = [];
  cx.nodes.forEach(n => { n.shape = "dot"; n.r = R; n.classes = []; n.rank = undefined; n.col = undefined; n.anchor = null; n.vx = n.vy = 0; });
  cx.warnings.length = cx.data.warnings.length;
  cx.ruleset = next;
  activate(cx, next);
  showWarnings(cx);
  if (next.seed) seed(cx);
  look(cx);
  cx.active.forEach(a => a.b.mount?.(a));
  cx.active.forEach(a => a.b.setup?.(a));
  cx.sweeps = next.sweep ? partition(cx.nodes, next.sweep.key).sort((p, q) => rankIn(next.sweep.order, p[0][next.sweep.key]) -
    rankIn(next.sweep.order, q[0][next.sweep.key])).map(part => new Set(part)) : null;
  cx.heat = 1;
  if (!next.live) { for (let i = 0; i < (next.settle ?? 1); i++) tick(cx);
    if (next.top !== undefined) { const lift = Math.min(...cx.nodes.map(n => n.y - n.h / 2)) - next.top;   // only ever pushed down: undo the drift
      cx.nodes.forEach(n => { n.y -= lift; }); } }
}

export function tick(cx) {
  for (const a of cx.active) if (a.b.phase === "force") a.b.run(a);
  if (cx.ruleset.live) { for (const n of cx.nodes) { if (!(cx.drag && cx.drag.target === n)) { n.x += n.vx * cx.heat; n.y += n.vy * cx.heat; } n.vx *= 0.6; n.vy *= 0.6; }
    cx.heat = Math.max(0.03, cx.heat * 0.985); }
  const constraints = cx.active.filter(a => a.b.phase === "constraint");
  if (!cx.sweeps) { constraints.forEach(a => a.b.run(a)); return; }
  for (const part of cx.sweeps) for (const a of constraints) {   // one group at a time, each seeing the last one's moves
    const sel = a.sel.filter(n => part.has(n)); if (sel.length) a.b.run({...a, sel}); }
}
