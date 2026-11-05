// The toolbar: view switch, grouping, labels, flow, fit/zoom. Switching a view applies a different ruleset to the same nodes,
// and (unless motion is off) every node travels from where it was to where the new rules put it.
import {draw} from "./draw.js";
import {light} from "./light.js";
import {applyRuleset} from "./rules.js";
import {fit, zoomAt} from "./view.js";
import {endTween, fitWhenSettled, freeze, snapshot, startTween} from "./tween.js";

export function setMode(cx, next, animate = true) {
  const ui = cx.ui, preset = cx.presets[next];
  freeze(cx);
  const from = animate && cx.ruleset ? snapshot(cx) : null;
  cx.current = next; cx.pinned = null; light(cx, null); applyRuleset(cx, preset, !!from || !cx.ruleset);   // a live layout settles first, whether to be travelled to or to open on a calm picture
  ui.labelsLabel.hidden = !cx.nodes.some(n => n.shape === "dot");
  ui.groupingLabel.hidden = !preset.rules.some(r => r.id === "groups");
  ui.viewCards.setAttribute("aria-pressed", next === "cards");
  ui.viewNodes.setAttribute("aria-pressed", next === "nodes");
  if (preset.live) fitWhenSettled(cx);
  try { localStorage.setItem(cx.opts.storeKey, next); } catch (error) { /* storage unavailable: keep the default */ }
  if (from && startTween(cx, from)) return;
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
    if (cx.current === "nodes") { endTween(cx); applyRuleset(cx, cx.presets.nodes); draw(cx); fitWhenSettled(cx); } };
  ui.motion.onchange = ev => { cx.stage.classList.toggle("paused", !ev.target.checked); cx.stage.classList.toggle("noflow", !ev.target.checked && cx.opts.flow === false); draw(cx); };
  ui.labels.onchange = ev => cx.stage.classList.toggle("nolabels", !ev.target.checked);
  ui.fit.onclick = () => fit(cx);
  ui.actual.onclick = () => { const r = cx.viewport.getBoundingClientRect(); zoomAt(cx, r.width / 2, r.height / 2, 1 / cx.view.k); };
  cx.onResize = () => fit(cx);
  addEventListener("resize", cx.onResize);
}
