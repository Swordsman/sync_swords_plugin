// A stand-in for the page's `db` capability (claude.use("db")): enough of the Firestore-style API for the viewer's reads.
// Seed with window.__SEED__ = [map docs] before this script runs.
(() => {
  const store = new Map(), subs = new Set();
  const put = (path, data) => { store.set(path, structuredClone(data)); setTimeout(() => subs.forEach((s) => s()), 0); };
  const snap = (path) => ({ id: path.split("/").pop(), exists: store.has(path), data: () => structuredClone(store.get(path)), metadata: { fromCache: false } });
  const collection = (name) => {
    const run = () => { const docs = [...store.keys()].filter((k) => k.startsWith(name + "/") && !k.slice(name.length + 1).includes("/")).map(snap);
      return { docs, size: docs.length, empty: !docs.length, metadata: { fromCache: false } }; };
    return { path: name, limit: () => collection(name), orderBy: () => collection(name),
      onSnapshot(next) { const s = () => next(run()); subs.add(s); setTimeout(s, 0); return () => subs.delete(s); } };
  };
  for (const doc of window.__SEED__ ?? []) put(`maps/${doc.slug}`, doc);
  window.__putMap = (doc) => put(`maps/${doc.slug}`, doc);
  window.claude = { use: async (name) => (name === "db" ? { collection, doc: (p) => ({ path: p }) } : null) };
})();
