# sync_swords_plugin

A plugin with twenty-six skills sourced from their upstream repos, with optional auto-update:

- **taskdagger** — Contract-Based Task DAG. Structured project decomposition that enforces design-before-build, breaks projects into contract-bound modular components proven correct before integration, and unlocks parallel builds via frozen interface contracts.
- **littlewing** — Session flight recorder and context bridge. Archives Claude Code session transcripts, generates context bridges between sessions, and decomposes session JSONL into navigable directory trees.
- **ucf** — Universal Context Format. JSONL-based interchange format for converting AI conversation transcripts between providers (Claude, DeepSeek, Kimi, Hermes, Claude Web) with lossless roundtrips and cross-format sanitization.
- **aimpack** — AI MimePack: munpack-compatible MIME containers for LLM workflows. Plaintext-readable file packaging with linear edit history, S-expression instructions, and an extension system.
- **winnow** — Streaming semantic extraction for AI conversations. S-expression delta protocol over a typed semantic graph with bounded-context extraction.
- **context-review** — Surface everything unsurfaced in your context window. A full-context scan that names every neglected, forgotten, or underconsidered item, then categorizes findings into actionable slots.
- **hearthphoenix** — Process supervisor with transactional hotswap and pluggable transports (REST, Unix socket, file heartbeat, pipe, CLI). DaemonWrapper exposes external processes through multiple protocol interfaces.
- **provider-library** — Offline LLM API documentation reference cache. Curated, pre-scraped provider docs indexed for AI-agent consumption.
- **deepseek-api** — Curated DeepSeek API reference with on-demand fragment loading and per-agent dedup.
- **xylem** — Agent terminal substrate. Shared xonsh+Hy shell over FastAPI/WebSocket for multi-agent terminal coordination.
- **tree-sprawler** — Structural analysis CLIs: json-ruleset (discriminator decision trees from JSON corpora) and tree-probe (filesystem structure profiling).
- **io-shield** — File-level write-locking and SHA-256 integrity verification for multi-agent coordination.
- **squishyatoms** — Multi-tier knowledge compression (8 levels, extended to micro) for context management and budget-constrained assembly.
- **robody** — Context state synchronization harness for parent/subagent coordination via class-level shared memory bus.
- **pie** — Procedural Inference Emulator. Deterministic state machine for agent lifecycle management with OpenAI-compatible inference endpoint.
- **futurenotes** — Session watcher daemon extracting FutureNotes tags from Kimi CLI sessions into SQLite + markdown.
- **shellcrawl** — Sandboxed virtual Linux shell for AI agent exploration and evaluation. In-memory VFS + pisces command interpreter.
- **combo-vfs** — Filesystem analysis tools: tree-abstract (UUID/hash pattern collapsing) and fuse-watcher (transparent I/O logger).
- **design-incubator** — Catalog of 18 design-phase projects (specification only) across agent architecture, data/knowledge, system infrastructure, and research.
- **term-capture** — AI CLI Coordination. Control plane for interactive AI CLI tools (Claude Code, Kimi, Aider) with PTY screen capture, shell command interception, peer mesh coordination, and the ai-coop multi-agent cooperation CLI.
- **context-clone** — Subagent context cloning. Pass essential parent context to subagents so they return signal, not noise. (Needs refactoring)
- **delegate-fileread** — Delegated file reads. Protect parent context by reading files via subagents with distilled returns. (Needs refactoring)
- **delegate-research** — Delegated research with knowledge caching. Spawn research agents that cache and index findings. (Needs refactoring)
- **token-counter** — Token count estimation for files and text. ~4 chars/token heuristic with context budget guidelines. (Needs refactoring)
- **context-hygiene** — Session health diagnostics. 6-phase context hygiene process for detecting thrashing and preparing handoffs. (Needs refactoring)

## How updates work

The plugin carries its own update machinery (`scripts/sync.py`, stdlib-only
Python). Behavior is gated by one environment variable:

