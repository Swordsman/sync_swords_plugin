# HearthPhoenix Architecture

## 1. What Problem Does HearthPhoenix Solve?

HearthPhoenix is a **process-level supervision and hotswap harness** for Python. It answers a specific operational problem:

> You have a long-running Python process that performs business logic. You want to update its source code without downtime, and you want a safety net if the update goes badly. You also want this to work with processes you don't control — external daemons that speak their own protocols.

Traditional approaches — restarting the process manually, writing ad-hoc watchdog scripts, hacking SIGTERM handlers — are fragile, inconsistent, and don't compose. HearthPhoenix provides a reusable, contract-driven framework where:

- An **immortal supervisor** process owns the lifecycle of a **disposable worker** child process.
- Worker updates happen **transactionally**: snapshot the old version, start the new one, health-check it, and only commit if it's healthy. If the health check fails, the supervisor **rolls back** to the last-known-good snapshot automatically.
- **Pluggable transports** decouple the supervisor from how it communicates with the worker — REST, Unix socket, file, pipe, or CLI.
- A **contract/guarantee system** tells you, before you act, how safe each operation is — from "GUARANTEED" (we've verified this works) down to "NOT_SUPPORTED" (don't even try).
- An **interface translation layer** wraps external daemons, exposing them through multiple frontend protocols (HTTP, socket, CLI, pipe) simultaneously while speaking the daemon's single native backend protocol.

---

## 2. Two-Layer Architecture

HearthPhoenix has two distinct but composable layers:

### Layer 1: Supervisor/Worker System

```
┌──────────────────────────────────────────────┐
│                  SUPERVISOR                   │
│  (immortal parent, injection-based)           │
│                                               │
│  Owns:                                        │
│  ├── Transport (pluggable comm channel)       │
│  ├── SnapshotManager (versioned backups)      │
│  ├── WorkerLifecycle (spawn/kill/await)       │
│  ├── CrashLoopDetector (failure counting)     │
│  ├── GuaranteeMatrix (per-op guarantees)      │
│  └── health_check callable                    │
│                    │                          │
│               Transport                       │
│                    │                          │
│  ┌─────────────────▼────────────────────┐     │
│  │              WORKER                   │     │
│  │  (disposable child subprocess)        │     │
│  │  - All business logic                 │     │
│  │  - Optional WorkerApp SDK             │     │
│  │  - Optional WorkerContract            │     │
│  └───────────────────────────────────────┘     │
└──────────────────────────────────────────────┘
```

The supervisor is **injection-based**: you construct it with a Transport, SnapshotManager, WorkerLifecycle, and health_check function. All of these can be swapped at runtime via `reconfigure()` without restarting the supervisor process.

The worker is a **subprocess** — spawned, killed, and replaced. It never outlives a single update cycle. This is the key insight: by making the worker disposable, updates become "kill old, start new" rather than "modify in place."

### Layer 2: Interface Translation / Wrapping

```
┌──────────────────────────────────────────────────────┐
│                   DaemonWrapper                       │
│  (top-level orchestrator for external daemons)        │
│                                                       │
│  Owns:                                                │
│  ├── daemon lifecycle (WorkerLifecycle)               │
│  ├── InterfaceRegistry (adapter directory)            │
│  ├── TranslationEngine (message routing)              │
│  └── FileHealthMonitor (optional, advisory)           │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │           InterfaceRegistry                      │  │
│  │                                                  │  │
│  │  Frontends (expose to callers):                  │  │
│  │  ├── HttpAdapter  :8080/health                   │  │
│  │  ├── SocketAdapter /tmp/hp.sock                  │  │
│  │  ├── CliAdapter                                  │  │
│  │  └── PipeAdapter (stdin/stdout)                  │  │
│  │               │                                  │  │
│  │         TranslationEngine                        │  │
│  │    (routes + translates messages)                │  │
│  │               │                                  │  │
│  │  Backend (connects to daemon):                   │  │
│  │  └── SocketAdapter /tmp/anobios.sock             │  │
│  └─────────────────────────────────────────────────┘  │
│                                                       │
│  ┌──────────────────┐                                 │
│  │ EXTERNAL DAEMON   │   (process we don't control)   │
│  │ (e.g., anobios)   │                                 │
│  └──────────────────┘                                 │
└──────────────────────────────────────────────────────┘
```

