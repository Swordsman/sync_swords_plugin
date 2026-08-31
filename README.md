# sync_swords_plugin

A self-syncing plugin. Point any supported platform at this repo once; from
then on it keeps itself current — no manual pulls, no sync hacks.

## How the sync works

The plugin carries its own sync machinery (`scripts/sync.py`, stdlib-only
Python). Behavior is gated by one environment variable:

- **`SWORDS_AUTO_SYNC=1` set** → every session start (on hook-capable
  platforms) fast-forward-pulls the repo. New code is live next session.
随你- **Unset** → the hook/skill only *reports* drift and stays read-only.

It never force-pulls, never commits, never pushes. Divergence is reported,
not auto-resolved.

## Install per platform

| Platform | Install | Auto-sync source |
|---|---|---|
| Claude Code (local) | `/plugin marketplace add Swordsman/sync_swords_plugin`, install, enable auto-update | marketplace auto-update + bundled SessionStart hook |
| claude.ai / Cowork | add repo as plugin source | account sync re-fetches per session |
| Gemini CLI | `gemini extensions install <repo-url> --auto-update` | native `--auto-update` |
| Cursor | import repo as team marketplace, enable Auto Refresh | native Auto Refresh |
| Others (Codex, OpenCodeAREA, ...) | clone repo, point skills dir at it | run the sync skill (or hook where available) |

## Layout

```
.claude-plugin/plugin.json       plugin manifest
.claude-plugin/marketplace.json  makes this repo directly addable as a marketplace
hooks/hooks.json                 SessionStart drift-check / auto-pull
skills/sync/SKILL.md             skill wrapper (agent-invoked sync)
scripts/sync.py                  the sync engine (stdlib-only)
```
