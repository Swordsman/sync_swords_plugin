// The overview: every map is a node, grouped by project. Solid arrows are explicit refs; dashed lines are suggested links
// computed here from the terms the maps share. Click a node to see why it is linked; "open" goes to the map.
import { mountMap } from "../engine/mount.js";
import { suggest } from "./correlate.js";
import { h, pills, linkTo } from "./store.js";

// One ruleset on the same engine: map nodes sized by how many nodes they hold, grouped by a ring per project.
const OVERVIEW = { nodes: { live: true, fit: "all", seed: true, rules: [
  { id: "look", on: {}, do: [["shape", { as: "dot" }]] },
  { id: "size", on: {}, do: [["size", { r: 9, by: "priority", step: 0.2 }]] },
  { id: "physics", on: {}, do: [["repel", { strength: 5200 }], ["spring", { length: 190, k: 0.004 }], ["gravity", { k: 0.002 }]] },
  { id: "projects", on: {}, do: [["attract", { by: "group" }]] },
] } };

export function overviewData(maps, suggestions) {
  const slugs = new Set(maps.map((m) => m.slug));
  return {
    nodes: maps.map((m) => ({ id: m.slug, kind: "map", text: m.title, style: "map", icon: "🗺️", group: m.project || null,
      priority: m.data?.nodes?.length ?? 0, noId: true, maxLabel: 42 })),
    links: [...maps.flatMap((m) => (m.refs ?? []).filter((r) => slugs.has(r.slug)).map((r) => ({ source: m.slug, target: r.slug, kind: "ref" }))),
      ...suggestions.map((s) => ({ source: s.a, target: s.b, kind: "suggest", label: s.terms.join(" · "), weight: 0.4 }))],
    warnings: [],
  };
}

function detail(el, map, maps, suggestions) {
  if (!map) { el.replaceChildren(h("p", { className: "muted", textContent: "Click a map to see how it connects. Solid arrows: a map refers to another. Dashed: suggested from shared terms." })); return; }
  const title = (slug) => maps.find((m) => m.slug === slug)?.title ?? slug;
  const lines = [
    ...(map.refs ?? []).map((r) => ["builds on", r.slug, r.why]),
    ...maps.filter((m) => m.refs?.some((r) => r.slug === map.slug)).map((m) => ["used by", m.slug, m.refs.find((r) => r.slug === map.slug).why]),
    ...suggestions.filter((s) => s.a === map.slug || s.b === map.slug).map((s) => ["maybe related", s.a === map.slug ? s.b : s.a, `shares ${s.terms.join(", ")}`])];
  el.replaceChildren(h("b", {}, linkTo(map.slug, `Open ${map.title}`)), " ", pills(map.counts),
    h("p", { className: "goal-full", textContent: map.goal }),
    ...lines.map(([how, slug, why]) => h("p", { className: "muted" }, `${how} `, linkTo(slug, title(slug)), why ? ` — ${why}` : "")));
}

export function showOverview(host, maps) {
  const suggestions = suggest(maps), info = h("div", { className: "detail" }), canvas = h("div", { className: "canvas" });
  host.replaceChildren(h("h2", { className: "map-title", textContent: "How the maps connect" }), canvas, info);
  detail(info, null, maps, suggestions);
  return mountMap(canvas, overviewData(maps, suggestions), { presets: OVERVIEW, modes: ["nodes"], reach: "adjacent",
    storeKey: "intent-map-overview", onSelect: (node) => detail(info, node && maps.find((m) => m.slug === node.id), maps, suggestions) });
}
