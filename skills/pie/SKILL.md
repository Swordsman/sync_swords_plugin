# pie

Procedural Inference Emulator — deterministic state machine for agent lifecycle management.

## What it does

Manages agent lifecycle (spawn/suspend/resume/clone/split), gates content access, and presents as an OpenAI-compatible inference endpoint. Composes recursively.

## Components

| Module | Purpose |
|--------|---------|
| `pie.py` | Core state machine with CLI: spawn/list/suspend/resume/status |
| `agent.py` | Universal Agent Format library (Agent, AgentManifest, Context, Turn, runtimes) |
| `mimepack.py` | Standalone CLI for context-optimized file packaging/dedup for LLM workflows |

## Usage

```bash
# PIE state machine
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pie/pie.py spawn --name myagent
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pie/pie.py list
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pie/pie.py status myagent

# MimePack (independent tool)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pie/mimepack.py pack <files...>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pie/mimepack.py unpack <archive>
```

## Location

Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/pie/`

## Source

[Swordsman/pie](https://github.com/Swordsman/pie)
