// Drawing: places cards, dots, meta-node rings and edges from the nodes' current positions.
import {CARD_W} from "./util.js";
import {geometry} from "./edges.js";

export function showShape(n) {   // only the node's own shape shows, with no leftover morph styling
  const card = n.shape === "card";
  n.card.hidden = !card; n.dot.style.display = card ? "none" : "";
  n.card.style.transform = ""; n.card.style.opacity = n.dot.style.opacity = n.card.style.transition = n.dot.style.transition = "";
}

function place(n) {
  if (!n.turning) {
    if (n.shape === "card") { n.card.style.left = n.x - n.w / 2 + "px"; n.card.style.top = n.y - n.h / 2 + "px"; }
    else n.dot.setAttribute("transform", `translate(${n.x},${n.y})`);
    return; }
  n.card.hidden = false; n.dot.style.display = "";   // turning into the other shape: the card shrinks (or grows) as the dot fades in (or out)
  n.card.style.transition = n.dot.style.transition = "none"; n.card.style.opacity = n.m; n.dot.style.opacity = 1 - n.m;
  n.card.style.left = n.x - CARD_W / 2 + "px"; n.card.style.top = n.y - n.cardH / 2 + "px";
  n.card.style.transform = `scale(${n.w / CARD_W},${n.h / n.cardH})`;
  n.dot.setAttribute("transform", `translate(${n.x},${n.y})`);
}

export function draw(cx) {
  cx.nodes.forEach(place);
  cx.anchors.forEach(m => m.g.setAttribute("transform", `translate(${m.x},${m.y})`));
  for (const l of cx.links) {
    const {d, a, b} = geometry(l);
    l.wire.setAttribute("d", d); l.path.setAttribute("d", d);
    if (l.text) { l.text.setAttribute("x", (a.x + b.x) / 2); l.text.setAttribute("y", (a.y + b.y) / 2 - 4); }
  }
  const b = bounds(cx); cx.svg.setAttribute("width", Math.max(1, b.x1)); cx.svg.setAttribute("height", Math.max(1, b.y1));
}

export function bounds(cx, whole = true) {   // everything drawn, in stage coordinates (dot labels run about 190 px right of a dot)
  const labels = !cx.stage.classList.contains("nolabels");
  const xs = [], ys = [];
  for (const n of cx.nodes) { if (n.shape === "card") { xs.push(n.x - n.w / 2, n.x + n.w / 2); ys.push(n.y - n.h / 2, n.y + n.h / 2); }
    else { xs.push(n.x - n.r - 18, n.x + (labels ? Math.max(190, n.r + 24 + 5.6 * n.labelLen) : n.r + 18)); ys.push(n.y - 30, n.y + 30); } }
  if (whole) for (const m of cx.anchors) { xs.push(m.x - m.r, m.x + m.r); ys.push(m.y - m.r - 24, m.y + m.r); }
  if (whole) for (const h of cx.decor.children) { xs.push(h.offsetLeft, h.offsetLeft + CARD_W); ys.push(0); }
  return {x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) + 8};
}