This layer exists because the supervisor/worker system assumes both sides agree on a transport at startup. External daemons don't — they have one native protocol, and you can't modify them. The wrapping layer:

1. **Spawns and manages** the external daemon just like a worker.
2. **Exposes multiple frontend interfaces** — HTTP for debugging, CLI for scripting, socket for another supervisor, pipe for programmatic use.
3. **Translates** between each frontend's wire format and the daemon's backend protocol.
4. **Supports passthrough** — when a frontend and backend use the same protocol, messages pass through without structural transformation.

### How the Layers Relate

The two layers are independent but share infrastructure:

- `DaemonWrapper` uses `WorkerLifecycle` (same class the Supervisor uses) to spawn/kill the daemon.
- `DaemonWrapper` is **not** a `Supervisor`. It doesn't do hotswap of the daemon (that's on you). It focuses on multi-interface exposure.
- Both layers use the same health primitives: `HealthResult`, `HealthStatus`, `CrashLoopDetector`.
- A future version could compose them: a `Supervisor` managing a `DaemonWrapper`-based worker that wraps an external daemon.

---

## 3. How the Pieces Compose

### Construction Order

```
Supervisor(
    transport=SomeTransport(...),      # 1. How to talk to the worker
    snapshot_manager=SnapshotManager(...), # 2. Where to store backups
    lifecycle=WorkerLifecycle(...),    # 3. How to spawn/kill workers
    health_check=my_health_fn,         # 4. How to check worker health
    worker_cmd=["python", "worker.py"], # 5. What to run
    worker_path="./worker.py",         # 6. What file to snapshot
    crash_threshold=3,                 # 7. Crash loop sensitivity
    crash_window=30.0,                 # 8. Crash loop time window
    cooldown_seconds=10.0,             # 9. Cooldown between restarts
)
```

Every component is injected. Nothing is hardcoded. This is what makes `reconfigure()` possible — the supervisor is just a shell that orchestrates its injected dependencies.

### Runtime Composition

```
Supervisor.start()
  │
  ├── Transport.on_supervisor_start()     # bind socket / start server
  ├── Transport.configure() → env vars    # worker will read these
  ├── WorkerLifecycle.spawn(cmd, config)  # subprocess.Popen
  ├── WorkerLifecycle.await_healthy(fn)   # poll health via transport
  │     └── health_check() → HealthResult
  ├── Start monitor thread (daemon)       # watches PID + connectivity
  └── Return
```

### The Contract/Guarantee Pipeline

This is a multi-stage pipeline that runs at startup and after hotswap:

```
Stage 1: CapabilityScanner (AST analysis of worker.py)
  Input: worker source code
  Output: set of Capability enums found
  Example: {SIGTERM_HANDLER, HEALTH_CHECK, WORKER_APP}

Stage 2: GuaranteeMatrix (computation from capabilities)
  Input: set of Capability enums
  Output: per-operation guarantee levels
  Example: {start: GUARANTEED, stop: GUARANTEED, health_check: GUARANTEED,
            hotswap: GUARANTEED, rollback: GUARANTEED,
            restart: GUARANTEED, state_transfer: NOT_SUPPORTED}

Stage 3: WorkerContract verification (if worker declares contracts)
  Input: WorkerContract subclass with @contract decorators
  Output: VerificationReport (verified/unverified per operation)
  Note: runs contracts in an isolated subprocess with a 5.0s timeout each

Stage 4: DowngradeEngine (runtime failure handling)
  Input: detected failure (e.g., health check timeout)
  Output: downgraded guarantee for affected operation
  Persists downgrade for the lifetime of this worker
```

