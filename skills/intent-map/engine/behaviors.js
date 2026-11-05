// The behaviors a rule can invoke. A behavior is {phase, defaults, bound?, mount?, setup?, run?, unmount?, dropped?}; it gets
// `a` = {cx, rule, p (params), sel (selected nodes), links (selected links), state}. Phases: "look", "setup", "force" (adds
// velocity), "constraint" (moves positions, after integration). `bound` names the params that may follow a field (params.js);
// the link behaviors (spring, balance, direction, spread) live in links.js.
import {CARD_W, R, COLS, HEAD, partition, free, half, centroid, htmlEl} from "./util.js";
import {attract} from "./attract.js";
import {LINK_BEHAVIORS} from "./links.js";
import {num} from "./params.js";

const rankOf = order => v => { const i = order.indexOf(v); return i < 0 ? order.length : i; };

export const BEHAVIORS = {
  shape: {phase: "look", defaults: {as: "card"}, run(a) { a.sel.forEach(n => { n.shape = a.p.as; }); }},
  size: {phase: "look", defaults: {r: R, by: null, step: 3}, bound: ["r", "step"],   // a dot radius, fixed or grown by a numeric field
    run(a) { a.sel.forEach(n => { n.r = num(a.p.r, n) + (a.p.by ? num(a.p.step, n) * (+n[a.p.by] || 0) : 0); }); }},
  style: {phase: "look", defaults: {class: "emph"}, run(a) { a.sel.forEach(n => n.classes.push(a.p.class)); }},

  column: {phase: "constraint", defaults: {key: "kind", order: COLS, pitch: CARD_W + 84, sweeps: 4, heads: true},
    mount(a) {   // one column per value of `key`, in `order`; barycentre sweeps cut crossings between neighbours
      const rank = rankOf(a.p.order);
      const cols = partition(a.sel, a.p.key).sort((c, d) => rank(c[0][a.p.key]) - rank(d[0][a.p.key]) || c[0].order - d[0].order);
      a.state.cols = cols; cols.forEach((c, i) => c.forEach(n => { n.col = i; n.rank = c.indexOf(n); }));
      if (a.p.heads) cols.forEach((c, i) => { const h = htmlEl("div", "colhead", HEAD[c[0][a.p.key]] || String(c[0][a.p.key]).toUpperCase());
        h.style.left = i * a.p.pitch + "px"; a.cx.decor.appendChild(h); });
    },
    setup(a) {
      const cols = a.state.cols, sweep = (from, to, step) => { for (let i = from; i !== to; i += step) {
        const key = n => { const ns = a.cx.neighbors.get(n).filter(m => m.col === i - step && cols[i - step]);
          return ns.length ? ns.reduce((s, m) => s + m.rank, 0) / ns.length : n.rank; };
        const keys = new Map(cols[i].map(n => [n, key(n)]));
        cols[i].sort((p, q) => keys.get(p) - keys.get(q) || p.order - q.order); cols[i].forEach((n, r) => { n.rank = r; }); } };
      for (let round = 0; round < a.p.sweeps; round++) { sweep(1, cols.length, 1); sweep(cols.length - 2, -1, -1); }
    },
    run(a) { a.sel.forEach(n => { if (free(a.cx, n)) n.x = n.col * a.p.pitch + n.w / 2; }); }},
  "order-by": {phase: "setup", defaults: {key: "priority", dir: "desc", per: null},
    setup(a) { for (const part of partition(a.sel, a.p.per)) {
      part.sort((p, q) => (a.p.dir === "desc" ? -1 : 1) * ((p[a.p.key] > q[a.p.key]) - (p[a.p.key] < q[a.p.key])) || (p.rank ?? p.order) - (q.rank ?? q.order));
      part.forEach((n, r) => { n.rank = r; }); } }},
  relax: {phase: "constraint", defaults: {axis: "y", rate: 0.5}, bound: ["rate"],   // slide toward the middle of one's neighbours
    run(a) { const k = a.p.axis; a.sel.forEach(n => { const ns = a.cx.neighbors.get(n);
      if (ns.length && free(a.cx, n)) n[k] += (ns.reduce((s, m) => s + m[k], 0) / ns.length - n[k]) * num(a.p.rate, n); }); }},
  stack: {phase: "constraint", defaults: {axis: "y", gap: 12, per: null, start: null},   // no overlaps along one axis
    setup(a) { if (a.p.start === null) return; for (const part of this.sorted(a)) { let at = a.p.start;
      part.forEach(n => { n[a.p.axis] = at + half(n, a.p.axis); at += 2 * half(n, a.p.axis) + a.p.gap; }); } },
    sorted(a) { const k = a.p.axis; return partition(a.sel, a.p.per).map(part => [...part].sort((p, q) =>
      p.rank !== undefined && q.rank !== undefined ? p.rank - q.rank : p[k] - q[k])); },
    run(a) { const k = a.p.axis, g = a.p.gap;
      for (const part of this.sorted(a)) {
        for (let i = 1; i < part.length; i++) part[i][k] = Math.max(part[i][k], part[i - 1][k] + half(part[i - 1], k) + half(part[i], k) + g);
        for (let i = part.length - 2; i >= 0; i--) part[i][k] = Math.min(part[i][k], part[i + 1][k] - half(part[i + 1], k) - half(part[i], k) - g);
        if (a.p.start !== null) { const shift = a.p.start - Math.min(...part.map(n => n[k] - half(n, k)));
          if (shift > 0) part.forEach(n => { n[k] += shift; }); } } }},
  align: {phase: "constraint", defaults: {axis: "y", rate: 1, at: null}, bound: ["rate"],   // share one line: y for a row, x for a column
    run(a) { if (!a.sel.length) return; const k = a.p.axis, line = a.p.at ?? centroid(a.sel)[k];
      a.sel.forEach(n => { if (free(a.cx, n)) n[k] += (line - n[k]) * num(a.p.rate, n); }); }},
  pin: {phase: "constraint", defaults: {},
    setup(a) { a.state.at = new Map(a.sel.map(n => [n, {x: a.p.x ?? n.x, y: a.p.y ?? n.y}])); },
    dropped(a, n) { if (a.state.at.has(n)) a.state.at.set(n, {x: n.x, y: n.y}); },
    run(a) { a.state.at.forEach((p, n) => { if (free(a.cx, n)) { n.x = p.x; n.y = p.y; n.vx = n.vy = 0; } }); }},

  repel: {phase: "force", defaults: {strength: 3800}, bound: ["strength"],   // a pair pushes with the mean of its two strengths
    run(a) { const s = a.sel, st = s.map(n => num(a.p.strength, n)); for (let i = 0; i < s.length; i++) for (let j = i + 1; j < s.length; j++) { const p = s[i], q = s[j];
      let dx = q.x - p.x, dy = q.y - p.y; const d2 = dx * dx + dy * dy + 0.01, f = (st[i] + st[j]) / 2 / d2, d = Math.sqrt(d2);
      dx /= d; dy /= d; p.vx -= f * dx; p.vy -= f * dy; q.vx += f * dx; q.vy += f * dy; } }},
  gravity: {phase: "force", defaults: {k: 0.0015, unanchored: true}, bound: ["k"],
    setup(a) { a.state.c = a.sel.length ? centroid(a.sel) : {x: 0, y: 0}; },
    run(a) { const c = a.state.c; a.sel.forEach(n => { if (a.p.unanchored && n.anchor) return;
      const k = num(a.p.k, n); n.vx += (c.x - n.x) * k; n.vy += (c.y - n.y) * k; }); }},
  attract,
  ...LINK_BEHAVIORS,
};
