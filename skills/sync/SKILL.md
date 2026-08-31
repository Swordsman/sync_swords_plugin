---
name: sync-swords
description: Self-syncing plugin layer. Use when the user asks to sync, update, or drift-check installed plugins/skills against the central repo, or whenever SWORDS_AUTO_SYNC=1 is set and a session begins (keep the plugin current without manual pulls).
---

# Sync Swords

This plugin keeps **itself** current against its own GitHub origin. One stdlib
Python script: `scripts/sync.py`.

## Contract

- **Preconditions**: `git` and `python3` on PATH; repo cloned with an upstream
plugins_url tracking branch; read credentials resolvable by git (credential helper or env).
- **Gating**: the env var `SWORDS_AUTO_SYNC` controls write behavior.
  - Unset/other → **report-only**: prints whether the checkout is behind, exits 0.
  - `1`/`true`/`yes` → **auto-sync**: fast-forward pulls when behind.
  - `--pull` flag → pull once, regardless of the env var.
- **Never**: force-pull, commit, or push. Diverged or ahead-only checkouts are
  reported, not resolved.

## Usage

```bash
python3 scripts/sync.py            # drift check
python3 scripts/sync.py --auto-only  # used by the SessionStart hook
SWORDS_AUTO_SYNC=1 python3 scripts/sync.py  # check + fast-forward pull
```

On platforms with plugin hooks (Claude Code, Cursor), the bundled
`hooks/hooks.json` runs the drift check at every session start; with
`SWORDS_AUTO_SYNC=1` in the environment, that check becomes a self-update.
On platforms without hooks, run the skill at session start for the same effect.