---

## 4. The Hotswap Flow (End to End)

`Supervisor.update(source_path)` is the flagship operation. Here is the exact sequence:

```
1. VALIDATE
   - Syntax-check the new source file (import or compile)
   - If the file is invalid, raise immediately — nothing changes

2. SNAPSHOT
   - SnapshotManager.snapshot(current_worker_path)
   - Creates timestamped backup: .hearthphoenix/snapshots/worker-YYYYMMDD-HHMMSS/
   - The current .safe pointer still points to the previous safe version

3. STOP OLD WORKER
   - WorkerLifecycle.kill(old_proc)
   - Send SIGTERM, wait graceful_timeout (default 5.0s)
   - If still alive, send SIGKILL
   - Returns True if graceful, False if force-killed

4. START NEW WORKER
   - Copy/use new source at worker_path
   - WorkerLifecycle.spawn(cmd, config)
   - New subprocess starts with transport env vars

5. HEALTH CHECK
   - WorkerLifecycle.await_healthy(health_check, timeout=10.0, retries=5)
   - Polls health_check() via transport with backoff between retries
   - Each poll: Transport.health_check(timeout) → HealthResult

6. DECISION POINT
   
   IF HEALTHY:
     ├── SnapshotManager.promote(new_snapshot)  # mark as .safe
     ├── Run contract verification on new worker (if WorkerContract)
     ├── Compute new guarantee matrix
     └── Return {"success": True, "action": "commit", "health": HealthResult}
   
   IF UNHEALTHY:
     ├── WorkerLifecycle.kill(new_proc)          # kill the bad worker
     ├── SnapshotManager.restore(worker_path)    # restore .safe to path
     ├── WorkerLifecycle.spawn(cmd, config)      # restart old worker
     ├── WorkerLifecycle.await_healthy(fn)       # verify old worker is OK
     └── Return {"success": False, "action": "rollback", "health": HealthResult}

7. MONITOR
   - The daemon monitor thread continues watching the (new or restored) worker
   - If the worker dies unexpectedly: record crash → check crash loop → maybe escalate
```

Key property: **steps 2-6 happen under a lock** so only one update can be in flight at a time. The monitor thread continues running throughout — it's not paused, but it won't interfere with a deliberate update.

---

## 5. Contract & Guarantee System

### Philosophy

The guarantee system answers: "Can I safely do X?" before you do it. It's opt-in and non-blocking — workers that don't participate still work fine, they just get lower guarantees.

### Per-Operation Guarantee Levels

| Level | Meaning | Example |
|-------|---------|---------|
| `GUARANTEED` | We have verified this works | Worker declares `@contract("stop")`, verifier confirms SIGTERM handler works |
| `BEST_EFFORT` | We think this will work but can't prove it | SIGTERM handler detected via AST but not verified at runtime |
| `NOT_SUPPORTED` | We know this won't work | Worker has no health endpoint |
| `UNKNOWN` | We haven't checked (yet) | Fresh worker, capability scan hasn't run |

### Operations Tracked

| Operation | Requires for GUARANTEED | Always GUARANTEED? |
|-----------|------------------------|---------------------|
| `start` | Nothing | Yes |
| `stop` | SIGTERM_HANDLER (verified) | No |
| `restart` | SIGTERM_HANDLER (verified) | No |
| `health_check` | HEALTH_CHECK endpoint (verified) | No |
| `hotswap` | HEALTH_CHECK | No |
| `rollback` | Nothing (snapshots always work) | Yes |
| `state_transfer` | STATE_SERIALIZATION hooks (verified) | No |

### Declaration: WorkerContract

Workers opt in by subclassing `WorkerContract`:

