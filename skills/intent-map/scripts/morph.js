// Toggles cards -> nodes -> cards on a built page, capturing frames mid-tween and at rest, and checks the tween's contract.
// usage: node morph.js PAGE.html OUT_PREFIX   (writes OUT_PREFIX-<step>.png; prints {made, checks, errors})
const { chromium } = require("playwright");
const fs = require("fs");
const [pagePath, prefix] = process.argv.slice(2);
const html = fs.readFileSync(pagePath, "utf8");
const checks = [], errors = [], made = [];
const expect = (name, ok, extra = "") => checks.push(`${ok ? "ok  " : "FAIL"} ${name} ${extra}`);
const leftovers = () => [...document.querySelectorAll(".imap .card, .imap .dot")].filter(e => e.style.opacity || e.style.transform && e.classList.contains("card")).length;
const where = () => [...document.querySelectorAll(".imap .card")].map(e => e.style.left + e.style.top).join();
const seen = () => ({ cards: [...document.querySelectorAll(".imap .card")].filter(e => !e.hidden).length,
  dots: [...document.querySelectorAll(".imap .dot")].filter(e => e.style.display !== "none").length });

(async () => {
  const browser = await chromium.launch();
  const open = async opts => { const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ...opts });
    page.on("pageerror", e => errors.push(String(e))); page.on("console", m => m.type() === "error" && !/ERR_FAILED/.test(m.text()) && errors.push(m.text()));
    await page.route(/fonts\.(googleapis|gstatic)/, r => r.abort());
    await page.setContent(html, { waitUntil: "load" }); await page.waitForTimeout(500); return page; };
  const shot = async (page, name) => { const f = `${prefix}-${name}.png`; await page.screenshot({ path: f }); made.push(f); };
  const page = await open({});
  const total = (await page.locator(".imap .card").count()), before = await page.evaluate(where);
  await shot(page, "1-cards");
  await page.click(".view-nodes");
  let mid;
  for (const i of [1, 2, 3, 4]) { await page.waitForTimeout(150); mid ??= await page.evaluate(seen); await shot(page, `2-to-nodes-${i}`); }
  expect("mid-tween shows both shapes", mid.cards > 0 && mid.dots > 0, JSON.stringify(mid));
  await page.waitForTimeout(1200);
  const end = await page.evaluate(seen);
  expect("at rest in nodes view: dots only", end.cards === 0 && end.dots === total, JSON.stringify(end));
  expect("no morph styling left behind", (await page.evaluate(leftovers)) === 0);
  await page.waitForTimeout(2800); await shot(page, "3-nodes");
  await page.click(".view-cards");
  for (const i of [1, 2, 3, 4]) { await page.waitForTimeout(150); await shot(page, `4-to-cards-${i}`); }
  await page.waitForTimeout(1200);
  const back = await page.evaluate(seen);
  expect("at rest in cards view: cards only", back.dots === 0 && back.cards === total, JSON.stringify(back));
  expect("no morph styling left behind (cards)", (await page.evaluate(leftovers)) === 0);
  await shot(page, "5-cards");
  expect("cards land where they started", (await page.evaluate(where)) === before);
  await page.click(".view-nodes"); await page.waitForTimeout(150); await page.click(".view-cards"); await page.waitForTimeout(1500);
  expect("switching again mid-tween lands on cards", (await page.evaluate(seen)).cards === total);
  await page.close();
  const still = await open({ reducedMotion: "reduce" });
  await still.click(".view-nodes"); await still.waitForTimeout(60);
  const jumped = await still.evaluate(seen);
  expect("reduced motion: the switch is a jump", jumped.cards === 0 && jumped.dots === total, JSON.stringify(jumped));
  await still.close(); await browser.close();
  expect("no page errors", errors.length === 0, errors.join(" | "));
  console.log(JSON.stringify({ made, errors }) + "\n" + checks.join("\n"));
  process.exit(checks.some(c => c.startsWith("FAIL")) ? 1 : 0);
})();
