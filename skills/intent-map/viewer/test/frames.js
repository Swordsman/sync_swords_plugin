// Frame times of a stored graph in the viewer, with Barnes-Hut forced off and on. usage: node frames.js SEED.json SLUG [SECONDS]
// Opens #SLUG against the mock db in its first mode (a live force layout), waits for the opening layout, then records
// requestAnimationFrame gaps. Headless Chromium draws in software: read the two rows against each other, not as device speed.
const { chromium } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const [seedFile, slug, secs = "4"] = process.argv.slice(2);
const seed = JSON.parse(fs.readFileSync(seedFile, "utf8"));
const viewer = path.resolve(__dirname, ".."), engine = path.resolve(viewer, "../engine");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  const file = url === "/" ? path.join(viewer, "viewer.html") : url.startsWith("/engine/") ? path.join(engine, url.slice(8)) : path.join(viewer, url);
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  let body = fs.readFileSync(file);
  if (url === "/") body = body.toString().replace('<script type="module"', '<script src="/test/mock.js"></script><script type="module"');
  res.writeHead(200, { "content-type": (types[path.extname(file)] || "text/plain") + "; charset=utf-8" }); res.end(body);
});
const withRepel = (docs, above) => docs.map((d) => d.slug !== slug ? d : { ...d, presets: Object.fromEntries(Object.entries(d.presets).map(([name, p]) => [name, { ...p,
  rules: p.rules.map((r) => ({ ...r, do: r.do.map(([b, q]) => b === "repel" ? [b, { ...q, above }] : [b, q]) })) }])) });
const stats = (gaps) => { const s = [...gaps].sort((a, b) => a - b), q = (f) => s[Math.min(s.length - 1, Math.floor(s.length * f))];
  return `mean ${(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1)} ms  p50 ${q(.5).toFixed(1)}  p95 ${q(.95).toFixed(1)}  max ${s[s.length - 1].toFixed(1)}  (${s.length} frames)`; };

const record = (page, ms) => page.evaluate((ms) => new Promise((resolve) => { const out = []; let last = performance.now(), end = last + ms;
  const step = (now) => { out.push(now - last); last = now; now < end ? requestAnimationFrame(step) : resolve(out); }; requestAnimationFrame(step); }), ms);
const tickCost = (page) => page.evaluate(async (slug) => {   // the layout's own cost: forces + integration, no drawing
  const { mountMap } = await import("/engine/mount.js"), { tick } = await import("/engine/rules.js"), doc = window.__SEED__.find((m) => m.slug === slug);
  const el = document.createElement("div"); el.style.cssText = "width:1000px;height:700px"; document.body.append(el);
  const h = mountMap(el, structuredClone(doc.data), { presets: structuredClone(doc.presets), modes: ["nodes"], storeKey: "frames" }); h.cx.alive = false;
  for (let i = 0; i < 60; i++) tick(h.cx);   // warm the JIT first
  const t0 = performance.now(); for (let i = 0; i < 100; i++) tick(h.cx); const ms = (performance.now() - t0) / 100; h.destroy(); el.remove(); return ms; }, slug);

(async () => {
  await new Promise((resolve) => server.listen(0, resolve));
  const browser = await chromium.launch(), doc = seed.find((m) => m.slug === slug);
  console.log(`${slug}: ${doc.data.nodes.length} nodes, ${doc.data.links.length} links`);
  for (const [name, above] of [["pairwise repel", 1e9], ["Barnes-Hut repel", 0]]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    await page.addInitScript((docs) => { window.__SEED__ = docs; }, withRepel(seed, above));
    await page.route(/fonts\.(googleapis|gstatic)/, (route) => route.abort());
    await page.goto(`http://localhost:${server.address().port}/#${slug}`);
    await page.waitForTimeout(1500);
    const settling = await record(page, +secs * 1000);
    await page.waitForTimeout(25000);   // heat falls to its floor after ~230 ticks; the layout then sleeps
    const asleep = await record(page, +secs * 1000);
    console.log(`${name.padEnd(17)} layout tick ${(await tickCost(page)).toFixed(1)} ms | frames while settling: ${stats(settling)} | asleep: ${stats(asleep)}`);
    await page.close();
  }
  await browser.close(); server.close();
})();
