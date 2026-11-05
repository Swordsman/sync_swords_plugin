// Builds the engine's model from DATA: nodes (each with a card and a dot), links with their wires, and neighbour maps.
import {CARD_W, R, svgEl, htmlEl} from "./util.js";

function buildCard(cx, n) {
  const card = htmlEl("div", `card ${n.kind} s-${n.style}`); card.tabIndex = 0; card.style.width = CARD_W + "px";
  const top = htmlEl("div", "top");
  top.append(htmlEl("span", "icon", n.icon), htmlEl("span", "id", n.id));
  const chipText = n.kind === "solution" ? n.status : n.style === "unmet" ? "unmet" : "";
  if (chipText) top.append(htmlEl("span", "chip", chipText));
  card.append(top, htmlEl("div", "", n.text));
  if (n.testedBy.length) card.append(htmlEl("div", "meta", "tested by " + n.testedBy.join(", ")));
  cx.stage.appendChild(card); n.card = card;
}

function buildDot(cx, n) {
  const g = svgEl("g", {class: `dot ${n.kind} s-${n.style}`, tabindex: 0}, cx.dotLayer);
  n.circle = svgEl("circle", {r: R}, g);
  svgEl("text", {class: "emoji", "text-anchor": "middle", dy: 4.5}, g).textContent = n.icon;
  n.label = svgEl("text", {dx: R + 6, dy: 4}, g);
  svgEl("tspan", {class: "id"}, n.label).textContent = n.id + " ";
  svgEl("tspan", {}, n.label).textContent = n.text.length > 30 ? n.text.slice(0, 28) + "…" : n.text;
  svgEl("title", {}, g).textContent = `${n.id} (${n.kind}${n.status ? ", " + n.status : ""}): ${n.text}`;
  n.dot = g;
}

function buildLinks(cx, data) {
  const arrow = (id, fill) => `<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="3.2" markerHeight="3.2" ` +
    `orient="auto"><path d="M0,0L10,5L0,10z" style="fill:var(${fill})"/></marker>`;
  cx.arrow = `arrow-${cx.uid}`; cx.arrowHot = `arrow-hot-${cx.uid}`;
  svgEl("defs", {}, cx.svg).innerHTML = arrow(cx.arrow, "--wire") + arrow(cx.arrowHot, "--hot");
  cx.links = data.links.map(l => ({...l, s: cx.byId[l.source], t: cx.byId[l.target]}));
  for (const l of cx.links) {
    l.directed = l.kind !== "suggest";   // suggested links are undirected: no arrow, no electrons
    l.wire = svgEl("path", {class: "wire " + l.kind}, cx.linkLayer);
    if (l.directed) l.wire.setAttribute("marker-end", `url(#${cx.arrow})`);
    l.path = svgEl("path", {class: "edge " + l.kind}, cx.linkLayer);
    if (l.label) { l.text = svgEl("text", {class: "linklabel", "text-anchor": "middle"}, cx.labelLayer); l.text.textContent = l.label; }
  }
}

export function buildGraph(cx, data) {
  cx.nodes = data.nodes.map((n, i) => ({testedBy: [], status: null, ...n, order: i, priority: n.priority ?? 0, x: 0, y: 0, vx: 0, vy: 0}));
  cx.byId = Object.fromEntries(cx.nodes.map(n => [n.id, n]));
  cx.anchorLayer = svgEl("g", {}, cx.svg); cx.linkLayer = svgEl("g", {}, cx.svg);
  cx.labelLayer = svgEl("g", {}, cx.svg); cx.dotLayer = svgEl("g", {}, cx.svg);
  buildLinks(cx, data);
  cx.neighbors = new Map(cx.nodes.map(n => [n, []]));
  cx.out = new Map(cx.nodes.map(n => [n, []])); cx.inn = new Map(cx.nodes.map(n => [n, []]));
  for (const l of cx.links) { cx.neighbors.get(l.s).push(l.t); cx.neighbors.get(l.t).push(l.s); cx.out.get(l.s).push(l); cx.inn.get(l.t).push(l); }
  cx.decor = htmlEl("div"); cx.stage.appendChild(cx.decor);   // column heads and other HTML decorations
  cx.legend.replaceChildren(...[...new Map(cx.nodes.map(n => [n.style, n.icon]))].map(([style, icon]) => htmlEl("span", "", `${icon} ${style}`)));
  for (const n of cx.nodes) { buildCard(cx, n); buildDot(cx, n); }
  cx.nodes.forEach(n => { n.cardH = n.card.offsetHeight; });   // measured once, while every card is still shown
}
