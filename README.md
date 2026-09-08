# sync_swords_plugin

A self-syncing plugin carrying three skills sourced from their upstream repos:

- **aimpack** — AI MimePack: munpack-compatible MIME containers for LLM workflows. Plaintext-readable file packaging with linear edit history, S-expression instructions, and an extension system.
- **winnow** — Streaming semantic distillation for AI conversations. S-expression delta protocol over a typed semantic graph with bounded-context extraction.
- **context-window-washing** — Surface everything unsurfaced in your context window. A full-context scan that names every neglected, forgotten, or underconsidered item, then categorizes findings into actionable slots.

## How the sync works

The plugin carries its own sync machinery (`scripts/sync.py`, stdlib-only
Python). Behavior is gated by one environment variable:

- **`SWORDS_AUTO_SYNC=1` set** — every session start (on hook-capable
  platforms) fast-forward-pulls the repo. New code is live next session.
- **Unset** — the hook/skill only *reports* drift and stays read-only.

It never force-pulls, never commits, never pushes. Divergence is reported,
not auto-resolved.

## Upstream sources

| Skill | Source repo |
|---|---|
| aimpack | [Swordsman/aimpack](https://github.com/Swordsman/aimpack) |
| winnow | [Swordsman/winnow](https://github.com/Swordsman/winnow) |
| context-window-washing | [Swordsman/cbtdag](https://github.com/Swordsman/cbtdag) (wash.md) |

## Install per platform

| Platform | Install | Auto-sync source |
|---|---|---|
| Claude Code (local) | `/plugin marketplace add Swordsman/sync_swords_plugin`, install, enable auto-update | marketplace auto-update + bundled SessionStart hook |
| claude.ai / Cowork | add repo as plugin source | account sync re-fetches per session |
| Gemini CLI | `gemini extensions install <repo-url> --auto-update` | native `--auto-update` |
| Cursor | import repo as team marketplace, enable Auto Refresh | native Auto Refresh |
| Others (Codex, OpenCode, ...) | clone repo, point skills dir at it | run the sync skill (or hook where available) |

## Layout

```
.claude-plugin/plugin.json       plugin manifest
.claude-plugin/marketplace.json  makes this repo directly addable as a marketplace
hooks/hooks.json                 SessionStart drift-check / auto-pull
skills/sync/SKILL.md             skill wrapper (agent-invoked sync)
skills/aimpack/SKILL.md          aimpack skill + references/
skills/winnow/SKILL.md           winnow skill (distilled from spec)
skills/wash/SKILL.md             context-window-washing skill
scripts/sync.py                  the sync engine (stdlib-only)
scripts/aimpack.py               aimpack CLI tool
```
