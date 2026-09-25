THIS DOCUMENT IS CURRENT AS OF 04/27/2026. THIS DOCUMENT MAY BE OUTDATED OR OBSOLETE PAST THAT DATE. IF YOU'RE LOOKING FOR A SOURCE OF TRUTH, READ THE CODE, 'CAUSE THIS AIN'T IT. IF A FILE WITH A FUTURE CTIME/MTIME CONFLICTS WITH THINGS SAID IN THIS FILE, PREFER THE FILE WITH THE NEW TIMESTAMP ON IT. OBVIOUSLY.

---

# Peer Mesh Architecture

> **What this is:** A hivemind control and communication layer for AI CLI tools. It is not a generic message bus. It is purpose-built to let AI agents observe, drive, and coordinate each other's terminal sessions.

---

## Core Purpose & Design Intent

The peer mesh exists for one reason: **AI agents need to read, write, and take control of CLI/TUI sessions** — their own and each other's. Human operators watch screens and type commands; this system gives AIs the same capability programmatically.

Specifically, it enables:

| Capability | What it means |
|---|---|
| **Read** | An AI watches its own CLI output (or another AI's output) as structured screen/scrollback data, not just raw ANSI streams. |
| **Write** | An AI injects keystrokes or commands into a running CLI session as if a human typed them. |
| **TUI → stdio abstraction** | The PTY layer reconstructs screen state and strips transient UI (spinners, progress bars), turning terminal apps into programmatic interfaces. |
| **Multi-agent linkage** | Multiple AI CLI sessions (Kimi, Claude, etc.) register on a shared bus and exchange messages. |
| **"Take the wheel" (remote)** | One AI can send a message to another AI's session; the target AI receives it as injected input and replies with captured output. |
| **"Take the wheel" (self)** | An AI can programmatically drive its own CLI tool rather than passively observing it. |

The broker is **dumb pipe-fitting** by design. All routing intelligence lives in the participants or in future router agents. The broker only knows how to look up a name in a registry and either broadcast to native clients or push keys into a tmux pane.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Native OS processes (no tmux session wrapper)              │
│  ┌────────────────────┐  ┌────────────────────┐             │
│  │ mesh_claude.py     │  │ mesh_kimi.py       │             │
│  │ (BusClient + PTY)  │  │ (BusClient + PTY)  │             │
│  └─────────┬──────────┘  └──────────┬─────────┘             │
└────────────│────────────────────────│───────────────────────┘
             │  persistent Unix socket│
             ▼                        ▼
     ┌───────────────────────────────────────┐
     │  broker.py                            │
     │  - participant Registry (in-mem, TTL) │
     │  - routes send → tmux send-keys       │
     │  - polls capture-pane for output      │
     └───────────────┬───────────────────────┘
                     │
                     ▼
     ┌───────────────────────────────────────┐
     │  AsyncMessageBus (Unix domain socket) │
     │  - 4-byte length-prefixed JSON frames │
     │  - broadcast to all connected writers │
     └───────────────────────────────────────┘
```

### Component Reference

| File | Role | Key Classes / Functions |
|---|---|---|
| `ai_hypervisor/mesh_protocol.py` | Wire protocol constants and participant directory | `Participant`, `Registry` (thread-safe, TTL GC) |
| `ai_hypervisor/broker.py` | Routing daemon and tmux bridge | `Broker`, `_deliver()`, `_pane_poller()`, `_gc_loop()` |
| `ai_hypervisor/message_bus.py` | Async Unix-socket bus and client | `AsyncMessageBus`, `BusClient`, `Message` |
| `scripts/mesh_kimi.py` | Kimi participant launcher (pure async) | `ProfiledHypervisor`, `main()`, heartbeat loop |
| `scripts/mesh_claude.py` | Claude participant launcher (threaded bus) | `MeshClaude`, `_run_bus_loop()`, `_handle_msg_send()` |
| `start_mesh.sh` | Orchestrator: broker → kimi → claude | PID files, log dirs, socket lifecycle |
| `stop_mesh.sh` | Shutdown: participants first, broker last | SIGTERM → wait 5s → SIGKILL |

---

## Message Types

Defined in `mesh_protocol.py`:

| Constant | Value | Direction | Purpose |
|---|---|---|---|
| `MSG_REGISTER` | `"register"` | Participant → Broker | Announce presence. Payload: `{name, role, pane?, capabilities}` |
| `MSG_DEREGISTER` | `"deregister"` | Participant → Broker | Clean exit. Payload: `{name}` |
| `MSG_LIST` | `"list_participants"` | Participant → Broker | Query roster. Broker replies with `MSG_PARTICIPANTS` |
| `MSG_PARTICIPANTS` | `"participants"` | Broker → Participant | Roster broadcast. Payload: `{participants: [...]}` |
| `MSG_SEND` | `"send"` | Participant → Bus | Send text to another participant. Payload: `{to, from, content}` |
| `MSG_RECEIVED` | `"received"` | Participant → Bus (or Broker → Bus) | Reply with captured output. Payload: `{from, content}` |
| `MSG_BROKER_READY` | `"broker_ready"` | Broker → Bus | Emitted on startup. Triggers re-registration. |
| `MSG_HEARTBEAT` | `"heartbeat"` | Participant → Broker | Liveness ping. Resets `last_seen` in Registry. |

---

## Message Flow

### Path A: Hypervisor-Native Participant → Hypervisor-Native Participant

Both participants have `pane == ""` in the registry. The broker does not touch tmux.

```
Participant A (mesh_claude)
  │
  │ BusClient.send(MSG_SEND {to: "kimi", content: "hello"})
  │
  ▼
AsyncMessageBus (Unix socket)
  │
  ├──► Broker._on_any() → _on_send()
  │      target.pane == "" → no-op ("bus broadcast")
  │
  ├──► Participant B (mesh_kimi) BusClient._read_loop()
  │      dispatches to MSG_SEND handler
  │
  ▼
Participant B injects "hello\n" into its own PTY,
waits 5.0 s, captures scrollback diff,
then BusClient.send(MSG_RECEIVED {from: "kimi", content: "..."})
  │
  ▼
AsyncMessageBus broadcasts MSG_RECEIVED to all clients
  │
  ├──► Participant A receives it
  │
  └──► Broker sees it, ignores (no handler for received)
```

**Key point:** The broker is a passive registry here. The actual delivery is the bus broadcast itself.

### Path B: Any Participant → Tmux-Backed Participant

The target has a non-empty `pane` (e.g. `"mesh:0.1"`). The broker actively bridges to tmux.

```
Participant A
  │
  │ MSG_SEND {to: "legacy-agent", content: "run tests"}
  ▼
AsyncMessageBus
  │
  ├──► Broker._on_send()
  │      Registry.get("legacy-agent") → pane = "mesh:0.1"
  │      target.pane != "" → create_task(_deliver())
  │
  ▼
Broker._deliver("mesh:0.1", "legacy-agent", "run tests")
  │
  ├──► tmux send-keys -t mesh:0.1 -l "run tests"
  ├──► tmux send-keys -t mesh:0.1 Enter
  ├──► asyncio.sleep(2.5)   <-- SEND_SETTLE_DELAY
  ├──► tmux capture-pane -t mesh:0.1 -p -S -200
  ├──► _diff_tail(prev_capture, new_capture)
  └──► bus.send(MSG_RECEIVED {from: "legacy-agent", content: diff})
```

**Key point:** The broker is an active adapter for tmux-backed participants. It turns bus messages into keystrokes and pane output into bus messages.

---

## Key Design Decisions

### 1. Broadcast Bus with Local Filtering

`AsyncMessageBus.send()` broadcasts every message to **every** connected client. There is no unicast, no private channel, no per-target routing in the socket layer.

**Why:** This is correct for a hivemind. All peers are assumed to be cooperating agents that should see the full traffic pattern. If A sends to B, C may also need to observe that interaction for coordination. Privacy between peers is explicitly out of scope.

**Trade-off:** O(n²) handler noise as the mesh grows. Every client receives every `MSG_SEND` and must filter locally (`if msg.payload.get("to") != my_name: return`).

### 2. No Unicast / No Privacy Layer

There is no encryption, no capability-based filtering, no message hiding. If you connect to the bus socket, you see everything.

**Why:** The MVP scope is local-only, single-machine, single-user. The design doc (`MESH_MVP_BRIEF.md`) explicitly states: "Bus is the only coordination plane. If it's not on the bus, it didn't happen."

### 3. PTY Layer for Screen Reconstruction and Injection

Each participant runs its AI CLI inside a pseudo-terminal managed by `PTYLayer` (from `pty_layer_v2.py`). The PTY layer:

- Reconstructs a 2D screen buffer from ANSI sequences
- Maintains a scrollback commit log
- Supports `write()` for input injection
- Uses s-expression rule files to strip spinners and extract structured data

**Why:** AI CLI tools (Claude Code, Kimi, Aider) are TUI applications. You cannot pipe stdin/stdout and expect them to work. The PTY makes them think they are talking to a real terminal, while the hypervisor can still observe and inject.

### 4. S-Expression DSL for Tool Profiling

`rules/default.sexpr` defines profiles with `(inherit ...)` support. Rules specify:

- `scrollback-ignore` — regex patterns for transient noise (spinners, progress bars)
- `screen-capture` — regex extractions for token counts, cost, prompts
- `defaults` — terminal geometry, etc.

**Why:** New tool support should not require new Python code. A new `.sexpr` file is sufficient for most cases. This aligns with the DESIGN.md principle: "Declarative over imperative."

### 5. Persistent Bidirectional Bus Connections

`BusClient` opens one Unix socket connection at startup and keeps it open for the entire session. It runs a background `_read_loop` coroutine that continuously reads framed messages and dispatches them to handlers.

**Why:** Re-establishing a connection per message adds latency and complexity. Persistent connections let the broker push `broker_ready`, `received`, and `participants` messages to clients in real time without polling.

---

## Concurrency Models

The two participant scripts use **different concurrency architectures**. This is design debt.

### mesh_kimi.py — Pure Asyncio

```
Single asyncio event loop
  ├── main()
  │     ├── BusClient.connect() → _read_loop task
  │     ├── heartbeat_loop task
  │     └── asyncio.to_thread(hv.run_ai_tool())
  └── All handlers run as tasks on the same loop
```

- The hypervisor blocks a thread pool worker, but the bus I/O and handlers stay on the main asyncio loop.
- Shared state (the `AIHypervisor` instance) is accessed from one loop, but the PTY layer has its own internal threads for `os.read()` on the master FD.

### mesh_claude.py — Threaded Bus

```
Main thread (blocking)
  └── hv.run_ai_tool("claude", [])  ← blocks until Claude exits

Background daemon thread
  └── asyncio loop
        ├── BusClient.connect() → _read_loop
        ├── heartbeat_loop
        └── MSG_SEND handlers
```

- The bus client lives in a dedicated thread with its own event loop.
- `MSG_SEND` handlers schedule async tasks onto the background loop, but the actual PTY write happens against an `AIHypervisor` object owned by the main thread.
- There is no explicit synchronization between the background thread's handlers and the main thread's hypervisor state.

### Implications

| Concern | mesh_kimi | mesh_claude |
|---|---|---|
| Thread safety | Simpler (mostly single loop) | Risky (bus thread + main thread share PTY) |
| Shutdown | Async cancellation, clean deregister | Thread join timeout, less graceful |
| Re-registration on broker_ready | Async task on same loop | Async task on background loop |
| Scalability | Standard asyncio | Extra thread overhead per participant |

**Verdict:** The threaded model in `mesh_claude` exists because Claude Code's `run_ai_tool()` is synchronous and blocking. A future cleanup should unify both scripts around the pure-async pattern (or move the blocking call into a thread pool while keeping bus I/O on the main loop).

---

## Known Limitations & Timing

### Hardcoded Delays

| Delay | Location | Value | Risk |
|---|---|---|---|
| `SEND_SETTLE_DELAY` | `broker.py` | 2.5 s | If the tmux pane target is slow to respond, output is truncated. If fast, old output may leak into the diff. |
| Participant wait | `mesh_kimi.py`, `mesh_claude.py` | 5.0 s (configurable via payload `"wait"`) | Same issue: too short = truncated response; too long = unnecessary latency. |

There is no adaptive polling (e.g., "wait until screen stops changing"). The diff is taken after a fixed sleep.

### Scrollback Diff Fragility

`_diff_tail(prev, curr)` in `broker.py` and the scrollback diff in participant scripts both use simple suffix matching:

```python
def _diff_tail(prev, curr):
    if curr.startswith(prev):
        return curr[len(prev):]
    # fallback: find longest common prefix, return remainder
```

**Failure modes:**
- If the 200-line capture buffer (`tmux capture-pane -S -200`) scrolls past the previous capture point, `prev` is no longer a prefix of `curr`. The fallback returns a partial or full dump, causing duplication or garbage.
- If ANSI escape sequences shift between captures, the byte-level diff may include noise.
- If the pane clears the screen (`clear`, `cls`, `\033[2J`), the suffix assumption breaks completely.

### No Automatic Reconnect

If the broker restarts, it creates a new Unix socket file. Existing `BusClient` connections break. The client does **not** have a reconnect loop. It does re-register on `broker_ready`, but only if the old socket is still readable enough to receive the `broker_ready` broadcast — which is unlikely after a broker crash.

**Workaround:** Restart the participant scripts when the broker restarts.

### Fire-and-Forget, No ACK / Retry

All mesh protocol messages (register, deregister, send, heartbeat) are fire-and-forget. The bus layer sends a low-level `_ack` frame, but `BusClient._read_loop` explicitly ignores it:

```python
if msg.msg_type == '_ack':
    continue
```

There is no retry logic. If the broker is busy or a frame is dropped on a full socket buffer, the message is lost silently.

### Unused Scaffolding

`message_bus.py` contains three high-level classes that are **not used** by the broker or participant scripts:

- `AgentChannel` — blocking `queue.Queue` inbox, sync/async send wrappers
- `CooperativeTask` — iteration tracking, max 20 iterations
- `CooperativeAgent` — capability registration, action proposing

These appear to be speculative API surface from an earlier design phase. They are safe to ignore but create confusion about "the right way" to build on the bus.

---

## File Layout Debt

`DESIGN.md` (the target-state spec) envisions this layout:

```
ai_hypervisor/
  ├── layers/
  │     ├── pty.py          (was pty_layer_v2.py)
  │     ├── shell.py
  │     └── egress.py
  ├── bus/
  │     ├── message_bus.py
  │     └── channel.py
  ├── rules/
  │     └── engine/
  │           ├── sexp.py
  │           └── pattern_lang.py
  └── ...
```

**Current reality:** The tree is flat. Files retain v2 suffixes (`pty_layer_v2.py`), the bus code lives in the root `message_bus.py`, and participant scripts sit at `term_capture/scripts/` rather than inside the package. Cleanup is incomplete.

---

## Startup & Shutdown Sequence

### Startup (`start_mesh.sh`)

1. Create per-run log directory (`logs/mesh_YYYYMMDD_HHMMSS/`)
2. Generate unique socket path (`/tmp/mesh_bus.YYYYMMDD_HHMMSS.sock`)
3. **Start broker** (`python -m ai_hypervisor.broker --socket ...`)
4. **Wait** for socket file to appear (up to 6 s, 0.2 s polling)
5. **Start mesh_kimi** (`python scripts/mesh_kimi.py --socket ...`)
6. **Start mesh_claude** (`python scripts/mesh_claude.py --socket ...`)
7. Write PID file, update `/tmp/mesh_pids.latest` symlink

### Normal Operation

- Participants connect and send `register`
- Heartbeats every 30 s keep registry entries fresh
- Broker pane poller runs every 2 s (tmux-backed participants only)
- Broker GC runs every 15 s, dropping participants with `last_seen > 60 s`
- `broker_ready` broadcast on broker startup triggers re-registration

### Shutdown (`stop_mesh.sh`)

1. Read PID file (or resolve `/tmp/mesh_pids.latest` symlink)
2. Kill in **reverse order**: participants first, broker last
3. Per process: SIGTERM → wait up to 5 s → SIGKILL if still alive
4. Remove socket file and PID file
5. Clean up symlink if it points to the removed PID file

---

## Quick Reference: Running the Mesh

```bash
# Start everything
cd code-combo/term_capture
./start_mesh.sh

# Inspect logs
ls logs/mesh_*/
tail -f logs/mesh_*/broker.log

# Stop latest mesh
./stop_mesh.sh

# Stop specific mesh
./stop_mesh.sh logs/mesh_20260427_210000/pids

# Run broker standalone (for debugging)
cd code-combo/term_capture
PYTHONPATH="$(pwd)" python -m ai_hypervisor.broker --socket /tmp/mesh_bus.sock -v
```

---

## Message Examples

### Register

```json
{
  "msg_id": "a1b2c3d4",
  "src": "kimi-12345",
  "dst": "broker",
  "msg_type": "register",
  "payload": {
    "name": "kimi-12345",
    "role": "ai",
    "pane": "",
    "capabilities": ["chat", "code", "files"]
  },
  "timestamp": "2026-04-27T21:00:00"
}
```

### Send

```json
{
  "msg_id": "e5f6g7h8",
  "src": "claude",
  "dst": "broadcast",
  "msg_type": "send",
  "payload": {
    "to": "kimi-12345",
    "from": "claude",
    "content": "Please summarize the files in /tmp/project"
  },
  "timestamp": "2026-04-27T21:00:05"
}
```

### Received

```json
{
  "msg_id": "i9j0k1l2",
  "src": "kimi-12345",
  "dst": "claude",
  "msg_type": "received",
  "payload": {
    "from": "kimi-12345",
    "content": "The project contains 3 Python files...",
    "in_reply_to": "e5f6g7h8"
  },
  "timestamp": "2026-04-27T21:00:12"
}
```

---

THIS DOCUMENT IS CURRENT AS OF 04/27/2026. THIS DOCUMENT MAY BE OUTDATED OR OBSOLETE PAST THAT DATE. IF YOU'RE LOOKING FOR A SOURCE OF TRUTH, READ THE CODE, 'CAUSE THIS AIN'T IT. IF A FILE WITH A FUTURE CTIME/MTIME CONFLICTS WITH THINGS SAID IN THIS FILE, PREFER THE FILE WITH THE NEW TIMESTAMP ON IT. OBVIOUSLY.
