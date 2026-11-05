// Behaviors that act on links (a rule's `edges` selector narrows them; without one, every link between selected nodes).
// All are forces. spring and balance pull a link toward a length, direction orders its ends, spread fans a node's links apart.
import {num} from "./params.js";
import {partition} from "./util.js";

const TURN = 2 * Math.PI, wrap = a => (a % TURN + TURN) % TURN;

function pull(l, rest, k) {   // a spring along one link toward length `rest`
  let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y; const d = Math.hypot(dx, dy) || 1, f = (d - rest) * k;
  dx /= d; dy /= d; l.s.vx += f * dx; l.s.vy += f * dy; l.t.vx -= f * dx; l.t.vy -= f * dy;
}

export const LINK_BEHAVIORS = {
  spring: {phase: "force", defaults: {length: 150, k: 0.004}, bound: ["length", "k"],   // a link's `weight` (default 1) scales its stiffness
    run(a) { for (const l of a.links) pull(l, num(a.p.length, l), num(a.p.k, l) * (l.weight ?? 1)); }},
  balance: {phase: "force", defaults: {k: 0.01, per: null}, bound: ["k"],   // each link toward the mean length of its group (`per`: a link field)
    run(a) { for (const part of partition(a.links, a.p.per)) { if (!part.length) continue;
      const mean = part.reduce((s, l) => s + Math.hypot(l.t.x - l.s.x, l.t.y - l.s.y), 0) / part.length;
      part.forEach(l => pull(l, mean, num(a.p.k, l))); } }},
  direction: {phase: "force", defaults: {axis: "x", sign: 1, gap: 60, k: 0.01}, bound: ["gap", "k"],   // target at least `gap` beyond source along axis (sign -1: behind)
    run(a) { const v = "v" + a.p.axis;
      for (const l of a.links) { const short = num(a.p.gap, l) - a.p.sign * (l.t[a.p.axis] - l.s[a.p.axis]);
        if (short > 0) { const f = short * num(a.p.k, l) * a.p.sign; l.t[v] += f; l.s[v] -= f; } } }},
  spread: {phase: "force", defaults: {k: 0.1}, bound: ["k"],   // a node's links fan out at even angles: each neighbour slides toward the middle of the two beside it
    setup(a) { a.state.around = new Map(a.sel.map(n => [n, []]));
      for (const l of a.links) { a.state.around.get(l.s).push(l.t); a.state.around.get(l.t).push(l.s); } },
    run(a) { for (const [hub, ends] of a.state.around) { if (ends.length < 2) continue;
      const ring = ends.map(m => ({m, th: Math.atan2(m.y - hub.y, m.x - hub.x), d: Math.min(240, Math.hypot(m.x - hub.x, m.y - hub.y) || 1)}))
        .sort((p, q) => p.th - q.th);
      ring.forEach((e, i) => { const next = ring[(i + 1) % ring.length], prev = ring[(i + ring.length - 1) % ring.length];
        const f = (wrap(next.th - e.th) - wrap(e.th - prev.th)) / 2 * e.d * num(a.p.k, hub), tx = -Math.sin(e.th) * f, ty = Math.cos(e.th) * f;
        e.m.vx += tx; e.m.vy += ty; hub.vx -= tx; hub.vy -= ty; }); } }},
};
