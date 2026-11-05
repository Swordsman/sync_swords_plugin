// Edge geometry. A card-to-card link beside it runs side to side as a curve, anything else as a line between the shapes' rims.
// Nodes carry m (1 card, 0 dot, between while one turns into the other), so a link between shapes in transit blends the two.
import {lerp} from "./util.js";

function rim(n, toward, pad) {   // where the line from n's centre toward a point leaves its shape
  const dx = toward.x - n.x, dy = toward.y - n.y, d = Math.hypot(dx, dy) || 1, ux = dx / d, uy = dy / d;
  const box = Math.min(n.w / 2 / (Math.abs(ux) || 1e-9), n.h / 2 / (Math.abs(uy) || 1e-9)), t = n.m * box + (1 - n.m) * n.r;
  return {x: n.x + ux * (t + pad), y: n.y + uy * (t + pad)};
}

function curve(l) {   // [from, control, control, to] of the side-to-side cubic
  const right = l.s.x < l.t.x, x1 = l.s.x + (right ? 1 : -1) * l.s.w / 2, x2 = l.t.x + (right ? -1 : 1) * (l.t.w / 2 + 2);
  const bend = Math.max(30, Math.abs(x2 - x1) / 2) * (right ? 1 : -1);
  return [{x: x1, y: l.s.y}, {x: x1 + bend, y: l.s.y}, {x: x2 - bend, y: l.t.y}, {x: x2, y: l.t.y}];
}

const along = (a, b, t) => ({x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t)});
const cubic = c => `M${c[0].x},${c[0].y} C${c[1].x},${c[1].y} ${c[2].x},${c[2].y} ${c[3].x},${c[3].y}`;

export function geometry(l) {   // {d: path, a, b: where the line starts and ends}
  const side = Math.abs(l.s.x - l.t.x) > (l.s.w + l.t.w) / 2 ? Math.min(l.s.m, l.t.m) : 0;
  if (side === 1) { const c = curve(l); return {d: cubic(c), a: c[0], b: c[3]}; }
  const a = rim(l.s, l.t, 0), b = rim(l.t, l.s, l.directed ? 3 : 0);
  if (side === 0) return {d: `M${a.x},${a.y} L${b.x},${b.y}`, a, b};
  const c = curve(l).map((p, i) => along([a, along(a, b, 1 / 3), along(a, b, 2 / 3), b][i], p, side));
  return {d: cubic(c), a: c[0], b: c[3]};
}
