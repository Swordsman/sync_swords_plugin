// Entry point: open the db once, then mount each panel. Each panel is its own module.
import { openDb } from "./db.js";
import { mountDashboard } from "./dashboard.js";
import { mountBrowse } from "./browse.js";
import { mountInbox } from "./inbox.js";

const status = document.getElementById("status");
const db = await openDb();
if (!db) {
  status.textContent = "The store isn't reachable in this view (open it on claude.ai while signed in to the owning account).";
} else {
  const report = (err) => { status.textContent = `Store error: ${err.code || ""} ${err.message || err}`; };
  mountDashboard(db, document.getElementById("dashboard"), report);
  mountBrowse(db, document.getElementById("catalog"), document.getElementById("docs"), report);
  mountInbox(db, document.getElementById("inbox"), report);
}
