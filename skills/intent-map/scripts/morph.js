// Toggles cards -> nodes -> cards on a built page, capturing frames mid-tween and at rest, and checks the tween's contract.
// Time is Playwright's fake clock, so the frames fall at the same moments every run.
// usage: node morph.js PAGE.html OUT_PREFIX   (writes OUT_PREFIX-<step>.png; prints {made, checks, errors})
const { chromium } = require("playwright");
const fs = require("fs");
const [pagePath, prefix] = process.argv.slice(2);
const html = fs.readFileSync(pagePath, "utf8");
const checks = [], errors = [], made = [];
const expect = (name, ok, extra = "") => checks.push(`${ok ? "ok  " : "FAIL"} ${name} ${extra}`);
const leftovers = () => [...document.querySelectorAll(".imap .card, .imap .dot")].filter(e => e.style.opacity || e.style.transform && e.classList.contains("card")).length;
const where = () => [...document.querySelectorAll(".imap .card")].map(e => e.style.left + e.style.top).join();
const centres = sel => [...document.querySelectorAll(sel)].map(e => { const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; });
const seen = () => ({ cards: [...document.querySelectorAll(".imap .card")].filter(e => !e.hidden).length,
  dots: [...document.querySelectorAll(".imap .dot")].filter(e => e.style.display !== "none").length });

(async () => {
  const browser = await chromium.launch();
  const open = async opts => { const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ...opts });
    page.on("pageerror", e => errors.push(String(e))); page.on("console", m => m.type() === "error" && !/ERR_FAILED/.test(m.text()) && errors.push(m.text()));
    await page.route(/fonts\.(googleapis|gstatic)/, r => r.abort()); await page.clock.install();
    await page.setContent(html, { waitUntil: "load" }); await page.clock.runFor(500); return page; };
  const wait = (page, ms) => page.clock.runFor(ms);
  const shot = async (page, name) => { const f = `${prefix}-${name}.png`; await page.screenshot({ path: f }); made.push(f); };
  const page = await open({});
  const total = (await page.locator(".imap .card").count()), before = await page.evaluate(where);
  await shot(page, "1-cards");
  const cardsAt = await page.evaluate(centres, ".imap .card");
  await page.click(".view-nodes"); await wait(page, 20);
  const dotsAt = await page.evaluate(centres, ".imap .dot circle"), drift = Math.max(...cardsAt.map((c, i) => Math.hypot(c[0] - dotsAt[i][0], c[1] - dotsAt[i][1])));
  expect("the switch starts from where each node was (largest drift after 20 ms, px)", drift < 25, drift.toFixed(1));
  let mid;
  for (const i of [1, 2, 3, 4]) { await wait(page, 200); mid ??= await page.evaluate(seen); await shot(page, `2-to-nodes-${i}`); }
  expect("mid-tween shows both shapes", mid.cards > 0 && mid.dots > 0, JSON.stringify(mid));
  await wait(page, 1200);
  const end = await page.evaluate(seen);
  expect("at rest in nodes view: dots only", end.cards === 0 && end.dots === total, JSON.stringify(end));
  expect("no morph styling left behind", (await page.evaluate(leftovers)) === 0);
  await wait(page, 2800); await shot(page, "3-nodes");
  await page.click(".view-cards");
  for (const i of [1, 2, 3, 4]) { await wait(page, 200); await shot(page, `4-to-cards-${i}`); }
  await wait(page, 1200);
  const back = await page.evaluate(seen);
  expect("at rest in cards view: cards only", back.dots === 0 && back.cards === total, JSON.stringify(back));
  expect("no morph styling left behind (cards)", (await page.evaluate(leftovers)) === 0);
  await shot(page, "5-cards");
  expect("cards land where they started", (await page.evaluate(where)) === before);
  await page.click(".view-nodes"); await wait(page, 150); await page.click(".view-cards"); await wait(page, 1500);
  expect("switching again mid-tween lands on cards", (await page.evaluate(seen)).cards === total);
  await page.close();
  const still = await open({ reducedMotion: "reduce" });
  await still.click(".view-nodes"); await wait(still, 60);
  const jumped = await still.evaluate(seen);
  expect("reduced motion: the switch is a jump", jumped.cards === 0 && jumped.dots === total, JSON.stringify(jumped));
  await still.close(); await browser.close();
  expect("no page errors", errors.length === 0, errors.join(" | "));
  console.log(JSON.stringify({ made, errors }) + "\n" + checks.join("\n"));
  process.exit(checks.some(c => c.startsWith("FAIL")) ? 1 : 0);
})();
