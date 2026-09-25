---
name: littlewing
description: "Session flight recorder and context bridge. Archives Claude Code session transcripts, generates context bridges between sessions, decomposes session JSONL into navigable directory trees, and provides overlay-based compression for cross-session continuity."
---

# littlewing

Session recording, archival, and cross-session context bridging.

## Core capabilities

- **Recording**: Stop hook captures session JSONL to configurable backends (local, git, rclone)
- **Context bridge**: Generates compressed dialogue from prior sessions so the current session has continuity without re-explanation
- **Explode**: Decomposes session JSONL into a navigable directory tree (session / segments / messages) with verbatim raw preservation and derived views
- **Overlays**: Pyramid compression via separate model calls, producing progressively smaller summaries
- **Formats**: Output in markdown, JSON, JSONL, s-expression, mermaid, plain text

## Usage

The main CLI is `littlewing.py`. Key commands:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py bridge --project <name> -o /tmp/bridge.md
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py bridge --project <name> --enhance -o /tmp/bridge.md
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py list
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/littlewing.py show <session-id>
```

Explode a session into a directory tree:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/explode.py <session.jsonl> <output-dir>
```

The hook script (`littlewing_hook.py`) is designed for Stop hooks — it archives the current session transcript on session end.

## Backend architecture

Transports (where data goes): local filesystem, git repo, rclone remote.
Transforms (what happens to data): gzip compression, age encryption, PQC hybrid encryption.
Composed via Store orchestrator: `Store(transport, [transform1, transform2])`.

## Scripts

All scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/littlewing/`.
