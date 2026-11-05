// The `attract` behavior: one meta-node (dashed ring) per value of `by`. It pulls its members in, pushes everyone else
// out, and keeps apart from the other rings. `hold: "row"` sets ordered groups in a fixed row; others follow their members.
import {COLS, HEAD, partition, free, centroid, svgEl} from "./util.js";
import {startDrag} from "./drag.js";

export const attract = {phase: "force", defaults: {by: "kind", hold: null, order: COLS, gap: 110, keep: 90, pull: 0.09, slack: 0.015, push: 0.12},
  mount(a) {
    const cx = a.cx, rank = v => { const i = a.p.order.indexOf(v); return i < 0 ? a.p.order.length : i; };
    const parts = partition(a.sel, a.p.by).filter(m => m[0][a.p.by] !== null && m[0][a.p.by] !== undefined)
      .sort((m, q) => rank(m[0][a.p.by]) - rank(q[0][a.p.by]) || m[0].order - q[0].order);
    a.state.anchors = parts.map(members => {
      const name = members[0][a.p.by], c = centroid(members), g = svgEl("g", {class: "anchor"}, cx.anchorLayer);
      const r = 34 + 30 * Math.sqrt(members.length), ring = svgEl("circle", {r}, g);
      const label = svgEl("text", {"text-anchor": "middle", y: -r - 6}, g); label.textContent = (HEAD[name] || String(name)).toUpperCase();
      const anchor = {name, members, g, r, x: c.x, y: c.y, fixed: false, w: 2 * r, h: 2 * r};
      members.forEach(n => { n.anchor = anchor; });
      g.addEventListener("pointerdown", ev => startDrag(cx, ev, anchor, g));
      return anchor; });
    if (a.p.hold === "row") {   // ordered groups sit in a held row, left to right, spaced by their rings
      const all = centroid(a.sel), width = a.state.anchors.reduce((s, m) => s + 2 * m.r, 0) + a.p.gap * (a.state.anchors.length - 1);
      let x = all.x - width / 2;
      a.state.anchors.forEach(m => { m.x = x + m.r; x += 2 * m.r + a.p.gap; m.y = all.y; m.fixed = true; });
    }
    cx.anchors.push(...a.state.anchors);
  },
  unmount(a) { a.state.anchors.forEach(m => { m.g.remove(); }); a.cx.anchors = a.cx.anchors.filter(m => !a.state.anchors.includes(m)); },
  run(a) {
    const cx = a.cx, mine = a.state.anchors;
    for (const m of mine) {
      if (!m.fixed && free(cx, m) && m.members.length) { const c = centroid(m.members); m.x += (c.x - m.x) * 0.08; m.y += (c.y - m.y) * 0.08; }
      for (const n of cx.nodes) { const dx = n.x - m.x, dy = n.y - m.y, d = Math.hypot(dx, dy) || 1;
        if (n.anchor === m) { const pull = d > m.r * 0.75 ? a.p.pull : a.p.slack; n.vx -= dx * pull; n.vy -= dy * pull; }
        else if (d < m.r + 24) { const f = (m.r + 24 - d) * a.p.push; n.vx += dx / d * f; n.vy += dy / d * f; } }
    }
    for (let i = 0; i < mine.length; i++) for (let j = i + 1; j < mine.length; j++) { const p = mine[i], q = mine[j];   // groups keep apart
      const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 1, gap = p.r + q.r + a.p.keep;
      if (d < gap) { const f = (gap - d) * 0.05, ux = dx / d, uy = dy / d;
        for (const [m, sign] of [[p, -1], [q, 1]]) { if (!m.fixed && free(cx, m)) { m.x += sign * ux * f; m.y += sign * uy * f; }
          m.members.forEach(n => { n.vx += sign * ux * f * 0.5; n.vy += sign * uy * f * 0.5; }); } } }
  }};
