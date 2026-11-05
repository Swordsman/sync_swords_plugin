// Dragging nodes and meta-nodes, click-to-pin, and hover/focus highlighting.
import {draw} from "./draw.js";
import {light} from "./light.js";

export function startDrag(cx, ev, target, handle) {
  if (cx.touches.size > 1) return;
  ev.stopPropagation(); cx.touches.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
  const d = cx.drag = {target, cx: ev.clientX, cy: ev.clientY, ox: target.x, oy: target.y, moved: false};
  handle.setPointerCapture(ev.pointerId);
  handle.onpointermove = e => { if (!cx.drag || cx.pinch) return;
    const dx = (e.clientX - d.cx) / cx.view.k, dy = (e.clientY - d.cy) / cx.view.k;
    if (Math.hypot(dx, dy) > 3) d.moved = true;
    target.x = d.ox + dx; target.y = d.oy + dy; cx.heat = Math.max(cx.heat, 0.4); draw(cx); };
  handle.onpointerup = e => { cx.touches.delete(e.pointerId);
    if (cx.drag && d.moved && cx.anchors.includes(target)) target.fixed = true;   // a placed meta-node stays put
    if (cx.drag && d.moved) cx.active.forEach(a => a.b.dropped?.(a, target));
    if (cx.drag && !d.moved && cx.nodes.includes(target)) {
      cx.pinned = cx.pinned === target ? null : target; light(cx, cx.pinned); cx.opts.onSelect?.(cx.pinned); }
    cx.drag = null; handle.onpointermove = handle.onpointerup = null; };
}

export function bindNodes(cx) {
  cx.nodes.forEach(n => {
    for (const handle of [n.card, n.dot]) {
      handle.addEventListener("pointerdown", ev => startDrag(cx, ev, n, handle));
      handle.addEventListener("pointerenter", () => { if (!cx.drag) light(cx, cx.pinned || n); });
      handle.addEventListener("pointerleave", () => { if (!cx.drag) light(cx, cx.pinned); });
      handle.addEventListener("focus", () => light(cx, n));
      handle.addEventListener("blur", () => light(cx, cx.pinned));
    }
  });
}
