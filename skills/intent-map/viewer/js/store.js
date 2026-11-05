// Helpers shared by the viewer modules: open the db capability, build elements, subscribe with a slow-load notice.
export async function openDb(timeoutMs = 10000) {
  if (!window.claude?.use) return null;
  return Promise.race([claude.use("db"), new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs))]);
}

export function h(tag, props = {}, ...children) {
  const el = Object.assign(document.createElement(tag), props);
  el.append(...children.filter((child) => child != null && child !== false));
  return el;
}

// Subscribe once; onSlow() fires if nothing arrives within 10 s.
export function live(ref, onData, onError, onSlow) {
  let timer = setTimeout(() => onSlow?.(), 10000);
  const clear = () => { clearTimeout(timer); timer = null; };
  return ref.onSnapshot(
    (snap) => { if (!snap.metadata?.fromCache) clear(); onData(snap); },
    (err) => { clear(); onError?.(err); },
  );
}

export const STATUS_ORDER = ["built", "measured", "partial", "design", "untested", "not-built", "unmet"];

// Status counts as small coloured pills ("3 built", "1 unmet"), in a fixed order.
export function pills(counts = {}) {
  return h("span", { className: "pills" }, ...STATUS_ORDER.filter((s) => counts[s]).map((s) =>
    h("span", { className: `pill st-${s}`, textContent: `${counts[s]} ${s}` })));
}

export const linkTo = (slug, text) => h("a", { href: `#${slug}`, textContent: text ?? slug });