```python
from hearthphoenix.contracts import WorkerContract, contract, Operation

class MyContract(WorkerContract):
    @contract(Operation.STOP)
    def graceful_shutdown(self, timeout: float = 5.0) -> bool:
        """Handle SIGTERM, return True if clean."""
        ...

    @contract(Operation.HEALTH_CHECK)
    def health(self) -> HealthResult:
        """Return health status."""
        ...

    @contract(Operation.STATE_TRANSFER)
    def serialize(self, path: Path) -> None:
        """Save state to path."""
        ...

    @contract(Operation.STATE_TRANSFER)
    def deserialize(self, path: Path) -> None:
        """Load state from path."""
        ...
```

The `@contract` decorator takes an `Operation` enum value (not a string). It maps the operation to the method that fulfills it.

### Verification: ContractVerifier

At startup and after hotswap, if the worker declares a `WorkerContract`:

1. `ContractVerifier` spawns an **isolated subprocess** running the worker's contract methods.
2. Each declared contract is tested individually with a **5.0 second timeout**.
3. Results are cached to `~/.hearthphoenix/<sha256_of_worker_file>/verified_contracts.json`.
4. Verified contracts → `GUARANTEED` for that operation.
5. Unverified contracts → `BEST_EFFORT`.
6. Undeclared operations → `NOT_SUPPORTED`.

**Cache limitation:** The cache key is the SHA256 of the worker file only. If the worker imports other modules and those change, the cache is not invalidated. This is a known limitation documented in the code.

### Runtime Downgrade: DowngradeEngine

If a previously-verified contract fails at runtime, the `DowngradeEngine` handles it:

