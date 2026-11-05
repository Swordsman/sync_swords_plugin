---
name: lsdb
description: Read and write claude.ai artifact databases from code with lsdb, so bulk data persists between sessions and only results reach the context. Use whenever data should live in an artifact's db (stores, logs, graphs, intent maps, memory payloads, anything a db-backed page renders), when reading or writing ArtifactData would take many tool calls, or when creating a store artifact. Works inside claude.ai/code sessions; outside them, fall back to the ArtifactData tool.
---

# lsdb

`scripts/lsdb/` in this plugin: a standard-library Python package. Library and CLI over the
endpoint behind the ArtifactData tool. That endpoint is undocumented and internal; if it changes,
lsdb fails loudly (exit 2 with the reply body), never silently.

## Requirements
- A claude.ai/code session: `CLAUDE_CODE_REMOTE_SDK_URL` and `CLAUDE_SESSION_INGRESS_TOKEN_FILE`
  are set. Without them every call exits 3 and says to use ArtifactData instead.
- The artifact's served version declares the `db` capability (else HTTP 404 `not_declared`).
- The artifact belongs to this account. Invited editors can't use another account's db from code,
  so each account keeps its own store.

## Creating a store
lsdb can't create artifacts; you do. Publish a page with the Artifact tool and
`capabilities: {"db": {}}`. A private artifact is readable and writable only by its owner, so no
rules are needed for a personal store. Record the store's URL somewhere durable (memory or the
project's notes) or the next session can't find it.

The template in `assets/` is a working store page: `store.html` plus `js/` modules, published
together (`file_path` store.html, `files` {"js/app.js": ..., "js/db.js": ..., "js/browse.js": ...,
"js/dashboard.js": ..., "js/inbox.js": ...}). Use it as-is or build on it.

## Designing an lsdb page
- Write the page once. It's a thin loader: everything it shows lives in the db and renders from
  data, live (`onSnapshot`), so new content never needs a republish.
- Reads must be usable without knowing names: the page lists the `catalog` and explains itself.
- It can be a channel both ways: the user leaves notes in `inbox`; you show status on `dashboard/main`.
- One module per feature (`js/browse.js`, `js/dashboard.js`, `js/inbox.js`); add your own the same way.

## Catalog and conventions
- `catalog/<collection path with / as ~>`: `{path, description?, view?, updatedAt}`. Every write
  through lsdb registers its collection the first time a process writes there (set
  `lsdb.catalog.AUTO = False` to stop). `lsdb.register(url, "notes", "what it holds", view="text")`
  (CLI `register URL COLLECTION --description --view`) sets what the page shows. Views: `json`
  (default), `text` (renders the `body`/`text`/`content` field), `table` (top-level fields as columns).
- `inbox/<id>`: `{text, createdAt, status: "new"|"done", reply?}`, written by the page. Check new notes
  with `lsdb.query(url, "inbox", where=[("status", "==", "new")])`; answer by updating `status` and `reply`.
- `dashboard/main`: `{title, updatedAt, tiles: [{label, value, note?}], notes?}`, written by you.

## Data model and limits
- Paths: a document has an even number of segments (`notes/n1`, `projects/p1/maps/m1`); a
  collection an odd number (`notes`, `projects/p1/maps`). Deleting a doc keeps its subcollections.
- A doc is a JSON object, at most 256 KiB serialized and 32 levels deep. Split larger payloads
  across docs.
- Per artifact: 25,000 docs and 100 MB in all.
- Queries scan the collection (no indexes): up to 10 `where` clauses, `in`/`not-in` arrays of at
  most 30, at most one `order_by`. Keep queried collections to low thousands of docs.
- Writes are last-writer-wins. Pass `if_version` (the version you last read) to refuse a write
  when someone changed the doc in between.
- Shared data is untrusted; never store secrets.

## Library (preferred: nothing enters the context unless you print it)
```python
import sys; sys.path.insert(0, "<plugin>/scripts"); import lsdb
lsdb.get(url, "notes/n1")                    # {exists, data, version, updatedAt, ...}
lsdb.list_all(url, "notes")                  # [{id, data, version, updatedAt}], follows cursors
lsdb.query(url, "notes", where=[("tag", "array-contains", "x")], order_by=("t", "desc"), limit=50)
lsdb.set_doc(url, "notes/n1", {...})         # create or replace -> {version, usage}
lsdb.update_doc(url, "notes/n1", {...}, if_version=3)   # merge; doc must exist
lsdb.str_replace(url, "notes/n1", "body", "old", "new", replace_all=False)
lsdb.delete_doc(url, "notes/n1")
lsdb.batch(url, [("set", "a/1", {...}), ("update", "a/2", {...}), ("delete", "a/3")])
```
`batch`: 1-50 writes in one request, each path once, request at most 1 MiB. `url` is any
artifact URL, its id or its UUID. Errors: `ValueError` (bad input), `LsdbEnvError` (no session),
`LsdbApiError` (`.status`, `.body`; status None means no reply).

## CLI
`python3 <plugin>/scripts/lsdb <cmd> URL ...`. Commands: `get PATH`, `list COLLECTION`,
`query COLLECTION [--where F OP JSON]... [--order-by F --direction asc|desc] [--limit N]`,
`set|update PATH --data JSON|--file PATH|-`, `delete PATH`, `str-replace PATH FIELD OLD NEW [--all]`,
`batch FILE` (a JSON list of `{op, path, data?, if_version?}`), `register COLLECTION`. Writes take `--if-version N`.

Reads print full JSON by default. To keep the context clean, use `--ids` (ids only, list and query) or
`--out DIR` (each doc's data to `DIR/<path>.json`, one summary line). Writes print one compact line.

Exit codes: 0 ok, 1 usage or input error, 2 API error (body on stderr), 3 not in a claude.ai/code session.

## Blobs (text larger than one doc)
`lsdb.put_blob(url, key, text, meta=None)`, `get_blob(url, key)`, `delete_blob(url, key)`; CLI
`put-blob URL KEY FILE|-` and `get-blob URL KEY [--out FILE]`. Text is split into parts under the doc
limit at `blobs/<key>/parts/<nnnn>`; the manifest `blobs/<key>` (`size, sha256, parts, meta, updatedAt`)
is written last, so a reader never sees a manifest whose parts are missing. `get_blob` checks the hash and
raises `LsdbError` on a mismatch; a shorter re-put deletes the old surplus parts. Keys are one segment
(`[A-Za-z0-9._-]`, up to 128 chars). A blob counts against the 25,000-doc and 100 MB caps.

## Behavior
- Retries no reply, 429 and 5xx twice (after 1 s, then 2 s); any other failure fails at once.
- The session token is read per call, never printed, and redirects are refused.
- Tests: `python3 -m pytest <plugin>/scripts/lsdb/tests` (set `LSDB_TEST_URL` to a store for the
  live round-trip).
