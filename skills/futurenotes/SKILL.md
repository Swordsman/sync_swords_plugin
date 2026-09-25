# futurenotes

Session watcher daemon that extracts FutureNotes tags from Kimi CLI sessions.

## What it does

Tails Kimi CLI session files for `<FutureNotes>...</FutureNotes>` tags in assistant output, extracts and deduplicates them (SHA-256), and persists to `notes.md` (append-only markdown) and `notes.db` (SQLite).

## Usage

```bash
# Start the daemon
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/futurenotes_daemon.py [--poll-interval 5] [--session-dir ~/.kimi/sessions]

# Notes are written to:
#   notes.md  — human-readable append-only log
#   notes.db  — SQLite (id/timestamp/content/status/content_hash)
```

## Note lifecycle

Notes in the database carry a status: `pending` → `active` → `done`. Claude can query/update status directly in `notes.db`.

## Location

Script: `${CLAUDE_PLUGIN_ROOT}/scripts/futurenotes_daemon.py`

Stdlib-only Python, no dependencies.

## Source

[Swordsman/futurenotes](https://github.com/Swordsman/futurenotes)
