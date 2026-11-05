// Card and label templates. A template says which fields a node's card and dot label show, so any source draws sensibly.
//   head:  [[class, "text"], ...]  spans on the card's top row     chip:  "text"  a pill at its right end (hidden when empty)
//   body:  "text"                  the card's main line            meta:  ["text", ...]  small lines (a line with a missing field is dropped)
//   label: [[class, "text"], ...]  the dot's label (the last part is cut to `max` characters)     tip: "text"  the dot's tooltip
// "text" holds {field} or {field|format} (usd, k, pct, int); a field a node lacks makes the whole text empty.
// The default template is the intent-map look; a `template` rule overrides any key for the nodes it selects.
import {htmlEl, svgEl} from "./util.js";

const FORMAT = {
  usd: v => "$" + v.toFixed(v < 0.01 ? 4 : v < 1 ? 3 : 2),
  k: v => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(v < 1e4 ? 1 : 0) + "k" : String(Math.round(v)),
  pct: v => Math.round(v * 100) + "%",
  int: v => String(Math.round(v)),
};

export function fill(text, n) {   // -> string, or "" when a field is missing
  let missing = false;
  const out = text.replace(/\{(\w+)(?:\|(\w+))?\}/g, (_, field, format) => {
    const v = n[field]; if (v === undefined || v === null || v === "") { missing = true; return ""; }
    return format ? FORMAT[format](+v) : String(v); });
  return missing ? "" : out;
}

function intentFields(n) {   // the fields the default template reads; a source that sets them itself keeps its own
  n.chip ??= n.kind === "solution" ? n.status : n.style === "unmet" ? "unmet" : "";
  n.tested ??= n.testedBy.length ? "tested by " + n.testedBy.join(", ") : "";
  n.what ??= n.kind + (n.status ? ", " + n.status : "");
}

export const defaultTemplate = n => ({head: [["icon", "{icon}"], ["id", "{id}"]], chip: "{chip}", body: "{text}", meta: ["{tested}"],
  label: n.noId ? [["", "{text}"]] : [["id", "{id} "], ["", "{text}"]], max: n.maxLabel ?? 30, tip: "{id} ({what}): {text}"});

function fillCard(n, t) {
  const card = n.card; card.replaceChildren();
  const top = htmlEl("div", "top"), chip = fill(t.chip || "", n);
  top.append(...t.head.map(([cls, text]) => htmlEl("span", cls, fill(text, n))));
  if (chip) top.append(htmlEl("span", "chip", chip));
  card.append(top, htmlEl("div", "", fill(t.body, n)));
  for (const line of t.meta || []) { const text = fill(line, n); if (text) card.append(htmlEl("div", "meta", text)); }
}

function fillDot(n, t) {
  n.label.replaceChildren(); n.labelLen = 0;
  t.label.forEach(([cls, text], i) => {
    let shown = fill(text, n); if (i === t.label.length - 1 && shown.length > t.max) shown = shown.slice(0, t.max - 2) + "…";
    svgEl("tspan", cls ? {class: cls} : {}, n.label).textContent = shown; n.labelLen += shown.length; });
  n.dot.querySelector("title").textContent = fill(t.tip, n);
}

export function renderTemplates(cx) {   // rebuilds what changed since the last call, then measures the new cards (all shown meanwhile)
  const changed = [];
  for (const n of cx.nodes) {
    intentFields(n);
    const t = {...defaultTemplate(n), ...n.tpl}, key = JSON.stringify(t);
    if (key === n.tplKey) continue;
    n.tplKey = key; fillCard(n, t); fillDot(n, t); n.card.hidden = false; changed.push(n); }
  changed.forEach(n => { n.cardH = n.card.offsetHeight; });
}