| Detected Failure | Downgrade Action |
|------------------|------------------|
| SIGTERM ignored (worker didn't die after SIGTERM) | `stop` → `BEST_EFFORT`, remove from verified cache |
| Health check timeout | `health_check` → `BEST_EFFORT` |
| Health check returns 500/unhealthy | `health_check` → `NOT_SUPPORTED` |
| serialize/deserialize raises | `state_transfer` → `NOT_SUPPORTED` |
| Crash during state transfer | `state_transfer` → `NOT_SUPPORTED` + alert |

Downgrades persist for the lifetime of the current worker process. A hotswap to a new worker triggers fresh verification.

---

## 6. Interface Translation / Wrapping Layer

### Why It Exists

The supervisor/worker system requires both sides to agree on a transport protocol. When wrapping an **external daemon** (a process you don't control), you can't modify the daemon to use HearthPhoenix transports. The wrapping layer solves this by:

1. Treating the daemon as a black box with one native backend interface.
2. Standing up multiple frontend interfaces that external callers can use.
3. Translating messages between frontend wire formats and the backend protocol.

### Composition

```
DaemonWrapper
  ├── daemon_cmd: ["/path/to/daemon", "--flag"]
  ├── backend: InterfaceAdapter (connects TO the daemon)
  │     e.g., SocketAdapter("backend", socket_path="/tmp/daemon.sock", direction="backend")
  ├── frontends: list[InterfaceAdapter] (expose TO callers)
  │     e.g., [HttpAdapter("http", port=8080, direction="frontend"),
  │            SocketAdapter("socket", socket_path="/tmp/hp.sock", direction="frontend")]
  ├── lifecycle: WorkerLifecycle (spawn/kill daemon)
  ├── health_check: optional custom callable (overrides backend health)
  └── file_monitor: FileHealthMonitor (optional, advisory only)
```

### InterfaceRegistry

The registry is the adapter directory. It:

- **Registers** all adapters (backend + frontends) by name.
- **Tracks** enabled/disabled state per adapter.
- **Provides** `list_frontends()` (name → enabled flag) and the `frontends` mapping for the TranslationEngine.
- **Supports** `enable(name)` / `disable(name)` at runtime (via `DaemonWrapper.toggle_frontend`) — frontends can be turned on/off without restarting the daemon.

### TranslationEngine

The engine sits between frontends and the backend:

```
Frontend A ──→ TranslationEngine ──→ Backend ──→ Daemon
Frontend B ──→      │
Frontend C ──→      │
                    ├── Passthrough check: if frontend protocol == backend protocol
                    │   AND both support passthrough, skip structural transformation
                    ├── Message size limit: 1 MB (hard cap)
                    ├── Backend timeout: returns error Message, never raises
                    └── Error propagation: backend errors → frontend with metadata
```

The `route(source, message)` method (takes the source adapter, not a name):
1. Rejects messages larger than `MAX_MESSAGE_SIZE` (1 MB) with an `action="error"` Message.
2. Derives source/backend protocol type from each adapter's class name.
3. Checks passthrough compatibility (same protocol type + `supports_passthrough`).
4. If passthrough: forwards the canonical Message directly to the backend.
5. If not: applies any registered structural transform (identity until one is registered), then forwards.
6. Sends to backend via `backend.send(message, timeout=30.0)`.
7. Returns the response `Message` to the caller.

### InterfaceAdapter (ABC)

All adapters implement this interface:

```python
class InterfaceAdapter:
    name: str                          # unique name in the registry
    direction: InterfaceDirection      # FRONTEND, BACKEND, or BIDIRECTIONAL
    supports_passthrough: bool         # can skip translation when protocols match

    def start(self) -> None: ...       # bind/listen (frontend) or connect (backend)
    def stop(self) -> None: ...        # unbind/disconnect
    def send(self, message: Message, timeout: float = 30.0) -> Message: ...
    def health_check(self, timeout: float) -> HealthResult: ...
```

### Directions

| Direction | Role | Example |
|-----------|------|---------|
| `FRONTEND` | Exposes an interface for external callers | HTTP server on :8080 |
| `BACKEND` | Connects to the daemon's native interface | Unix socket to daemon |
| `BIDIRECTIONAL` | Can serve either role | Generic adapter |

### Adapter Implementations

| Adapter | Mechanism | Passthrough |
|---------|-----------|-------------|
| `HttpAdapter` | HTTP/1.1 REST, JSON body | Yes |
| `SocketAdapter` | JSON lines over Unix socket (TCP fallback) | Yes |
| `CliAdapter` | Subprocess invocation, stdin/stdout JSON | Yes |
| `PipeAdapter` | stdin/stdout JSON lines | Yes |

### Message Type

```python
@dataclass(frozen=True)
class Message:
    action: str          # what operation to perform ("error" signals a failure)
    payload: dict        # operation-specific data
    metadata: dict       # routing info, timestamps, correlation IDs
    version: int = 1     # message schema version
```

There is no `error` field — failures use `action == "error"` with details in `payload`.

### FileHealthMonitor

A non-adapter component that polls a heartbeat file written by the daemon:

- Polls `heartbeat_path` (e.g., `/tmp/daemon.heartbeat`).
- `stale_timeout` (default 30.0s): if the file is older than this, status is `DEGRADED` or `UNHEALTHY`.
- Results appear in `DaemonWrapper.status()["file_monitor"]` but are **advisory only** — they do NOT affect the wrapper state machine.
- Backend health (via the backend adapter's `health_check()`) is canonical.

### Health Aggregation Policy

1. **Backend health is canonical.** It drives the `DaemonWrapper` state machine (`running`, `degraded`, `unrecoverable`).
2. **Frontend health is advisory.** Shown in `status()["frontends"]` but does not affect state.
3. **FileHealthMonitor is advisory.** Shown in `status()["file_monitor"]` but does not affect state.
4. **Custom health callable overrides backend health.** If provided, used for state-machine decisions instead.

### Queue Overflow Policy

Each frontend adapter has a bounded queue (default 100 messages). When full:

1. The oldest message is dropped (FIFO eviction).
2. The new message is enqueued.
3. An error `Message` is returned: `Message(action="error", payload={"reason": "queue_overflow", "dropped": 1})`.

---

## 7. Data Flow

### Supervisor ↔ Worker (via Transport)

```
Supervisor                        Transport                    Worker
    │                                 │                           │
    │── health_check() ───────────────▶│── HTTP GET /health ──────▶│
    │                                 │◀── {"status": "ok"} ─────│
    │◀─────── HealthResult ──────────│                           │
    │                                 │                           │
    │ (update)                        │                           │
    │── kill old worker               │                           │
    │── spawn new worker ────────────▶│── env vars ──────────────▶│
    │── health_check() ───────────────▶│── health poll ───────────▶│
    │◀─────── HealthResult ──────────│◀─────────────────────────│
```

The transport carries **only what the supervisor needs to monitor the worker**: health checks. All supervisor state (PID, crash count, guarantee levels, snapshot paths) stays in the supervisor process. The transport is not a general-purpose RPC channel — it's a control plane, not a data plane.

### Wrapper Layer Message Flow

```
External Caller          Frontend Adapter       TranslationEngine      Backend Adapter     Daemon
     │                        │                       │                     │                │
     │── HTTP POST /action ──▶│                       │                     │                │
     │                        │── Message ───────────▶│                     │                │
     │                        │                       │── (translate?)      │                │
     │                        │                       │── Message ─────────▶│── socket ─────▶│
     │                        │                       │                     │◀── response ──│
     │                        │                       │◀── Message ────────│                │
     │                        │◀── Message ──────────│                     │                │
     │◀── HTTP 200 + JSON ───│                       │                     │                │
```

With passthrough (same protocol on both sides), the TranslationEngine step is skipped — messages flow directly.

---

## 8. Threading Model

### Supervisor

- **Main thread:** Runs the supervisor control loop, handles `start()`, `stop()`, `update()` calls.
- **Monitor thread (daemon):** Watches the worker's PID and transport connectivity. If the worker dies unexpectedly, records the crash via `CrashLoopDetector` and decides whether to restart or escalate to unrecoverable.
- **Update lock:** Only one `update()` can run at a time. The lock prevents concurrent hotswaps but does not block `status()` or the monitor thread.

### DaemonWrapper / Adapters

- **Each frontend adapter** that listens for connections (HttpAdapter, SocketAdapter) runs its accept loop in a **daemon thread**.
- **TranslationEngine** is called from adapter threads. `route()` is synchronous — the adapter handler forwards to the backend and returns the response on the same thread. It does **not** pull from a per-frontend queue (the `BoundedQueue` exists but is not wired into this synchronous path).
- **Backend adapter** maintains a persistent connection to the daemon. Send/receive is synchronous per call.

### CrashLoopDetector

- Uses a **sliding time window** with timestamps (no background thread). `record_crash()` prunes old entries on each call.
- Thread-safe for concurrent crash recording from the monitor thread and status queries from the main thread.
- `max_restarts` and `restart_window_seconds` provide a secondary "give up" threshold.

---

## 9. Sequences

### Startup Sequence

```
Supervisor.start()
  1. Transport.on_supervisor_start()
     - RestTransport: starts HTTP server thread
     - SocketTransport: binds Unix socket, starts accept thread
     - FileTransport: initializes heartbeat file path
     - PipeTransport: no-op (pipes are per-subprocess)
     - CliTransport: no-op

  2. config = Transport.configure()
     - Returns env vars for the worker subprocess
     - e.g., {"HEARTH_PHOENIX_TRANSPORT": "rest", "HEARTH_PHOENIX_REST_PORT": "9876"}

  3. proc = WorkerLifecycle.spawn(worker_cmd, config)
     - Merges config into subprocess environment
     - Returns subprocess.Popen

  4. result = WorkerLifecycle.await_healthy(health_check, timeout=10.0, retries=5)
     - Calls health_check() which calls Transport.health_check(timeout)
     - Retries with backoff on failure
     - Raises/returns UNHEALTHY if all retries exhausted

  5. If HEALTHY:
     - Start monitor thread (daemon) watching worker PID
     - Run capability scan on worker source
     - Run contract verification if WorkerContract detected
     - Compute guarantee matrix
     - Supervisor state → "running"

  6. If UNHEALTHY:
     - WorkerLifecycle.kill(proc)
     - Supervisor state → "degraded" or "unrecoverable" (based on crash count)
```

### Shutdown Sequence

```
Supervisor.stop()
  1. Set supervisor state → "stopping"
  2. Signal monitor thread to stop
  3. WorkerLifecycle.kill(worker_proc, graceful_timeout=5.0)
     - SIGTERM → wait → SIGKILL if needed
  4. Transport.shutdown(graceful=True)
     - RestTransport: stop HTTP server
     - SocketTransport: close socket, stop accept thread
     - Others: cleanup
  5. Transport.on_supervisor_stop()
  6. Supervisor state → "stopped"
```

### Rollback Sequence (after failed update)

```
Update failed health check:
  1. WorkerLifecycle.kill(new_proc)
  2. SnapshotManager.restore(worker_path)
     - Copies .safe snapshot back to worker_path
  3. WorkerLifecycle.spawn(worker_cmd, config)  # restart old version
  4. WorkerLifecycle.await_healthy(health_check)
  5. If old worker is healthy:
     - Monitor thread resumes watching
     - State → "running" (rolled back)
  6. If old worker is ALSO unhealthy:
     - State → "unrecoverable"
     - Both versions are bad — manual intervention needed
```

### Crash Loop Sequence

```
Worker dies unexpectedly:
  1. Monitor thread detects PID exit
  2. CrashLoopDetector.record_crash()
     - If crash_count > crash_threshold within crash_window:
       → Crash loop detected
       → State → "unrecoverable"
       → Supervisor stops attempting restarts
  3. If not in crash loop:
     - CrashLoopDetector.record_restart()
     - If restart_count > max_restarts within restart_window:
       → CrashLoopDetector.give_up() → True
       → State → "unrecoverable"
     - Otherwise:
       → Restore .safe and restart worker
       → State → "degraded"
```

---

## 10. Key Design Decisions

### 1. Runtime-Only Contract Enforcement (Opt-In)

**Decision:** Contracts are enforced at runtime only, and they are voluntary. Workers that don't declare contracts still work — they just get `NOT_SUPPORTED` or `BEST_EFFORT` instead of `GUARANTEED`.

**Rationale:** HearthPhoenix meets you where you are. No mypy protocol enforcement, no forced compliance. The absence of a declaration is information, not a failure. This is consistent with the downgrade logic: you can start without contracts and add them incrementally.

### 2. Injection-Based Supervisor

**Decision:** Every dependency is injected via the constructor. `reconfigure()` allows swapping them at runtime.

**Rationale:** The supervisor is a shell. Making it injection-based means you can swap transports, health checks, and lifecycle managers without restarting the supervisor process. This is the same pattern that would enable a grandparent meta-supervisor in the future.

### 3. Worker as Disposable Subprocess

**Decision:** The worker is always a subprocess, never a thread or in-process module.

**Rationale:** Subprocesses provide true isolation. A crashing worker cannot corrupt the supervisor. Updates are "kill old, start new" — clean, simple, and safe. The cost is IPC overhead, but for the control-plane traffic HearthPhoenix handles, this is negligible.

### 4. Grandparent Hotswap — Deferred

**Decision:** A meta-supervisor that hotswaps the supervisor itself is a natural extension (the injection-based architecture supports it), but it's deferred.

**Rationale:** The pattern repeats cleanly one level up. Worth building eventually, but out of scope for current phases.

### 5. Unix-First, Windows Later

**Decision:** Core primitives (Unix domain sockets, SIGTERM, inotify) are Unix-native. Python's cross-platform nature means a port is possible later, but it's not a requirement.

**Rationale:** The target audience runs Linux or WSL. No Windows compatibility shims in the current implementation. SocketTransport has a TCP fallback that would work on Windows if needed.

### 6. Cache Key Is Worker File Hash Only

**Decision:** `VerifiedContractCache` uses SHA256 of the worker file as the cache key.

**Known limitation:** If the worker imports other modules and those change, the cache is not invalidated. This is documented in the code. A future improvement could track the full dependency tree.

### 7. Backend Health Is Canonical (Wrapper Layer)

**Decision:** In the DaemonWrapper, backend adapter health drives the state machine. Frontend health and FileHealthMonitor are advisory.

**Rationale:** The backend is the actual connection to the daemon. If the backend is healthy, the daemon is reachable. Frontend failures could be configuration issues on the caller side. The file monitor is a secondary signal — useful for dashboards but not for automated decisions.

---

## 11. Environment Variables

### Global (read by supervisor and worker)

| Variable | Values | Default | Effect |
|----------|--------|---------|--------|
| `HEARTH_PHOENIX_CONTRACTS` | `1` or `0` | `1` | Enable/disable runtime contract checking |
| `HEARTH_PHOENIX_LOG_FORMAT` | `text` or `json` | `text` | Log output format |
| `HEARTH_PHOENIX_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` | Logging verbosity |

### Transport-Specific (injected into worker by Transport.configure())

| Variable | Set By | Purpose |
|----------|--------|---------|
| `HEARTH_PHOENIX_TRANSPORT` | All transports | Identifies transport type to worker (e.g., `"rest"`) |
| `HEARTH_PHOENIX_REST_PORT` | RestTransport | Port for HTTP health endpoint |
| `HEARTH_PHOENIX_SOCKET_PATH` | SocketTransport | Path to Unix domain socket |
| `HEARTH_PHOENIX_FILE_PATH` | FileTransport | Path to shared heartbeat file |
| `HEARTH_PHOENIX_CLI_CMD` | CliTransport | Health check command to execute |

---

## 12. File Layout (Reference)

```
hearthphoenix/
├── hearthphoenix/           # Main package
│   ├── __init__.py          # Public API exports
│   ├── supervisor.py        # Supervisor orchestrator
│   ├── lifecycle.py         # WorkerLifecycle (spawn/kill/await/rollback)
│   ├── snapshot.py          # SnapshotManager
│   ├── health.py            # HealthResult, CrashLoopDetector
│   ├── contracts.py         # Contract, WorkerContract, @contract, verifier, cache
│   ├── guarantees.py        # GuaranteeMatrix, DowngradeEngine
│   ├── capabilities.py      # CapabilityScanner, AST detection
│   ├── logging_config.py    # configure_logging, auto_configure
│   ├── transports/          # Transport ABC + implementations
│   │   ├── base.py          # Transport ABC
│   │   ├── rest.py, socket.py, file.py, pipe.py, cli.py
│   ├── worker/              # Worker SDK
│   │   ├── app.py           # WorkerApp
│   │   └── signals.py       # install_graceful_shutdown
│   └── wrappers/            # Interface translation layer
│       ├── daemon_wrapper.py
│       ├── translation_engine.py
│       ├── interface_registry.py
│       ├── health_monitor.py
│       ├── protocol.py      # Message, InterfaceDirection
│       ├── queue.py         # Bounded queue
│       └── adapters/
│           ├── base.py      # InterfaceAdapter ABC
│           ├── http_adapter.py, socket_adapter.py, cli_adapter.py, pipe_adapter.py
├── tests/                   # Full test suite
├── design/                  # Design documents
├── examples/                # Example workers
├── NOTES/                   # Development notes and decisions
└── pyproject.toml
```
