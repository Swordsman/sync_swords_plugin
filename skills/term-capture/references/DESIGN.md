# term_capture — Design Spec

Orientation document for how this project should be structured and how the
pieces fit together. Companion to `README.md`, which describes current state;
this file describes the *target* state.

---

## 1. Purpose

`term_capture` is a control plane for interactive AI CLI tools (Claude Code,
Aider, Kimi, etc.). It wraps those tools so that another process — human or
agent — can observe, coordinate, and intervene without modifying the tools
themselves.

Two products live in this repo:

| Product   | Audience                    | Interface            | Status     |
| --------- | --------------------------- | -------------------- | ---------- |
| `ai-coop` | End users, shell scripts    | CLI (tmux-backed)    | Production |
| `ai-hv`   | Python integrators, daemons | Python API + `ai-hv` | Framework  |

`ai-coop` is what you run to *get work done today*. `ai-hv` is the library it
(eventually) sits on top of. Today they're parallel tracks; the design goal is
to make `ai-coop` a thin front-end over `ai-hv`.

---

## 2. Guiding Principles

1. **Passive observation first.** The default interaction with a tool is to
   read its screen — never patch its binary, inject into its address space, or
   intercept its credentials.
2. **Standard Unix mechanisms only.** PTYs, PATH, env vars, Unix sockets,
   DEBUG traps. Anything that would require root, a kernel module, or
   ptrace is out of scope.
3. **Declarative over imperative.** Tool-specific behavior (what counts as a
   prompt, where the token counter lives, which lines are spinner noise) lives
   in s-expression rule files, not Python.
4. **One way to do each thing.** No v1/v2 parallel implementations in the
   tree; no eight coordination scripts that each reinvent the message bus.
5. **Local-first.** No required cloud service. A single laptop with tmux and
   Python 3.12 is the baseline environment.

---

## 3. Architecture

```
                    ┌────────────────────────┐
                    │       ai-coop (CLI)    │
                    │   do / status / wait   │
                    └───────────┬────────────┘
                                │ uses
                    ┌───────────▼────────────┐
                    │   ai_hypervisor (lib)  │
                    │     Hypervisor class   │
                    └─┬────────┬──────────┬──┘
                      │        │          │
           ┌──────────▼──┐ ┌───▼────┐ ┌───▼────┐
           │  SHELL      │ │  PTY   │ │ EGRESS │
           │  cmd + fs   │ │ screen │ │ network│
           └─────────────┘ └────────┘ └────────┘
                      │        │          │
                      └────────┼──────────┘
                               │
                   ┌───────────▼────────────┐
                   │   Wrapped AI CLI tool  │
                   │   (claude, aider, …)   │
                   └────────────────────────┘
                               │
                   ┌───────────▼────────────┐
                   │  Message Bus (Unix sk) │
                   │  AgentChannel, Tasks   │
                   └────────────────────────┘
```

### Three encapsulation layers

**SHELL** — Command interception via bash/zsh DEBUG trap and preexec hooks.
Tracks what the wrapped tool actually ran, provides optional filesystem
overlays (passthrough / synthetic `/ai/*` / overlay workspace).

**PTY** — Spawn the tool in a pseudo-terminal. Maintain a 2D screen buffer
reconstructed from ANSI sequences, plus a scrollback commit log. This is the
primary sense organ. Supports input injection for context management.

**EGRESS** — Network observation via proxy configuration. Host allowlist,
bandwidth tracking. Stub-only for now and deliberately lowest priority —
most target tools resist interception and the value-to-effort ratio is poor.

### Rule engine (cross-cutting)

The PTY layer consumes s-expression rule files (`rules/*.sexpr`). Rules
define:
- scrollback-ignore patterns (spinner frames, transient UI)
- screen-capture extractions (token counts, cost, prompts)
- per-tool profiles with `(inherit …)`

This is the *primary* customization surface. New tool support means a new
`.sexpr` file, not new Python. Heartbeats and liveness belong in the protocol
layer (ACP), never as a replacement for the rule engine.

### Message bus (cross-cutting)

`message_bus.py` provides an async Unix-socket bus with `AgentChannel` and
`CooperativeTask`. Any multi-agent coordination — Claude talking to Kimi,
status daemons, external watchers — goes through this bus. There should be
exactly one bus implementation in the tree.

---

## 4. Ideal File Layout

