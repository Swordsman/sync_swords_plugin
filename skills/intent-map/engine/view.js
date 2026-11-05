// The camera: pan, zoom, fit. The graph can never be dragged or zoomed out of sight (clamp keeps a margin on screen).
import {bounds} from "./draw.js";

const PAD = 16, KEEP = 80;

export function clamp(cx) {
  const r = cx.viewport.getBoundingClientRect(), b = bounds(cx), v = cx.view;
  if (r.width < 4 * KEEP || r.height < 4 * KEEP) return;
  v.x = Math.min(r.width - KEEP - b.x0 * v.k, Math.max(KEEP - b.x1 * v.k, v.x));
  v.y = Math.min(r.height - KEEP - b.y0 * v.k, Math.max(KEEP - b.y1 * v.k, v.y));
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

export function fit(cx) {
  const r = cx.viewport.getBoundingClientRect(), b = bounds(cx), w = b.x1 - b.x0, h = b.y1 - b.y0, v = cx.view;
  if (cx.ruleset.fit === "width") {   // read top-down: fit the width, scroll the rest
    v.k = Math.min(1, (r.width - 2 * PAD) / w, Math.max(0.35, (r.height - 2 * PAD) / h));
    v.x = Math.max(PAD, (r.width - w * v.k) / 2) - b.x0 * v.k; v.y = PAD - b.y0 * v.k; applyView(cx); return; }
  v.k = Math.min(1.4, (r.width - 2 * PAD) / w, (r.height - 2 * PAD) / h);
  v.x = (r.width - (b.x1 + b.x0) * v.k) / 2; v.y = (r.height - (b.y1 + b.y0) * v.k) / 2; applyView(cx);
}

export function fitWhenSettled(cx) { clearTimeout(cx.settleTimer); cx.settleTimer = setTimeout(() => fit(cx), 1800); }

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
