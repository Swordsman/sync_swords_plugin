// One map: its title, goal, links to related maps, and the engine rendering it (cards or nodes, same as the standalone page).
import { mountMap } from "../engine/mount.js";
import { h, pills, linkTo } from "./store.js";

export function showMap(host, map, maps) {
  const known = new Set(maps.map((m) => m.slug));
  const related = (label, items) => items.length ? h("p", { className: "muted" }, `${label}: `,
    ...items.flatMap((item, i) => [i ? ", " : "", known.has(item.slug) ? linkTo(item.slug, item.slug) : item.slug,
      item.why ? h("span", { className: "why", textContent: ` (${item.why})` }) : ""])) : null;
  const usedBy = maps.filter((m) => m.refs?.some((r) => r.slug === map.slug)).map((m) => ({ slug: m.slug, why: m.refs.find((r) => r.slug === map.slug).why }));
  const canvas = h("div", { className: "canvas" });
  host.replaceChildren(
    h("h2", { className: "map-title", textContent: map.title }),
    h("p", { className: "meta" }, map.project ? h("span", { className: "project", textContent: map.project }) : null, pills(map.counts)),
    h("p", { className: "goal-full", textContent: map.goal }),
    ...[related("Builds on", map.refs ?? []), related("Used by", usedBy)].filter(Boolean), canvas,
    h("details", {}, h("summary", { textContent: "Source (sexpr)" }), h("pre", { textContent: map.sexpr })));
  return mountMap(canvas, map.data, { storeKey: "intent-map-view" });
}
