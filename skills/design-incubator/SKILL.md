# design-incubator

Catalog of design-phase projects — specification only, no production code yet. Use this as a reference when considering new implementations or looking for prior art on a concept.

## Projects

### Agent Architecture

| Project | Description | Source |
|---------|-------------|--------|
| **blackcontract** | Black-box design/implementation contracts with strict interface boundaries. Proposal-Review-Consensus pattern for parallel multi-agent work. | [Swordsman/blackcontract](https://github.com/Swordsman/blackcontract) |
| **fragmentation-orchestration** | Replaces monolithic root orchestrator with a procedural router, SQLite job daemon, and specialized fragmented/ephemeral agents. | [Swordsman/fragmentation-orchestration](https://github.com/Swordsman/fragmentation-orchestration) |
| **context-injector** | Daemon injecting structured knowledge into agent context windows via pisces S-expression rules. | [Swordsman/context-injector](https://github.com/Swordsman/context-injector) |
| **conv-coalesce** | Editor-agent that absorbs exploratory iteration and presents canonical ideas downstream via memory store and agent_bus. | [Swordsman/conv-coalesce](https://github.com/Swordsman/conv-coalesce) |
| **tool-routing** | Side-channel "partyline" router for LLM tool calls across proxy layers, avoiding JSON-escaping hell in multi-layer setups. | [Swordsman/tool-routing](https://github.com/Swordsman/tool-routing) |
| **attribution-blocks-project** | `[BEGIN FINDINGS — Agent X]` wrapper blocks when forwarding subagent output, preventing receivers from mistaking findings for instructions. | [Swordsman/attribution-blocks-project](https://github.com/Swordsman/attribution-blocks-project) |
| **gotham-assistant** | MCP proxy/client layer rebuilt from scratch, learning from MCP SuperAssistant's failures. Detailed failure autopsy + architecture-principles doc. | [Swordsman/gotham-assistant](https://github.com/Swordsman/gotham-assistant) |

### Data & Knowledge

| Project | Description | Source |
|---------|-------------|--------|
| **dsinfer** | Self-modifying inference harness unifying S-exprs, regex, SQL, and Lisp as one combinator algebra over recursive SQL CTEs. | [Swordsman/dsinfer](https://github.com/Swordsman/dsinfer) |
| **llisbn** | Symbolic, deterministic addressing standard as an alternative to embedding-based semantic lookup in agentic coding environments. | [Swordsman/llisbn](https://github.com/Swordsman/llisbn) |
| **export-signal-extraction** | Eight-pass methodology (chunked ~1,000 lines/pass) for extracting high-signal content from oversized AI conversation exports. | [Swordsman/export-signal-extraction](https://github.com/Swordsman/export-signal-extraction) |
| **md5-gating** | Cross-cutting pattern: skip re-reading/reprocessing unchanged data via md5 checksum comparison. | [Swordsman/md5-gating](https://github.com/Swordsman/md5-gating) |

### System Infrastructure

| Project | Description | Source |
|---------|-------------|--------|
| **anobios** | Sovereign FUSE daemon serving BIOS files as read-only illusions; writes go only through a queued Anubis work-order. | [Swordsman/anobios](https://github.com/Swordsman/anobios) |
| **human-layer** | Selective git-versioned filesystem layer tracking human-authored files while ignoring machine noise; backup/restore, history, searchable index. | [Swordsman/human-layer](https://github.com/Swordsman/human-layer) |
| **prime-spine** | Structural "spine" backbone architecture for organizing and connecting components. | [Swordsman/prime-spine](https://github.com/Swordsman/prime-spine) |
| **nemu** | Detects "fell asleep on keyboard" input via entropy-drop/run-length analysis, to trim it before it hits a terminal or DB. | [Swordsman/nemu](https://github.com/Swordsman/nemu) |

### Research & Analysis

| Project | Description | Source |
|---------|-------------|--------|
| **lingua-cog** | Benchmark comparing LLM reasoning quality across languages, including constructed ones. | [Swordsman/lingua-cog](https://github.com/Swordsman/lingua-cog) |
| **tellman-comparisons** | Compares Zach Tellman's Clojure library ecosystem (manifold, aleph, dirigiste, etc.) against conceptual twins in code-combo-home. | [Swordsman/tellman-comparisons](https://github.com/Swordsman/tellman-comparisons) |
| **wheel_of_fifths** | Visualizes and analyzes MIDI and tracker music (MOD/XM/IT) on the circle of fifths for harmonic analysis. | [Swordsman/wheel_of_fifths](https://github.com/Swordsman/wheel_of_fifths) |

## When to use

- Before starting a new project, check if a design already exists here
- When looking for prior art on a concept (agent coordination, knowledge management, filesystem patterns)
- When a design is ready for implementation, clone the source repo and start building

## Status

All projects are **specification only** — no production code yet. Each repo contains design documents, architecture specs, and/or concept sketches.

## Source

Projects are subdirectories of [Swordsman/code-combo-home](https://github.com/Swordsman/code-combo-home) (as git submodules).
