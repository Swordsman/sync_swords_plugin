// mountMap(root, data, opts): draws {nodes, links, warnings} into `root` under a ruleset and returns {destroy}.
//   nodes: {id, kind, text, style, icon, group?, status?, priority?, testedBy?, noId?, maxLabel?, ...any field a template or a rule reads}   links: {source, target, kind, label?, weight?}
//   opts:  presets (name -> ruleset; default cards + nodes), modes (which to offer), storeKey, title, reach, flow (false: start paused), onSelect(node|null)
import {PRESETS} from "./presets.js";
import {buildGraph} from "./graph.js";
import {bindNodes} from "./drag.js";
import {bindViewport} from "./view.js";
import {bindControls, setMode, savedMode} from "./controls.js";
import {HEAT_FLOOR, showWarnings, tick} from "./rules.js";
import {bindTween, stepTween} from "./tween.js";
import {draw} from "./draw.js";

const SHELL = `<header><h1></h1>
<span class="group view-switch" role="group" aria-label="view"><button class="view-cards" type="button" aria-pressed="true">cards</button>
<button class="view-nodes" type="button" aria-pressed="false">nodes</button></span>
<label class="grouping-label" hidden>group by <select class="grouping"></select></label>
<label class="labels-label" hidden><input type="checkbox" class="labels" checked> labels</label>
<label><input type="checkbox" class="motion" checked> flow</label>
<span class="group"><button class="fit" type="button">fit</button><button class="actual" type="button">100%</button>
<span class="zoomlevel"></span></span>
<div class="legend"></div></header>
<div class="warn"></div>
<div class="viewport"><div class="stage"><svg class="edges"></svg></div></div>`;

let instances = 0;

function shell(cx) {
  const root = cx.root, q = s => root.querySelector(s);
  root.className = "imap"; root.innerHTML = SHELL;
  q("h1").textContent = cx.opts.title || ""; q("h1").hidden = !cx.opts.title;
  Object.assign(cx, {stage: q(".stage"), svg: q(".edges"), viewport: q(".viewport"), warnEl: q(".warn"), legend: q(".legend"),
                     zoomLevel: q(".zoomlevel")});
  cx.ui = {viewCards: q(".view-cards"), viewNodes: q(".view-nodes"), grouping: q(".grouping"), groupingLabel: q(".grouping-label"),
           labels: q(".labels"), labelsLabel: q(".labels-label"), motion: q(".motion"), fit: q(".fit"), actual: q(".actual")};
  q(".view-switch").hidden = cx.modes.length < 2;
}

export function mountMap(root, data, opts = {}) {
  const presets = structuredClone(opts.presets || PRESETS);   // the controls edit rules: never the caller's copy
  const modes = opts.modes || Object.keys(presets);
  const cx = {root, data: {warnings: [], ...data}, presets, modes, uid: ++instances, alive: true, drag: null, anchors: [], heat: 1,
              ruleset: null, active: [], sweeps: null, view: {k: 1, x: 16, y: 16}, pinned: null, touches: new Map(), pan: null,
              pinch: null, opts: {storeKey: "intent-map-view", reach: "flow", ...opts}};
  cx.warnings = [...cx.data.warnings];
  shell(cx);
  buildGraph(cx, cx.data);
  showWarnings(cx);
  bindNodes(cx); bindViewport(cx); bindControls(cx); bindTween(cx);
  if (cx.opts.flow === false) { cx.ui.motion.checked = false; cx.stage.classList.add("paused", "noflow"); }   // many edges: start with the flow off
  const saved = savedMode(cx);
  setMode(cx, modes[0]);   // the first mode gives every node a starting place
  if (saved && saved !== modes[0] && modes.includes(saved)) setMode(cx, saved, false);
  const loop = now => {
    if (!cx.alive) return;
    const awake = cx.ruleset.live && (cx.heat > HEAT_FLOOR || cx.drag);   // a cooled layout does not move: nothing to tick or draw
    if (awake) tick(cx);
    if (cx.tween) stepTween(cx, now); else if (awake) draw(cx);
    cx.raf = requestAnimationFrame(loop);
  };
  loop(performance.now());
  return {cx, destroy() { cx.alive = false; cancelAnimationFrame(cx.raf); clearTimeout(cx.settleTimer);
    removeEventListener("resize", cx.onResize); root.replaceChildren(); }};
}
