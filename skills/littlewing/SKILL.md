---
name: littlewing
description: "Session recorder and context bridge. Records live Claude Code sessions as raw JSONL and/or winnow (.wno) records to configurable storage (local disk, git repo, rclone remotes such as Google Drive, Claude Docs), generates context bridges between sessions, decomposes session JSONL into navigable directory trees, and provides overlay-based compression for cross-session continuity. Use when the littlewing hook asks for queued records to be uploaded, or when setting up, checking, or restoring session recordings."
---

# littlewing

Session recording, archival, and cross-session context bridging.

## Core capabilities

- **Recording**: plugin hooks ship the live session through two independent modes, raw JSONL and winnow records, each to its own storage
- **Context bridge**: compressed dialogue from prior sessions, for continuity without re-explanation
- **Explode**: decomposes session JSONL into a navigable directory tree (session / segments / messages) with verbatim raw preservation and derived views
- **Overlays**: pyramid compression via separate model calls, producing progressively smaller summaries
- **Formats**: markdown, JSON, JSONL, s-expression, mermaid, plain text, winnow transcript

## Recording modes

Both are off until configured. They switch on separately:

| Mode | Ships | Pieces |
|---|---|---|
| `raw` | the session JSONL itself | contiguous byte ranges, xz-compressed; joined in order they rebuild the log byte for byte |
| `wno` | a winnow record (`scripts/winnow/winnow.py`) | part 1 is a full `.wno` log, later parts are new deltas only; joined in order they give the whole record |

Each run sends only what's new since the last one. winnow sees only turns that can't change any more, numbered from the start of the session, and each run is seeded with the record so far.

## Storage (sinks)

| Transport | Who writes it | Notes |
|---|---|---|
| `local` | the hook | default sink `disk`: `~/.littlewing/records` |
| `git` | the hook | any checkout; `url` clones it on first use, `auto_push` pushes each commit |
| `rclone` | the hook | Google Drive, OneDrive, S3 and 40+ others, via a configured rclone remote |
| `claude-docs` | Claude | the hook queues files in an outbox and asks Claude to upload them |

Transforms per mode: raw gets `xz`, plus `base85` text armor on text-only sinks (Claude Docs): 25% of raw size at xz preset 9 on one measured session, a little more at the default preset 6. A `.wno` stays plain text. Set `transforms` on a mode to add `age` or `pqc` encryption or use `gzip` instead.

## Configuration

Layers, later wins: built-in defaults, `~/.config/littlewing/config.json`, the repo's `.littlewing.json`, `$LITTLEWING_CONFIG`, `$LITTLEWING_CONFIG_JSON` (inline JSON, the easy route in cloud environments), then these shortcuts:

| Variable | Effect |
|---|---|
| `LITTLEWING_RAW` | `off`, `on`, or a sink name: switches raw mode on with that sink |
| `LITTLEWING_WNO` | the same for winnow records |
| `LITTLEWING_DOCS` | comma-separated Claude Docs urls; defines sink `docs` |
| `LITTLEWING_HOME` | state, outbox and local records root (default `~/.littlewing`) |

Example, both modes to one Claude Docs records doc:

```
LITTLEWING_RAW=docs
LITTLEWING_WNO=docs
LITTLEWING_DOCS=https://claude.ai/code/artifact/<doc-id>
```

Example config file, raw to a private git repo, records to Claude Docs:

```json
{
  "modes": {
    "raw": {"enabled": true, "sink": "archive"},
    "wno": {"enabled": true, "sink": "docs", "model": "flash"}
  },
  "sinks": {
    "archive": {"transport": "git", "root": "~/session-archive", "auto_push": true,
                "url": "git@github.com:you/session-archive.git"},
    "drive":   {"transport": "rclone", "remote": "gdrive", "path": "littlewing"},
    "docs":    {"transport": "claude-docs", "docs": ["https://claude.ai/code/artifact/<doc-id>"]}
  }
}
```

`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py config` prints the effective config and the files it read.

