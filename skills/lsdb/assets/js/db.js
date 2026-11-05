// Shared helpers: open the db capability, build elements, and subscribe with a loading timeout.

export async function openDb(timeoutMs = 10000) {
  if (!window.claude?.use) return null;
  return Promise.race([claude.use("db"), new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs))]);
}

export function h(tag, props = {}, ...children) {
  const el = Object.assign(document.createElement(tag), props);
  el.append(...children.filter((child) => child != null && child !== false));
  return el;
}

// Subscribe once; onData(snapshot). If nothing arrives within 10 s, onSlow() says the data can't be reached yet.
export function live(ref, onData, onError, onSlow) {
  let timer = setTimeout(() => onSlow?.(), 10000);
  const clear = () => { clearTimeout(timer); timer = null; };
  return ref.onSnapshot(
    (snap) => { if (!snap.metadata?.fromCache) clear(); onData(snap); },
    (err) => { clear(); onError?.(err); },
  );
}

export const catalogId = (path) => path.replaceAll("/", "~");

export function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toLocaleString();
}
