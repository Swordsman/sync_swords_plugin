// Constants and small helpers shared by the intent-map engine modules.
export const CARD_W = 236, R = 12, NS = "http://www.w3.org/2000/svg";
export const COLS = ["goal", "need", "solution", "test"];
export const HEAD = {goal: "GOAL", need: "NEEDS", solution: "SOLUTIONS", test: "TESTS"};
const OPS = {"=": (a, b) => a === b, "!=": (a, b) => a !== b, "<": (a, b) => a < b, "<=": (a, b) => a <= b,
             ">": (a, b) => a > b, ">=": (a, b) => a >= b};

export const lerp = (a, b, t) => a + (b - a) * t;
export const ease = t => t < 0.5 ? 2 * t * t : 1 - (2 - 2 * t) ** 2 / 2;

export function matches(n, on) {
  return Object.entries(on || {}).every(([key, want]) => {
    if (key === "priority") { const [op, v] = want; if (!OPS[op]) throw new Error(`unknown comparison ${op}`); return OPS[op](n.priority, v); }
    return Array.isArray(want) ? want.includes(n[key]) : n[key] === want; });
}
export function linkMatches(l, sel) {   // {kind, from, to, end}: the link's kind, fields at its source or target, at either end
  if (!sel) return true;
  const has = (want, v) => want === undefined || (Array.isArray(want) ? want.includes(v) : want === v);
  return has(sel.kind, l.kind) && (!sel.from || matches(l.s, sel.from)) && (!sel.to || matches(l.t, sel.to)) &&
    (!sel.end || matches(l.s, sel.end) || matches(l.t, sel.end));
}
export function partition(members, key) {
  if (!key) return [members];
  const parts = new Map(); for (const n of members) { const v = n[key]; if (!parts.has(v)) parts.set(v, []); parts.get(v).push(n); }
  return [...parts.values()];
}
export const free = (cx, n) => !(cx.drag && cx.drag.target === n);
export const half = (n, axis) => axis === "x" ? n.w / 2 : n.h / 2;
export const rankIn = (order, v) => { const i = (order || []).indexOf(v); return i < 0 ? Infinity : i; };
export const centroid = list => ({x: list.reduce((s, n) => s + n.x, 0) / list.length, y: list.reduce((s, n) => s + n.y, 0) / list.length});

export function svgEl(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
export function htmlEl(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}
