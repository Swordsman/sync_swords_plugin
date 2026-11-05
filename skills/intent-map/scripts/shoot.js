// Screenshot an artifact-form page the way the viewer wraps it, at the widths it is seen at, in light and dark,
// and report script errors. usage: node shoot.js PAGE.html OUT_PREFIX
const { chromium } = require("playwright");
const fs = require("fs");
const [page_path, prefix] = process.argv.slice(2);
const skeleton = body => '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" ' +
  'content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light}body{margin:0;' +
  'font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style></head><body>' +
  body + "</body></html>";
const shots = [["panel-light", 760, 900, "light", []], ["desktop-dark", 1440, 900, "dark", []],
  ["phone-light", 400, 800, "light", []], ["nodes-panel-light", 760, 900, "light", ["#view-nodes"]],
  ["nodes-group-desktop-dark", 1440, 900, "dark", ["#view-nodes", "group"]]];
(async () => {
  const browser = await chromium.launch(), errors = [], made = [];
  for (const [name, width, height, scheme, actions] of shots) {
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme });
    page.on("pageerror", e => errors.push(`${name}: ${e}`));
    page.on("console", m => { if (m.type() === "error") errors.push(`${name}: ${m.text()}`); });
    await page.setContent(skeleton(fs.readFileSync(page_path, "utf8")), { waitUntil: "load" });
    await page.waitForTimeout(800);
    for (const action of actions) {   // "#id" clicks a control; anything else picks that grouping
      if (action.startsWith("#")) await page.click(action);
      else if (await page.$(`#grouping option[value="${action}"]`)) await page.selectOption("#grouping", action);
    }
    if (actions.length) await page.waitForTimeout(4500);   // let the force layout settle
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    if (overflow) errors.push(`${name}: the page body scrolls horizontally`);
    const file = `${prefix}-${name}.png`;
    await page.screenshot({ path: file, fullPage: true });
    made.push(file);
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify({ made, errors }));
})();
