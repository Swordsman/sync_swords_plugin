# term-capture

AI CLI Hypervisor — control plane for interactive AI command-line tools.

## What it does

Wraps AI CLI tools (Claude Code, Kimi, Aider, etc.) in a three-layer
encapsulation framework for observation, coordination, and control:

- **PTY Layer** — 2D screen buffer with scrollback commit log, ANSI
  parsing, per-tool profiles via S-expression rules
- **SHELL Layer** — Command interception via bash/zsh DEBUG trap,
  command history tracking, filesystem virtualization
- **EGRESS Layer** — Network monitoring, host allowlist/blocklist,
  bandwidth tracking (framework)

Two products:

1. **`ai-coop`** — Working multi-agent cooperation CLI. Fire tasks to
   AI agents via tmux, check results later. Commands: `do`, `status`,
   `wait`, `results`, `send`, `poll`, `attach`, `stop`, `clean`.
2. **`ai-hv`** — Python hypervisor framework. PTY and SHELL layers
   implemented, EGRESS is a stub. Experimental.

Plus a **peer-mesh** system — hypervisor-native P2P mesh of AI CLIs
communicating via a central broker over persistent bidirectional bus
connections. Tmux is an optional display layer.

## Usage

```bash
# ai-coop: fire a task
${CLAUDE_PLUGIN_ROOT}/scripts/term_capture/ai_hypervisor/ai-coop do "build a website" --yolo

# ai-coop: check status
${CLAUDE_PLUGIN_ROOT}/scripts/term_capture/ai_hypervisor/ai-coop status

# Hypervisor: run Claude under monitoring
python -m ai_hypervisor.cli run claude

# Peer mesh: start broker + participants
${CLAUDE_PLUGIN_ROOT}/scripts/term_capture/start_mesh.sh
```

## Key components

| Component | File | Purpose |
|-----------|------|---------|
| AIHypervisor | `ai_hypervisor/hypervisor.py` | Main coordinator |
| PTYLayerV2 | `ai_hypervisor/pty_layer_v2.py` | 2D screen buffer + scrollback |
| ShellLayer | `ai_hypervisor/shell_layer.py` | Command interception |
| EgressLayer | `ai_hypervisor/egress_layer.py` | Network monitoring |
| MessageBus | `ai_hypervisor/message_bus.py` | Async Unix socket bus |
| Broker | `ai_hypervisor/broker.py` | Mesh message router |
| SExpParser | `ai_hypervisor/sexp.py` | S-expression rule parser |
| PatternCompiler | `ai_hypervisor/pattern_lang.py` | Pattern → regex compiler |
| ProtocolBridge | `ai_hypervisor/protocol_bridge.py` | MCP/ACP interception |
| ai-coop | `ai_hypervisor/ai-coop` | Multi-agent cooperation CLI |

## S-expression rule engine

Tool-specific behavior (prompt detection, token counter location,
spinner noise filtering) is declarative via S-expression files in
`ai_hypervisor/rules/`. Profile inheritance via `(inherit <name>)`.

## Protocols

- **MCP** (Model Context Protocol) — JSON-RPC 2.0 over stdio
- **ACP** (Agent Communication Protocol) — REST/HTTP message bus

## Requirements

- Python 3.10+
- Linux or macOS
- tmux (for ai-coop and mesh display)
- Standard library only (no external runtime dependencies)

## Location

Package: `${CLAUDE_PLUGIN_ROOT}/scripts/term_capture/ai_hypervisor/`
Mesh scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/term_capture/`

## Source

[Swordsman/term-capture](https://github.com/Swordsman/term-capture)
