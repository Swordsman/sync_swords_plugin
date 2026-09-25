# sync_swords_plugin

A self-syncing plugin carrying seven skills sourced from their upstream repos:

- **taskdagger** — Contract-Based Task DAG. Structured project decomposition that enforces design-before-build, breaks projects into contract-bound modular components proven correct before integration, and unlocks parallel builds via frozen interface contracts.
- **littlewing** — Session flight recorder and context bridge. Archives Claude Code session transcripts, generates context bridges between sessions, and decomposes session JSONL into navigable directory trees.
- **ucf** — Universal Context Format. JSONL-based interchange format for converting AI conversation transcripts between providers (Claude, DeepSeek, Kimi, Hermes, Claude Web) with lossless roundtrips and cross-format sanitization.
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
| taskdagger | [Swordsman/cbtdag](https://github.com/Swordsman/cbtdag) |
| littlewing | [Swordsman/flight-recorder](https://github.com/Swordsman/flight-recorder) |
| ucf | [Swordsman/universal-context-format](https://github.com/Swordsman/universal-context-format) |
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
scripts/sync.py                  the sync engine (stdlib-only)
scripts/aimpack.py               aimpack CLI tool
scripts/multiedit.py             multiedit batch read/write tool
scripts/taskdagger-cli.py        taskdagger DAG CLI
scripts/littlewing/              session flight recorder + context bridge
scripts/ucf/                     universal context format adapters
skills/taskdagger/SKILL.md       taskdagger skill + references/
skills/littlewing/SKILL.md       littlewing skill
skills/ucf/SKILL.md              UCF skill
skills/aimpack/SKILL.md          aimpack skill + references/
skills/winnow/SKILL.md           winnow skill
skills/wash/SKILL.md             context-window-washing skill
skills/sync/SKILL.md             sync skill
```
