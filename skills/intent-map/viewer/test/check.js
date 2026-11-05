// Drives the viewer against the mock db with Playwright. usage: node check.js SEED.json OUT_PREFIX
// Serves viewer.html + js/ from viewer/ and engine/ from ../../engine, the layout the published artifact has.
const { chromium } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const [seedFile, prefix] = process.argv.slice(2);
const seed = JSON.parse(fs.readFileSync(seedFile, "utf8"));
const viewer = path.resolve(__dirname, ".."), engine = path.resolve(viewer, "../engine");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
const roots = { "/js/": viewer, "/engine/": path.dirname(engine), "/test/": viewer };
const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0], root = Object.entries(roots).find(([p]) => url.startsWith(p));
  const file = url === "/" ? path.join(viewer, "viewer.html") : root ? path.join(root[1], url) : null;
  if (!file || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  let body = fs.readFileSync(file);   // the mock db goes in ahead of the module script, as the capability would be there
  if (url === "/") body = body.toString().replace('<script type="module"', '<script src="/test/mock.js"></script><script type="module"');
  res.writeHead(200, { "content-type": (types[path.extname(file)] || "text/plain") + "; charset=utf-8" }); res.end(body);
});
const checks = [], errors = [];
const expect = (name, ok, extra = "") => checks.push(`${ok ? "ok  " : "FAIL"} ${name} ${extra}`);

(async () => {
  await new Promise((resolve) => server.listen(0, resolve));
  const browser = await chromium.launch(), desktop = { viewport: { width: 1280, height: 900 } };
  const withMock = async (opts, hash = "") => {
    const page = await browser.newPage(opts);
    page.on("response", (r) => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`)); page.on("pageerror", (e) => errors.push(String(e))); page.on("console", (m) => m.type() === "error" && !/ERR_FAILED|status of 404/.test(m.text()) && errors.push(m.text()));
    await page.addInitScript((docs) => { window.__SEED__ = docs; }, seed);
    await page.route(/fonts\.(googleapis|gstatic)/, (route) => route.abort());
    await page.goto(`http://localhost:${server.address().port}/${hash}`);
    return page;
  };
  let page = await withMock(desktop);
  await page.waitForTimeout(3200);
  if (process.env.DEBUG) console.log(await page.evaluate(() => document.body.innerText.slice(0, 400)), errors);
  expect("list shows every map", (await page.locator("#list .entry").count()) === seed.length, `(${seed.length})`);
  expect("overview is the default view", (await page.locator("#main .map-title").first().textContent()).includes("connect"));
  const refs = seed.reduce((n, m) => n + m.refs.filter((r) => seed.some((s) => s.slug === r.slug)).length, 0);
  expect("overview draws every ref as an edge", (await page.locator("path.wire.ref").count()) === refs, `(${refs})`);
  const suggested = await page.locator("path.wire.suggest").count();
  expect("overview has suggested edges, labelled", seed.length < 4 || (suggested > 0 && (await page.locator(".linklabel").count()) === suggested), `(${suggested})`);
  expect("one node per map", (await page.locator(".imap .dot").count()) === seed.length);
  await page.screenshot({ path: `${prefix}-overview.png`, fullPage: true });
  // the camera cannot wander off the graph
  const box = await page.locator(".viewport").boundingBox();
  await page.mouse.move(box.x + 30, box.y + 30); await page.mouse.down(); await page.mouse.move(box.x + 30 + 6000, box.y + 30 + 4000, { steps: 8 }); await page.mouse.up();
  const where = await page.evaluate(() => { const v = document.querySelector(".viewport").getBoundingClientRect(); const d = [...document.querySelectorAll(".imap .dot")].map((e) => e.getBoundingClientRect());
    return d.some((r) => r.right > v.left && r.left < v.right && r.bottom > v.top && r.top < v.bottom); });
  if (process.env.DEBUG) console.log(await page.evaluate(() => ({ t: document.querySelector(".stage").style.transform, v: document.querySelector(".viewport").getBoundingClientRect().toJSON(), d: [...document.querySelectorAll(".imap .dot")].map((e) => e.getBoundingClientRect().toJSON()).map((r) => [Math.round(r.left), Math.round(r.right), Math.round(r.top), Math.round(r.bottom)]) })));
  expect("after a huge pan, part of the graph is still in view", where);
  // select a node: its detail appears with an Open link
  await page.locator(".imap .dot").first().click({ force: true }); await page.waitForTimeout(200);
  expect("selecting a map shows its detail", (await page.locator(".detail a").first().textContent()).startsWith("Open "));
  // open a map from the list
  const slug = seed.find((m) => m.refs.length)?.slug ?? seed[0].slug;
  await page.click(`#list a[href="#${slug}"]`); await page.waitForTimeout(1200);
  const doc = seed.find((m) => m.slug === slug);
  expect("a map renders as cards, one per node", (await page.locator(".imap .card").count()) === doc.data.nodes.length, `(${doc.data.nodes.length})`);
  expect("the map shows its goal and project", (await page.locator("#main .goal-full").first().textContent()) === doc.goal);
  await page.screenshot({ path: `${prefix}-map.png`, fullPage: true });
  await page.click(".view-nodes"); await page.waitForTimeout(2500);
  expect("nodes view draws dots", (await page.locator(".imap .dot:visible").count()) === doc.data.nodes.length);
  await page.close();
  page = await withMock({ viewport: { width: 390, height: 800 }, colorScheme: "dark" });
  await page.waitForTimeout(3000);
  expect("phone: no horizontal scroll", !(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)));
  await page.screenshot({ path: `${prefix}-phone-dark.png`, fullPage: true });
  await page.close();
  const unique = [...new Set(errors)];
  expect("no console or page errors", unique.length === 0, unique.join(" | "));
  console.log(checks.join("\n")); await browser.close(); server.close();
  process.exit(checks.some((c) => c.startsWith("FAIL")) ? 1 : 0);
})();
