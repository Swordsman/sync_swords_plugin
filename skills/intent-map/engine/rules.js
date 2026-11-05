// The rule engine. A ruleset is {live, settle, top, fit, seed, sweep, rules}; a rule is {id, on, edges?, do: [[behavior, params], ...],
// enabled}. `on` selects nodes: {} is all; each key narrows it (kind/status/style/group/id take a value or a list; priority
// takes [op, number]). `edges` narrows the links between selected nodes: {kind, from, to, end} (from/to/end are node selectors for
// the link's source, target, either end). A param that is a number may instead follow a field: {scale, from: [lo, hi], to: [a, b]}.
// Live rulesets tick every frame; others settle for `settle` ticks and then hold still (a live one settles that long
// before a view switch travels to it). `seed` spreads
// nodes on a spiral first (force layouts need distinct starting places). `sweep: {key, order}` runs the constraints one group
// at a time (Gauss-Seidel), so each group settles against its neighbours' latest positions.
import {CARD_W, R, matches, linkMatches, partition, rankIn} from "./util.js";
import {isBound} from "./params.js";
import {showShape} from "./draw.js";
import {BEHAVIORS} from "./behaviors.js";
import {renderTemplates} from "./template.js";

export const HEAT_FLOOR = 0.03;   // a live layout cools to this and then sleeps until something heats it (a drag, a new rule set)
export const showWarnings = cx => { cx.warnEl.textContent = cx.warnings.join("  ·  "); };

function seed(cx) {   // phyllotaxis: deterministic, evenly spread
  cx.nodes.forEach((n, i) => { const a = i * 2.39996, r = 60 * Math.sqrt(i + 1); n.x = Math.cos(a) * r; n.y = Math.sin(a) * r; });
}

function activate(cx, next) {
  cx.active = [];
  for (const rule of next.rules) { if (rule.enabled === false) continue;
    const sel = cx.nodes.filter(n => matches(n, rule.on)), inside = new Set(sel);
    const links = cx.links.filter(l => inside.has(l.s) && inside.has(l.t) && linkMatches(l, rule.edges));
    for (const [name, params] of rule.do) { const b = BEHAVIORS[name];
      if (!b) { cx.warnings.push(`rule ${rule.id}: no behavior called "${name}"`); continue; }
      const p = {...b.defaults, ...params};
      for (const [key, v] of Object.entries(p)) if (isBound(v) && !b.bound?.includes(key)) {
        cx.warnings.push(`rule ${rule.id}: ${name} ${key} cannot follow a field`); p[key] = v.to[0]; }
      cx.active.push({cx, rule, name, b, p, sel, links, state: {}}); } }
}

function look(cx) {
  cx.active.filter(a => a.b.phase === "look").forEach(a => a.b.run(a));
  renderTemplates(cx);
  cx.nodes.forEach(n => { const card = n.shape === "card";
    showShape(n); n.m = card ? 1 : 0; n.turning = false;
    n.card.className = `card ${n.kind} s-${n.style} ${n.classes.join(" ")}`;
    n.dot.setAttribute("class", `dot ${n.kind} s-${n.style} ${n.classes.join(" ")}`);
    n.circle.setAttribute("r", n.r); n.label.setAttribute("dx", n.r + 6);
    n.w = card ? CARD_W : 2 * n.r; n.h = card ? n.cardH : 2 * n.r; });
}

export function applyRuleset(cx, next, warm = false) {   // warm: a live layout also settles first, so it can be travelled to
  for (const a of cx.active) a.b.unmount?.(a);
  cx.decor.innerHTML = ""; cx.anchors = [];
  cx.nodes.forEach(n => { n.shape = "dot"; n.r = R; n.classes = []; n.rank = undefined; n.col = undefined; n.anchor = null; n.tpl = null; n.vx = n.vy = 0; });
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
  if (!next.live || warm) for (let i = 0; i < (next.settle ?? (next.live ? 0 : 1)); i++) tick(cx);
  if (!next.live) {
    if (next.top !== undefined) { const lift = Math.min(...cx.nodes.map(n => n.y - n.h / 2)) - next.top;   // only ever pushed down: undo the drift
      cx.nodes.forEach(n => { n.y -= lift; }); } }
}

export function tick(cx) {
  for (const a of cx.active) if (a.b.phase === "force") a.b.run(a);
  if (cx.ruleset.live) { for (const n of cx.nodes) { if (!(cx.drag && cx.drag.target === n)) { n.x += n.vx * cx.heat; n.y += n.vy * cx.heat; } n.vx *= 0.6; n.vy *= 0.6; }
    cx.heat = Math.max(HEAT_FLOOR, cx.heat * 0.985); }
  const constraints = cx.active.filter(a => a.b.phase === "constraint");
  if (!cx.sweeps) { constraints.forEach(a => a.b.run(a)); return; }
  for (const part of cx.sweeps) for (const a of constraints) {   // one group at a time, each seeing the last one's moves
    const sel = a.sel.filter(n => part.has(n)); if (sel.length) a.b.run({...a, sel}); }
}