```
term_capture/
├── README.md              # what this is + quick start
├── DESIGN.md              # this file
├── INVENTORY.md           # component map (kept current)
├── setup.py               # package metadata
├── pyproject.toml         # build config, ruff/pytest
├── .gitignore             # __pycache__, logs/, *.pyc
│
├── ai_hypervisor/         # the library
│   ├── __init__.py
│   ├── __main__.py        # python -m ai_hypervisor
│   ├── cli.py             # ai-hv CLI
│   ├── hypervisor.py      # Hypervisor context manager
│   │
│   ├── layers/
│   │   ├── pty.py         # (was pty_layer_v2.py)
│   │   ├── shell.py
│   │   ├── egress.py
│   │   └── shell_hooks.sh
│   │
│   ├── rules/
│   │   ├── engine/
│   │   │   ├── sexp.py
│   │   │   └── pattern_lang.py
│   │   ├── default.sexpr
│   │   ├── claude.sexpr
│   │   └── aider.sexpr
│   │
│   ├── bus/
│   │   ├── message_bus.py
│   │   ├── channel.py
│   │   └── task.py
│   │
│   ├── protocols/
│   │   ├── bridge.py      # stdio interception
│   │   ├── mcp.py
│   │   └── acp.py         # heartbeat lives here
│   │
│   ├── input_predictor.py
│   ├── extensions.py
│   │
│   └── tools/
│       ├── ai-coop        # working tmux CLI
│       └── irc-join
│
├── tests/
│   ├── test_hypervisor.py
│   ├── test_pty.py
│   ├── test_rules.py
│   └── test_bus.py
│
└── docs/
    ├── ai-coop.md         # user guide
    ├── ai-hv.md           # framework guide
    └── rules.md           # s-expression reference
```

Key simplifications vs. today:
- `pty_layer.py` (v1) is gone; v2 becomes `layers/pty.py`.
- Layers live in `layers/`, rules in `rules/`, bus in `bus/`.
- All 18 loose top-level experiment scripts are gone — their useful parts
  either moved into the library or into `docs/` as worked examples.
- `ai-coop` becomes a tool *inside* the package, not a sibling of the
  library it depends on.

---

## 5. Entry Points

| Command                                | Purpose                               |
| -------------------------------------- | ------------------------------------- |
| `ai-coop do "<task>"`                  | Fire-and-forget task to an agent      |
| `ai-coop status` / `wait` / `results`  | Inspect running / finished sessions   |
| `ai-coop send` / `poll`                | Interactive I/O with a running agent  |
| `ai-coop attach` / `stop` / `clean`    | Tmux management                       |
| `python -m ai_hypervisor run <tool>`   | Wrap a tool with the hypervisor       |
| `python -m ai_hypervisor status`       | Inspect hypervisor state              |

Python library surface (what integrators import):

```python
from ai_hypervisor import Hypervisor, HypervisorConfig
from ai_hypervisor.bus import AgentChannel, CooperativeTask
from ai_hypervisor.rules import load_profile
```

That's the whole public API. Everything else is internal.

---

## 6. Extensibility

Three sanctioned extension points, in order of preference:

1. **Write a `.sexpr` profile.** Covers 80% of "I want to support a new
   tool" cases.
2. **Register an `Extension`** via `extensions.py` for custom screen-change
   reactions, budget limits, auto-responses.
3. **Subclass `Hypervisor`** only when the above don't fit. This should be
   rare and reviewed.

Anything that would require forking a layer module is a signal that the
layer's API is wrong — fix the API, don't fork.

---

## 7. Non-Goals

- Running untrusted AI tools in a security sandbox. This is a coordination
  layer, not a sandbox.
- Cross-platform Windows support. WSL2 is fine; native Windows is not.
- Replacing tmux. `ai-coop` uses tmux because tmux is good at what it does.
- Becoming a cloud service, a daemon with a REST API, or a GUI.
- Competing with MCP/ACP. We *speak* those protocols; we don't invent a new
  one.

---

## 8. Open Questions

These are unresolved and worth a decision before the cleanup lands:

1. **Is `ai-coop` rewritten on top of `ai-hv`, or do they stay parallel?**
   Target is "rewritten on top," but that's a multi-week job. In the
   meantime they share the repo and duplicate some PTY handling.
2. **Does EGRESS earn its keep?** Currently a stub. If it stays a stub for
   another six months, delete it and update the three-layer pitch to two.
3. **Rule-file discovery.** Should profiles ship with the package, live in
   `~/.config/ai-hv/rules/`, or both (with user rules overriding)? Target:
   both, with explicit precedence.
4. **Heartbeat placement.** README asserts heartbeats belong in
   `protocols/acp.py`. Confirm this holds once heartbeats are actually
   implemented — don't let them leak into the PTY layer.

---

## 9. Definition of "Cleaned Up"

The cleanup is done when:

- [ ] Zero `__pycache__` or `logs/` directories tracked.
- [ ] No loose `.py` files at `term_capture/` root except `setup.py`.
- [ ] Exactly one PTY implementation.
- [ ] Exactly one message-bus implementation.
- [ ] `ai-coop` is a tool inside the package.
- [ ] `INVENTORY.md` matches reality.
- [ ] `pytest` from the repo root runs green.
- [ ] A new contributor can read `README.md` + `DESIGN.md` and know where
      to put new code without asking.
