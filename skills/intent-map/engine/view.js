// The camera: pan, zoom, fit. The graph can never be dragged or zoomed out of sight (clamp keeps a margin on screen).
import {bounds} from "./draw.js";

const PAD = 16, KEEP_PX = 80;

export function clamp(cx) {   // the graph's box keeps a margin on screen, and at least one node stays inside the view
  const r = cx.viewport.getBoundingClientRect(), b = bounds(cx, false), v = cx.view;   // nodes only: an empty ring is not something to keep in sight
  if (!r.width || !r.height) return;
  const KEEP = Math.min(KEEP_PX, r.width / 4, r.height / 4);
  v.x = Math.min(r.width - KEEP - b.x0 * v.k, Math.max(KEEP - b.x1 * v.k, v.x));
  v.y = Math.min(r.height - KEEP - b.y0 * v.k, Math.max(KEEP - b.y1 * v.k, v.y));
  const over = (n) => [Math.max(0, KEEP - (n.x * v.k + v.x), n.x * v.k + v.x - (r.width - KEEP)),   // how far n is outside the safe area, per axis
                       Math.max(0, KEEP - (n.y * v.k + v.y), n.y * v.k + v.y - (r.height - KEEP))];
  const near = cx.nodes.reduce((best, n) => Math.hypot(...over(n)) < Math.hypot(...over(best)) ? n : best, cx.nodes[0]);
  const [dx, dy] = over(near), sx = near.x * v.k + v.x, sy = near.y * v.k + v.y;
  v.x += sx < KEEP ? dx : -dx; v.y += sy < KEEP ? dy : -dy;
}

export function applyView(cx) {
  clamp(cx);
  cx.stage.style.transform = `translate(${cx.view.x}px,${cx.view.y}px) scale(${cx.view.k})`;
  cx.zoomLevel.textContent = Math.round(cx.view.k * 100) + "%";
}

export function zoomAt(cx, px, py, factor) {
  const v = cx.view, k = Math.min(3, Math.max(0.15, v.k * factor)), f = k / v.k;
  v.x = px - (px - v.x) * f; v.y = py - (py - v.y) * f; v.k = k; applyView(cx);
}

export function fitView(cx) {   // the camera that frames the whole graph (computed, not applied)
  const r = cx.viewport.getBoundingClientRect(), b = bounds(cx), w = b.x1 - b.x0, h = b.y1 - b.y0;
  if (cx.ruleset.fit === "width") {   // read top-down: fit the width, scroll the rest
    const k = Math.min(1, (r.width - 2 * PAD) / w, Math.max(0.35, (r.height - 2 * PAD) / h));
    return {k, x: Math.max(PAD, (r.width - w * k) / 2) - b.x0 * k, y: PAD - b.y0 * k}; }
  const k = Math.min(1.4, (r.width - 2 * PAD) / w, (r.height - 2 * PAD) / h);
  return {k, x: (r.width - (b.x1 + b.x0) * k) / 2, y: (r.height - (b.y1 + b.y0) * k) / 2};
}

export function fit(cx) { Object.assign(cx.view, fitView(cx)); applyView(cx); }

export function bindViewport(cx) {   // wheel zoom, drag-to-pan on empty space, two-finger pinch
  const vp = cx.viewport, touches = cx.touches;
  vp.addEventListener("wheel", ev => { ev.preventDefault(); const r = vp.getBoundingClientRect();
    zoomAt(cx, ev.clientX - r.left, ev.clientY - r.top, Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0015))); }, {passive: false});
  vp.addEventListener("pointerdown", ev => {
    touches.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    if (touches.size === 2) { const [a, b] = [...touches.values()]; cx.drag = null; cx.pan = null;
      cx.pinch = {d: Math.hypot(a.x - b.x, a.y - b.y)}; return; }
    cx.pan = {x: ev.clientX - cx.view.x, y: ev.clientY - cx.view.y}; vp.classList.add("panning");
    vp.setPointerCapture(ev.pointerId); });
  vp.addEventListener("pointermove", ev => {
    if (touches.has(ev.pointerId)) touches.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    if (cx.pinch && touches.size === 2) { const [a, b] = [...touches.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
      const r = vp.getBoundingClientRect(); zoomAt(cx, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, d / cx.pinch.d);
      cx.pinch.d = d; return; }
    if (cx.pan) { cx.view.x = ev.clientX - cx.pan.x; cx.view.y = ev.clientY - cx.pan.y; applyView(cx); } });
  const release = ev => { touches.delete(ev.pointerId); if (touches.size < 2) cx.pinch = null;
    cx.pan = null; vp.classList.remove("panning"); };
  vp.addEventListener("pointerup", release);
  vp.addEventListener("pointercancel", release);
}
