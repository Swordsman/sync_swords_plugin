// The map list, grouped by project: title, goal and status counts for each map; the Overview entry on top.
import { h, pills, linkTo } from "./store.js";

export const NO_PROJECT = "no project";

export function byProject(maps) {
  const groups = new Map();
  for (const map of maps) {
    const name = map.project || NO_PROJECT;
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(map);
  }
  const names = [...groups.keys()].sort((a, b) => (a === NO_PROJECT) - (b === NO_PROJECT) || a.localeCompare(b));
  return names.map((name) => [name, groups.get(name).sort((a, b) => a.title.localeCompare(b.title))]);
}

export function renderList(el, maps, active) {
  const entry = (map) => h("div", { className: `entry ${map.slug === active ? "on" : ""}` },
    h("b", {}, linkTo(map.slug, map.title)),
    h("div", { className: "goal", textContent: map.goal || "" }),
    pills(map.counts));
  const overview = h("a", { href: "#overview", className: `overview-link ${active === "overview" ? "on" : ""}`, textContent: "Overview: how the maps connect" });
  el.replaceChildren(h("h2", { textContent: `Maps (${maps.length})` }), overview,
    ...(maps.length ? byProject(maps).flatMap(([name, group]) => [h("h3", { textContent: name }), ...group.map(entry)])
      : [h("p", { className: "muted", textContent: "No maps stored yet. Push one with intentmap.py --store (see the box above)." })]));
}
