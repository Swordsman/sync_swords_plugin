// Entry point: one live subscription to `maps`; the hash picks the view (#overview or none: overview, #<slug>: that map).
import { openDb, live, h } from "./store.js";
import { renderList } from "./list.js";
import { showMap } from "./mapview.js";
import { showOverview } from "./overview.js";

const $ = (id) => document.getElementById(id);
const status = $("status"), main = $("main");
const state = { maps: [], shown: null, view: null };

const route = () => decodeURIComponent(location.hash.slice(1)) || "overview";

function signature(name) {   // what the current view depends on: it is rebuilt only when this changes
  const stamp = (m) => `${m.slug}@${m.updatedAt}`;
  if (name === "overview") return `overview|${state.maps.map(stamp).join(",")}`;
  const map = state.maps.find((m) => m.slug === name);
  return map ? `${stamp(map)}|${state.maps.filter((m) => m.refs?.some((r) => r.slug === name)).map(stamp).join(",")}` : `missing|${name}`;
}

function render() {
  const name = route();
  renderList($("list"), state.maps, name);
  const sig = signature(name);
  if (state.shown === sig) return;
  state.shown = sig;
  state.view?.destroy();
  state.view = null;
  const map = state.maps.find((m) => m.slug === name);
  if (name === "overview") state.view = state.maps.length ? showOverview(main, state.maps) : (main.replaceChildren(h("p", { className: "muted", textContent: "Nothing to connect yet." })), null);
  else if (map) state.view = showMap(main, map, state.maps);
  else main.replaceChildren(h("p", { className: "muted" }, `No map called "${name}" in the store (yet). `, h("a", { href: "#overview", textContent: "Overview" })));
}

const db = await openDb();
if (!db) {
  status.textContent = "The store isn't reachable in this view (open it on claude.ai while signed in to the owning account).";
} else {
  addEventListener("hashchange", render);
  live(db.collection("maps"), (snap) => {
    state.maps = snap.docs.map((doc) => doc.data()).filter((m) => m?.slug && m.data).sort((a, b) => a.slug.localeCompare(b.slug));
    status.textContent = "";
    render();
  }, (err) => { status.textContent = `Store error: ${err.code || ""} ${err.message || err}`; },
  () => { status.textContent = "Can't reach the store yet…"; });
}
