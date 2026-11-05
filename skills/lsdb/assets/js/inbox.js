// Inbox: the user leaves Claude notes; Claude reads them with lsdb and marks them done.
// Doc shape: {text, createdAt, status: "new" | "done", reply?}
import { catalogId, h, live, when } from "./db.js";

const DESCRIPTION = "Notes you leave for Claude. Claude reads new ones with lsdb and marks them done.";

export function mountInbox(db, root, report) {
  const text = h("textarea", { rows: 3, placeholder: "A note or request for Claude…" });
  const send = h("button", { className: "go", type: "submit", textContent: "Leave note" });
  const note = h("span", { className: "muted" });
  const form = h("form", { style: "display:grid;gap:8px" }, text, h("div", { style: "display:flex;gap:10px;align-items:center" }, send, note));
  const list = h("div", { className: "list", style: "margin-top:12px" });
  root.replaceChildren(h("h2", { textContent: "Inbox" }), h("p", { className: "muted", style: "margin-bottom:8px", textContent: DESCRIPTION }), form, list);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = text.value.trim();
    if (!value) return;
    send.disabled = true;
    try {
      await db.collection("inbox").add({ text: value, createdAt: new Date().toISOString(), status: "new" });
      await ensureListed(db);
      text.value = "";
      note.textContent = "Saved. Claude sees it next time it checks the inbox.";
    } catch (err) { report(err); } finally { send.disabled = false; }
  });

  live(db.collection("inbox").orderBy("createdAt", "desc").limit(20), (snap) => {
    list.replaceChildren(...snap.docs.map((doc) => {
      const data = doc.data();
      return h("div", { className: "item", style: "cursor:default" },
        h("span", { className: `pill ${data.status === "done" ? "done" : ""}`, textContent: data.status || "new" }), " ",
        h("span", { className: "muted", style: "font-size:12px", textContent: when(data.createdAt) }),
        h("pre", { style: "margin-top:4px", textContent: data.text || "" }),
        data.reply ? h("pre", { className: "muted", textContent: `Claude: ${data.reply}` }) : null);
    }));
  }, report);
}

async function ensureListed(db) {
  const ref = db.doc(`catalog/${catalogId("inbox")}`);
  if (!(await ref.get()).exists) await ref.set({ path: "inbox", description: DESCRIPTION, view: "table", updatedAt: new Date().toISOString() });
}