winnow runs at max thinking effort (`"think": "max"` on the wno mode, the default; don't lower it). That's slow on dense turns, so the hooks allow two hours and the recorder keeps whatever finished if a run is cut short. winnow's `deepseek` backend runs `scripts/winnow/ds`, which needs the `openai` Python package (`pip install openai`) and exits unless `DEEPSEEK_API_KEY` is set. Where a proxy injects the real credential, as in Claude Code cloud environments with DeepSeek connected, a placeholder works: `"env": {"DEEPSEEK_API_KEY": "proxy"}` on the wno mode.

## Triggers

| Trigger | Hook | What ships |
|---|---|---|
| `push` | PostToolUse on Bash `git push` | everything new |
| `pr` | PostToolUse on PR creation (`gh pr create`, GitHub MCP) | everything new |
| `stop` | Stop, after each reply (the backup) | hook-written sinks: everything new; Claude Docs: only past `queued_min_bytes` (1 MiB) or `queued_min_turns` (20 replies) |
| `compact` | PreCompact | everything new; never wakes Claude |
| `session_end` | SessionEnd | everything new, from a detached child process |
| `session_start` | SessionStart | nothing; lists uploads still queued |

Each is switched under `triggers` in the config. A Claude Docs upload left after the last trigger is lost in a cloud container, which is discarded at session end; on a local machine the next session's start lists it.

The hooks run in the background (`asyncRewake`): when records are queued, the hook exits 2 and its message wakes Claude, even when the session is idle. A queued record is announced once, then again every `renotify_minutes` (60) until it's marked sent.

## Uploading queued records

When the hook's message says records are queued for Claude Docs, for each file it lists:

1. Upload it to the first doc listed: Artifact tool, publish with `url=<doc>`, `file_path=<file>`, `asset: true`. If the doc is full (1 GiB or 5,000 uploads), use the next doc listed; if none is left, tell the user.
2. Index it: add a row to that doc's index table (Date | Repo | Log id | Record | Asset id | What it covers). Raw pieces go in a table on a tab named Raw, created on first use. If the doc's own convention also registers uploads as blobs, do that too.
3. Mark it sent: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py outbox done <id> --asset <asset id>`, adding `--doc <url>` when it went to a doc other than the first.

Then carry on with whatever you were doing. A sink's `steps` list in the config replaces these steps with the doc owner's own.

`littlewing.py outbox` lists what's queued, `outbox sent` what's done, and `outbox notice` prints the hook's message again.

## Restoring

```
littlewing.py restore <pieces or directories> -o session.jsonl     # raw log, byte for byte
littlewing.py restore <pieces> --into-archive                      # into the archive for list/bridge/search
littlewing.py restore p0001_t1-t9.wno p0002_t10-t20.wno -o record.wno
```

**Generations.** Claude Code rewrites a session's log when a container restarts (new path, every line changed), so saved offsets stop lining up. Each mode keeps a fingerprint of what it already shipped: raw the hashes of the log's first 4 KB and of the 4 KB before its offset, wno the hash of the last turn it recorded. When the fingerprint no longer matches, that mode starts a new generation (`g2/`, `g3/`, ...) from the top. A raw generation restores to a whole log by itself; `restore` picks the newest, `--generation N` another. wno only starts over when the turns themselves changed: a rewrite that keeps the conversation identical (the usual case) continues the same record.

Raw pieces carry their storage key in the base85 header, so files downloaded from Claude Docs under asset-id names still sort and verify. `.wno` parts need their names, from the index row; otherwise they're joined in the order given.

## Other commands

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py record [--session <id>] [--final]
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py bridge --project <name> -o /tmp/bridge.md
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py bridge --project <name> --enhance -o /tmp/bridge.md
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py list
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py conversation <session-id> --format winnow
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/explode.py <session.jsonl> <output-dir>
```

`ingest`, `list`, `bridge`, `search` and `overlay` work on the archive, `{home}/archive` unless `archive` points elsewhere.

## Scripts

All in `${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/`: `littlewing.py` (CLI), `littlewing_hook.py` (every hook event), `recorder.py`, `lwconfig.py`, `transcript.py`, `backends/` (transports + transforms), `formats/`. Tests: `python3 -m unittest discover -s scripts/littlewing/tests`.
