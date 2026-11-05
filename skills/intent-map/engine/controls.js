// The toolbar: view switch, grouping, labels, flow, fit/zoom. Switching a view applies a different ruleset to the same nodes.
import {draw} from "./draw.js";
import {light} from "./light.js";
import {applyRuleset, showWarnings} from "./rules.js";
import {fit, fitWhenSettled, zoomAt} from "./view.js";

export function setMode(cx, next) {
  const ui = cx.ui, preset = cx.presets[next];
  cx.current = next; cx.pinned = null; light(cx, null); applyRuleset(cx, preset);
  ui.labelsLabel.hidden = !cx.nodes.some(n => n.shape === "dot");
  ui.groupingLabel.hidden = !preset.rules.some(r => r.id === "groups");
  ui.viewCards.setAttribute("aria-pressed", next === "cards");
  ui.viewNodes.setAttribute("aria-pressed", next === "nodes");
  if (preset.live) fitWhenSettled(cx);
  try { localStorage.setItem(cx.opts.storeKey, next); } catch (error) { /* storage unavailable: keep the default */ }
  draw(cx); fit(cx);
}

export function savedMode(cx) {
  try { return localStorage.getItem(cx.opts.storeKey); } catch (error) { return null; }
}

export function bindControls(cx) {
  const ui = cx.ui, nodes = cx.nodes;
  const choices = ["kind"].concat(nodes.some(n => n.group !== n.kind) ? ["group"] : [], ["none"]);
  const names = {kind: "kind (goal / needs / solutions / tests)", group: "group (from the map)", none: "nothing"};
  ui.grouping.replaceChildren(...choices.map(c => Object.assign(document.createElement("option"), {value: c, textContent: names[c]})));
  ui.viewCards.onclick = () => setMode(cx, "cards");
  ui.viewNodes.onclick = () => setMode(cx, "nodes");
  ui.grouping.onchange = () => {   // the dropdown edits a rule: the groups rule's `by`, or switches it off
    const rule = cx.presets.nodes.rules.find(r => r.id === "groups"), value = ui.grouping.value;
    rule.enabled = value !== "none";
    rule.do = [["attract", {by: value, hold: value === "kind" ? "row" : null}]];
    if (cx.current === "nodes") { applyRuleset(cx, cx.presets.nodes); draw(cx); fitWhenSettled(cx); } };
  ui.motion.onchange = ev => cx.stage.classList.toggle("paused", !ev.target.checked);
  ui.labels.onchange = ev => cx.stage.classList.toggle("nolabels", !ev.target.checked);
  ui.fit.onclick = () => fit(cx);
  ui.actual.onclick = () => { const r = cx.viewport.getBoundingClientRect(); zoomAt(cx, r.width / 2, r.height / 2, 1 / cx.view.k); };
  cx.onResize = () => fit(cx);
  addEventListener("resize", cx.onResize);
}