- **`SWORDS_AUTO_SYNC=1` set** — every session start (on hook-capable
  platforms) pulls updates from the repo. New code is live next session.
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
| context-review | [Swordsman/cbtdag](https://github.com/Swordsman/cbtdag) (wash.md) |
| hearthphoenix | [Swordsman/hearthphoenix](https://github.com/Swordsman/hearthphoenix) |
| provider-library | [Swordsman/provider-api-library](https://github.com/Swordsman/provider-api-library) |
| deepseek-api | [Swordsman/provider-api-library](https://github.com/Swordsman/provider-api-library) (skills/deepseek-api/) |
| xylem | [Swordsman/xylem](https://github.com/Swordsman/xylem) |
| tree-sprawler | [Swordsman/tree-sprawler](https://github.com/Swordsman/tree-sprawler) |
| io-shield | [Swordsman/io-shield](https://github.com/Swordsman/io-shield) |
| squishyatoms | [Swordsman/squishyatoms](https://github.com/Swordsman/squishyatoms) |
| robody | [Swordsman/robody](https://github.com/Swordsman/robody) |
| pie | [Swordsman/pie](https://github.com/Swordsman/pie) |
| futurenotes | [Swordsman/futurenotes](https://github.com/Swordsman/futurenotes) |
| shellcrawl | [Swordsman/shellcrawl](https://github.com/Swordsman/shellcrawl) |
| combo-vfs | [Swordsman/combo-vfs](https://github.com/Swordsman/combo-vfs) |
| design-incubator | [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (design-phase projects) |
| term-capture | [Swordsman/term-capture](https://github.com/Swordsman/term-capture) |
| context-clone | [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (.agents/skills/) |
| delegate-fileread | [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (.agents/skills/) |
| delegate-research | [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (.agents/skills/) |
| token-counter | [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (.agents/skills/) |
| context-hygiene | [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (.knowledge/skills/) |

## Install per platform

| Platform | Install | Auto-update source |
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
hooks/hooks.json                 SessionStart update-check / auto-pull
scripts/sync.py                  the update engine (stdlib-only)
scripts/aimpack.py               aimpack CLI tool
scripts/multiedit.py             multiedit batch read/write tool
scripts/taskdagger-cli.py        taskdagger DAG CLI
scripts/littlewing/              session flight recorder + context bridge
scripts/ucf/                     universal context format adapters
scripts/hearthphoenix/           process supervisor package + examples
scripts/xylem/                   agent terminal substrate
scripts/tree_sprawler/           json-ruleset + tree-probe analysis CLIs
scripts/io_shield.py             file write-locking + integrity
scripts/context_atom.py          multi-tier knowledge compression
scripts/robody/                  context state synchronization harness
scripts/pie/                     procedural inference emulator
scripts/futurenotes_daemon.py    session FutureNotes extractor
scripts/shellcrawl/              sandboxed virtual shell
scripts/combo_vfs/               filesystem analysis tools
scripts/provider_download.py     provider doc re-scraper
scripts/term_capture/            AI CLI coordination + peer mesh
skills/taskdagger/               taskdagger skill + references/
skills/littlewing/               littlewing skill
skills/ucf/                      UCF skill
skills/aimpack/                  aimpack skill + references/
skills/winnow/                   winnow skill
skills/wash/                     context review skill
skills/sync/                     sync skill
skills/hearthphoenix/            hearthphoenix skill + references/
skills/provider-library/         provider library umbrella skill
skills/deepseek-api/             deepseek API skill + references/
skills/xylem/                    xylem skill
skills/tree-sprawler/            tree-sprawler skill
skills/io-shield/                io-shield skill
skills/squishyatoms/             squishyatoms skill + references/
skills/robody/                   robody skill
skills/pie/                      pie skill + references/
skills/futurenotes/              futurenotes skill
skills/shellcrawl/               shellcrawl skill
skills/combo-vfs/                combo-vfs skill
skills/design-incubator/         design-phase project catalog
skills/term-capture/             AI CLI coordination skill + references/
skills/context-clone/            subagent context cloning (needs refactoring)
skills/delegate-fileread/        delegated file reads (needs refactoring)
skills/delegate-research/        delegated research (needs refactoring)
skills/token-counter/            token estimation + script (needs refactoring)
skills/context-hygiene/          session health diagnostics (needs refactoring)
```
