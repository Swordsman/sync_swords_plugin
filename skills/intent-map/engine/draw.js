// Drawing: places cards, dots, meta-node rings and edges from the nodes' current positions.
import {CARD_W} from "./util.js";

const setPath = (l, d) => { l.wire.setAttribute("d", d); l.path.setAttribute("d", d); };

function rim(n, toward, pad) {   // where the line from n's centre toward a point leaves its shape
  const dx = toward.x - n.x, dy = toward.y - n.y, d = Math.hypot(dx, dy) || 1, ux = dx / d, uy = dy / d;
  const t = n.shape === "card" ? Math.min(n.w / 2 / (Math.abs(ux) || 1e-9), n.h / 2 / (Math.abs(uy) || 1e-9)) : n.r;
  return {x: n.x + ux * (t + pad), y: n.y + uy * (t + pad)};
}

export function draw(cx) {
  for (const n of cx.nodes) {
    if (n.shape === "card") { n.card.style.left = n.x - n.w / 2 + "px"; n.card.style.top = n.y - n.h / 2 + "px"; }
    else n.dot.setAttribute("transform", `translate(${n.x},${n.y})`); }
  cx.anchors.forEach(m => m.g.setAttribute("transform", `translate(${m.x},${m.y})`));
  for (const l of cx.links) {
    let a, b;
    if (l.s.shape === "card" && l.t.shape === "card" && Math.abs(l.s.x - l.t.x) > (l.s.w + l.t.w) / 2) {   // side to side, curved
      const right = l.s.x < l.t.x, x1 = l.s.x + (right ? 1 : -1) * l.s.w / 2, x2 = l.t.x + (right ? -1 : 1) * (l.t.w / 2 + 2);
      const bend = Math.max(30, Math.abs(x2 - x1) / 2) * (right ? 1 : -1);
      setPath(l, `M${x1},${l.s.y} C${x1 + bend},${l.s.y} ${x2 - bend},${l.t.y} ${x2},${l.t.y}`);
      a = {x: x1, y: l.s.y}; b = {x: x2, y: l.t.y};
    } else { a = rim(l.s, l.t, 0); b = rim(l.t, l.s, l.directed ? 3 : 0); setPath(l, `M${a.x},${a.y} L${b.x},${b.y}`); }
    if (l.text) { l.text.setAttribute("x", (a.x + b.x) / 2); l.text.setAttribute("y", (a.y + b.y) / 2 - 4); }
  }
  const b = bounds(cx); cx.svg.setAttribute("width", Math.max(1, b.x1)); cx.svg.setAttribute("height", Math.max(1, b.y1));
}

export function bounds(cx) {   // everything drawn, in stage coordinates (dot labels run about 190 px right of a dot)
  const labels = !cx.stage.classList.contains("nolabels");
  const xs = [], ys = [];
  for (const n of cx.nodes) { if (n.shape === "card") { xs.push(n.x - n.w / 2, n.x + n.w / 2); ys.push(n.y - n.h / 2, n.y + n.h / 2); }
    else { xs.push(n.x - n.r - 18, n.x + (labels ? 190 : n.r + 18)); ys.push(n.y - 30, n.y + 30); } }
  for (const m of cx.anchors) { xs.push(m.x - m.r, m.x + m.r); ys.push(m.y - m.r - 24, m.y + m.r); }
  for (const h of cx.decor.children) { xs.push(h.offsetLeft, h.offsetLeft + CARD_W); ys.push(0); }
  return {x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) + 8};
}
