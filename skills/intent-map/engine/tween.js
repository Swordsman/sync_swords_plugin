// Tweening: carries every node (position, size, card-ness) and the camera from one layout to another. A layout is
// {nodes: Map(node -> {x, y, w, h, m}), view: {k, x, y}}. The target is asked for afresh every frame, so it may still be
// moving (a live force layout) or come from anything that can produce a layout (say, a projection of a richer space).
import {ease, lerp} from "./util.js";
import {draw, showShape} from "./draw.js";
import {applyView, fit, fitView} from "./view.js";

const KEYS = ["x", "y", "w", "h", "m"], VIEW = ["k", "x", "y"];

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
export const snapshot = (cx, view = cx.view) => ({view: {...view},
  nodes: new Map(cx.nodes.map(n => [n, Object.fromEntries(KEYS.map(k => [k, n[k]]))]))});
const framed = cx => snapshot(cx, fitView(cx));   // where the nodes are now, seen by the camera that frames them

function mix(cx, tw, t) {   // writes the blend into the nodes and the camera; hands back the target the nodes still hold
  const to = tw.target(cx), e = ease(t);
  for (const [n, f] of tw.from.nodes) { const g = to.nodes.get(n); for (const k of KEYS) n[k] = lerp(f[k], g[k], e); }
  for (const k of VIEW) cx.view[k] = lerp(tw.from.view[k], to.view[k], e);
  cx.decor.style.opacity = cx.anchorLayer.style.opacity = e;   // column heads and rings fade in
  return to;
}

const progress = (tw, now) => Math.min(1, Math.max(0, (now - tw.t0) / tw.ms));

export function stepTween(cx, now) {
  const tw = cx.tween, t = progress(tw, now), to = mix(cx, tw, t);
  draw(cx); applyView(cx);
  for (const [n, g] of to.nodes) for (const k of KEYS) n[k] = g[k];   // the layout underneath carries on from where it truly is
  if (t === 1) endTween(cx);
}

export function endTween(cx) {   // lands on the target at once (the camera stays where it is)
  if (!cx.tween) return;
  cx.tween = null; cx.decor.style.opacity = cx.anchorLayer.style.opacity = "";
  cx.nodes.forEach(n => { n.turning = false; showShape(n); });
  draw(cx);
}

export function freeze(cx) {   // stops half way and keeps that picture as the layout, to start the next tween from
  const tw = cx.tween; if (!tw) return;
  mix(cx, tw, progress(tw, performance.now()));
  cx.tween = null; cx.decor.style.opacity = cx.anchorLayer.style.opacity = "";
}

export function startTween(cx, from, ms = 900, target = framed) {   // false when motion is off: the caller just jumps
  if (reducedMotion()) return false;
  const to = target(cx), tw = cx.tween = {from, target, ms, t0: performance.now()};
  cx.nodes.forEach(n => { n.turning = from.nodes.get(n).m !== to.nodes.get(n).m; });
  stepTween(cx, tw.t0); return true;
}

export function fitWhenSettled(cx) {   // a live layout is still moving: glide to its framing once it has calmed
  clearTimeout(cx.settleTimer);
  cx.settleTimer = setTimeout(() => { if (!cx.tween && !startTween(cx, snapshot(cx), 500)) fit(cx); }, 1800);
}

export function bindTween(cx) {   // grabbing the graph ends the animation
  for (const type of ["pointerdown", "wheel"]) cx.viewport.addEventListener(type, () => endTween(cx), {capture: true, passive: true});
}
