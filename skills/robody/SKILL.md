# robody

Context-window mirroring harness for parent/subagent state synchronization.

## What it does

Provides class-level shared memory ("bus") so a root agent and its subagents can mirror/sync state across separate context windows without triggering compaction.

## Components

| Module | Purpose |
|--------|---------|
| `robody.py` | Core Robody class, Orchestrator (spawn/terminate/broadcast/hot-swap), view filters, path-jail security |
| `robody_memory.py` | MemorySegment/MemoryPool/MemoryManager with public/shared/private tiers and pluggable eviction |
| `context_atom.py` | 8-tier self-compressing knowledge units (extended→micro) with per-tier token budgets |

## Status

Bus + memory-tier layers are built and working. KnowledgeAtom LOD compression, GoalGraph, and ContextWindow viewport are designed but not yet implemented.

## Location

Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/robody/`

## Source

[Swordsman/robody](https://github.com/Swordsman/robody)
