// Field-bound numbers. Wherever a behavior takes a number it may take {scale: FIELD, from: [lo, hi], to: [a, b], of?}: the
// field's value, held to [lo, hi], maps linearly onto [a, b]. A node reads its own field; a link reads the field from itself
// or, failing that, from its two ends, combined by `of` (max by default, min, mean).
const COMBINE = {max: Math.max, min: Math.min, mean: (p, q) => (p + q) / 2};

export const isBound = v => typeof v === "object" && v !== null && "scale" in v;

function field(subject, name, of) {
  if (!subject.s) return +subject[name] || 0;
  return typeof subject[name] === "number" ? subject[name] : COMBINE[of || "max"](+subject.s[name] || 0, +subject.t[name] || 0);
}

export function num(v, subject) {
  if (!isBound(v)) return v;
  const [lo, hi] = v.from, [a, b] = v.to, at = Math.min(1, Math.max(0, (field(subject, v.scale, v.of) - lo) / (hi - lo || 1)));
  return a + (b - a) * at;
}
