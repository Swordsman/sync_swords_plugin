// Browse: the catalog lists every collection; pick one to list its docs, pick a doc to view it.
// Catalog doc shape (written by lsdb): {path, description?, view?: "json" | "text" | "table", updatedAt}
import { h, live, when } from "./db.js";

export function mountBrowse(db, side, main, report) {
  const state = { entries: [], picked: null, stop: null, open: new Set() };
  const list = h("div", { className: "list" });
  side.replaceChildren(h("h2", { textContent: "Collections" }), list);
  main.replaceChildren(h("h2", { textContent: "Documents" }), h("p", { className: "muted", textContent: "Pick a collection on the left." }));

  live(db.collection("catalog"), (snap) => {
    state.entries = snap.docs.map((doc) => doc.data()).filter((entry) => entry?.path).sort((a, b) => a.path.localeCompare(b.path));
    if (!state.entries.length) {
      list.replaceChildren(h("p", { className: "muted", textContent: "No collections yet. Each collection Claude writes with lsdb is listed here automatically." }));
      return;
    }
    list.replaceChildren(...state.entries.map((entry) => {
      const button = h("button", { className: `item ${entry.path === state.picked?.path ? "on" : ""}` },
        h("b", { textContent: entry.path }),
        entry.description ? h("div", { className: "muted", style: "font-size:12px", textContent: entry.description }) : null);
      button.addEventListener("click", () => pick(entry));
      return button;
    }));
  }, report, () => { list.textContent = "Can't reach the store yet…"; });

  function pick(entry) {
    state.picked = entry;
    state.open = new Set();
    state.stop?.();
    [...list.children].forEach((child) => child.classList?.toggle("on", child.querySelector("b")?.textContent === entry.path));
    const filter = h("input", { placeholder: "Filter by id or content…" });
    const count = h("p", { className: "muted", style: "font-size:12px" });
    const rows = h("div", { style: "display:grid;gap:8px;margin-top:8px" });
    main.replaceChildren(h("h2", { textContent: entry.path }),
      entry.description ? h("p", { className: "muted", style: "margin-bottom:8px", textContent: entry.description }) : null,
      filter, count, rows);
    let docs = [];
    const render = () => {
      const needle = filter.value.trim().toLowerCase();
      const shown = docs.filter((doc) => !needle || `${doc.id} ${JSON.stringify(doc.data)}`.toLowerCase().includes(needle));
      count.textContent = `${shown.length} of ${docs.length} document(s)${docs.length >= 500 ? " (first 500)" : ""}`;
      rows.replaceChildren(entry.view === "table" ? table(shown) : h("div", { style: "display:grid;gap:8px" }, ...shown.map((doc) => card(doc, entry))));
    };
    filter.addEventListener("input", render);
    state.stop = live(db.collection(entry.path).limit(500), (snap) => {
      docs = snap.docs.map((doc) => ({ id: doc.id, data: doc.data() || {} }));
      render();
    }, report);
  }

  function card(doc, entry) {
    const body = h("div", { hidden: !state.open.has(doc.id), style: "margin-top:6px" }, view(doc.data, entry.view),
      ...subcollections(entry.path, doc.id));
    const head = h("button", { className: "item" }, h("b", { textContent: doc.id }),
      h("span", { className: "muted", style: "font-size:12px", textContent: ` ${summary(doc.data)}` }));
    head.addEventListener("click", () => {  // remembered, so live re-renders keep it open
      body.hidden = !body.hidden;
      state.open[body.hidden ? "delete" : "add"](doc.id);
    });
    return h("div", { style: "border:1px solid var(--line);border-radius:8px;padding:4px 6px" }, head, body);
  }

  function subcollections(path, id) {
    const prefix = `${path}/${id}/`;
    const nested = state.entries.filter((entry) => entry.path.startsWith(prefix) && !entry.path.slice(prefix.length).includes("/"));
    return nested.map((entry) => {
      const link = h("button", { className: "item", textContent: `↳ ${entry.path}` });
      link.addEventListener("click", () => pick(entry));
      return link;
    });
  }
}

function view(data, kind) {
  if (kind === "text") {
    const text = data.body ?? data.text ?? data.content;
    if (typeof text === "string") return h("pre", { textContent: text });
  }
  return h("pre", { textContent: JSON.stringify(data, null, 2) });
}

function table(docs) {
  const keys = [...new Set(docs.flatMap((doc) => Object.keys(doc.data)))].slice(0, 8);
  const cell = (value) => h("td", { textContent: typeof value === "string" ? value : JSON.stringify(value ?? "") });
  return h("div", { className: "scroll" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", { textContent: "id" }), ...keys.map((key) => h("th", { textContent: key })))),
    h("tbody", {}, ...docs.map((doc) => h("tr", {}, h("td", { textContent: doc.id }), ...keys.map((key) => cell(doc.data[key])))))));
}

function summary(data) {
  const stamp = data.updatedAt || data.createdAt;
  const keys = Object.keys(data).filter((key) => key !== "updatedAt" && key !== "createdAt");
  return `${keys.slice(0, 4).join(", ")}${keys.length > 4 ? ", …" : ""}${stamp ? ` · ${when(stamp)}` : ""}`;
}
