// Dashboard: Claude writes dashboard/main; the page shows it live.
// Shape: {title, updatedAt, tiles: [{label, value, note?}], notes?: "text"}
import { h, live, when } from "./db.js";

export function mountDashboard(db, root, report) {
  const body = h("div", { textContent: "Loading…", className: "muted" });
  root.replaceChildren(h("h2", { textContent: "Dashboard" }), body);
  live(db.doc("dashboard/main"), (snap) => {
    if (!snap.exists) {
      body.replaceChildren(h("p", { className: "muted", textContent: "Nothing yet. Claude writes status here (doc dashboard/main) when there's something to show." }));
      return;
    }
    const data = snap.data();
    const tiles = (data.tiles || []).map((tile) => h("div", { className: "tile" },
      h("div", { className: "l", textContent: tile.label ?? "" }),
      h("div", { className: "v", textContent: String(tile.value ?? "") }),
      tile.note ? h("div", { className: "muted", textContent: tile.note }) : null));
    body.replaceChildren(
      data.title ? h("p", { style: "font-weight:600;margin-bottom:8px", textContent: data.title }) : null,
      tiles.length ? h("div", { className: "tiles" }, ...tiles) : null,
      data.notes ? h("pre", { style: "margin-top:10px", textContent: data.notes }) : null,
      data.updatedAt ? h("p", { className: "muted", style: "margin-top:8px;font-size:12px", textContent: `Updated ${when(data.updatedAt)}` }) : null);
  }, report, () => { body.textContent = "Can't reach the store yet…"; });
}
