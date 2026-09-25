# HearthPhoenix API Reference

## Overview

HearthPhoenix provides two major subsystems:

1. **Supervisor/Worker System** — manage a Python worker subprocess with transactional hotswap and snapshot-based rollback.
2. **Interface Translation Layer** — wrap external daemons, exposing them through multiple frontend interfaces simultaneously.

This document covers every public class, function, and enum. Classes are organized by subsystem.

---

## Supervisor/Worker System

### `Supervisor`

The top-level orchestrator. Owns a transport, snapshot manager, worker lifecycle, and health check function. Provides the control API: `start()`, `stop()`, `update()`, `status()`, `reconfigure()`.

**When to use it:** Any time you need a managed, hotswappable worker process. This is the main entry point for the supervisor/worker system.

#### Constructor

```python
Supervisor(
    transport: Transport,
    snapshot_manager: SnapshotManager,
    lifecycle: WorkerLifecycle,
    health_check: Callable[[], HealthResult] | None = None,
    *,
    worker_cmd: list[str] | None = None,
    worker_path: str | Path | None = None,
    crash_threshold: int = 3,
    crash_window: float = 30.0,
    cooldown_seconds: float = 10.0,
)
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `transport` | Yes | How the supervisor communicates with the worker. Any `Transport` implementation. |
| `snapshot_manager` | Yes | Where versioned backups are stored. |
| `lifecycle` | Yes | How workers are spawned and killed. |
| `health_check` | No | Custom health check function. If `None`, the supervisor uses `transport.health_check()` directly. |
| `worker_cmd` | No | Command list to spawn the worker (e.g., `["python", "worker.py"]`). Required for `start()`. |
| `worker_path` | No | Path to the worker source file. Required for `update()`. |
| `crash_threshold` | No | Number of crashes within `crash_window` to trigger crash-loop detection. Default 3. |
| `crash_window` | No | Time window (seconds) for crash-loop detection. Default 30.0. |
| `cooldown_seconds` | No | Minimum time between automatic restarts. Default 10.0. |

**Gotcha:** `worker_path` must point to the actual Python file being executed, not a wrapper. The supervisor snapshots this file during `update()` and restores it on rollback.

#### Classmethods

**`Supervisor.wrap_worker(script_path, **kwargs) -> tuple[Supervisor, CapabilityReport]`**

Auto-configures a Supervisor by scanning the worker script for capabilities. Detects what transports the worker supports and wires up sensible defaults.

```python
supervisor, report = Supervisor.wrap_worker("./worker.py")
print(report.guarantee_level)   # e.g., "HEALTH_VERIFIED"
print(report.detected)          # set of Capability enums found
supervisor.start()
```

- Returns a `(supervisor, CapabilityReport)` tuple.
- The supervisor is pre-configured with a default transport.
- `**kwargs` are passed through to the `Supervisor` constructor.
- If the worker script imports from `hearthphoenix.transports`, that transport is selected.
- If the worker subclasses `WorkerApp`, additional capabilities are detected.

**`Supervisor.wrap_daemon(daemon_cmd, backend=..., frontends=[...], **kwargs) -> tuple[DaemonWrapper, CapabilityReport]`**

Auto-configures a `DaemonWrapper` for wrapping an external daemon. This is the quick-start for the interface translation layer.

```python
from hearthphoenix.wrappers.adapters import SocketAdapter, HttpAdapter

wrapper, report = Supervisor.wrap_daemon(
    ["./anobios"],
    backend=SocketAdapter("backend", socket_path="/tmp/anobios.sock", direction="backend"),
    frontends=[
        HttpAdapter("http", port=8080, direction="frontend"),
        SocketAdapter("socket", socket_path="/tmp/hp.sock", direction="frontend"),
    ],
)
wrapper.start()
```

- `daemon_cmd` is the command list to spawn the daemon.
- `backend` is an `InterfaceAdapter` with `direction="backend"` that connects TO the daemon.
- `frontends` is a list of `InterfaceAdapter` with `direction="frontend"` that expose interfaces TO callers.
- Returns `(DaemonWrapper, CapabilityReport)`.

#### Methods

**`start() -> None`**

Starts the supervisor and the initial worker.

1. Calls `transport.on_supervisor_start()`.
2. Calls `transport.configure()` to get environment variables for the worker.
3. Spawns the worker via `lifecycle.spawn(worker_cmd, config)`.
4. Polls health via `lifecycle.await_healthy(health_check)`.
5. If healthy: starts the monitor thread, runs capability scan, computes guarantee matrix. State → `"running"`.
6. If unhealthy: kills the worker. State → `"degraded"` or `"unrecoverable"`.

**Gotcha:** Must set `worker_cmd` in the constructor or via `reconfigure()` before calling `start()`. Raises `RuntimeError` if `worker_cmd` is `None`.

**`stop() -> None`**

Stops the supervisor and worker gracefully.

1. Signals the monitor thread to stop.
2. Calls `lifecycle.kill(worker_proc)` — SIGTERM then SIGKILL if needed.
3. Calls `transport.shutdown(graceful=True)`.
4. Calls `transport.on_supervisor_stop()`.
5. State → `"stopped"`.

**`update(source_path: str | Path) -> dict`**

Transactional hotswap. Replaces the running worker with a new version from `source_path`.

Returns a dict with keys:
- `"success"`: `bool` — `True` if commit, `False` if rollback.
- `"action"`: `str` — `"commit"` or `"rollback"`.
- `"health"`: `HealthResult` — the health check result from the new (or restored) worker.

Sequence:
1. Validate new source file (syntax check).
2. Snapshot current worker via `snapshot_manager.snapshot(worker_path)`.
3. Stop old worker via `lifecycle.kill()`.
4. Copy new source to `worker_path`.
5. Spawn new worker via `lifecycle.spawn()`.
6. Health-check via `lifecycle.await_healthy()`.
7. If healthy: `snapshot_manager.promote(snapshot)`. Run contract verification. Return `{"success": True, "action": "commit", ...}`.
8. If unhealthy: kill new worker. `snapshot_manager.restore(worker_path)`. Restart old worker. Return `{"success": False, "action": "rollback", ...}`.

**Gotcha:** Only one `update()` can run at a time. Concurrent calls will raise or block (implementation-dependent). The monitor thread continues running during updates.

**Gotcha:** If rollback itself fails (the old worker is also unhealthy), the supervisor enters `"unrecoverable"` state. Manual intervention is required.

**`status() -> dict`**

Returns a comprehensive status dict:

```python
{
    "started": bool,                # supervisor started?
    "worker_pid": int | None,       # current worker PID
    "state": str,                   # "stopped" | "running" | "degraded" | "unrecoverable"
    "transport_connected": bool,    # transport health
    "crash_count": int,             # crashes in current window
    "snapshots": int,               # number of stored snapshots
    "guarantee_level": str,         # highest GuaranteeLevel name
    "detected_capabilities": list[str],
    "missing_capabilities": list[str],
    "hotswap_risk": str,            # consolidated risk warning
    "per_operation_guarantees": dict[str, str],  # e.g., {"stop": "GUARANTEED", ...}
}
```

**`reconfigure(transport=None, snapshot_manager=None, lifecycle=None, health_check=None) -> None`**

Swaps injected dependencies at runtime. The supervisor process does not restart.

- All parameters are optional — only specified dependencies are replaced.
- You can change the transport without killing the worker (the new transport will be used for future health checks).
- Useful for hot-swapping the health check function or replacing a failed transport.

**Gotcha:** Does not restart the current worker. If you change the transport, the worker's existing transport binding is unaffected — only new health checks use the new transport.

#### State Machine

The supervisor has four states:

| State | Meaning | Transitions |
|-------|---------|-------------|
| `"stopped"` | Initial state, or after `stop()` | → `"running"` via `start()` |
| `"running"` | Worker is healthy, monitor thread active | → `"degraded"` on worker crash → `"stopped"` via `stop()` → `"unrecoverable"` on crash loop |
| `"degraded"` | Worker crashed but was restarted from `.safe` | → `"running"` if new worker healthy → `"unrecoverable"` if crash loop detected |
| `"unrecoverable"` | Crash loop or rollback failure — manual intervention needed | No automatic recovery |

---

### `WorkerLifecycle`

Manages the lifecycle of a worker subprocess: spawn, kill (graceful → forceful), await health, and rollback on failure.

**When to use it:** Passed to `Supervisor` constructor. Can also be used standalone if you need direct process control without the full supervisor.

#### Constructor

```python
WorkerLifecycle(log_mode: str = "devnull")
```

| Parameter | Values | Description |
|-----------|--------|-------------|
| `log_mode` | `"devnull"` (default), `"inherit"`, `"file"` | Controls where worker stdout/stderr go. |

- `"devnull"`: Worker output is discarded (default, cleanest).
- `"inherit"`: Worker output goes to the supervisor's stdout/stderr (useful for debugging).
- `"file"`: Worker output is written to a log file.

#### Methods

**`spawn(cmd: list[str], config: dict[str, str]) -> subprocess.Popen`**

Spawns a worker subprocess.

- `cmd`: Command list, e.g., `["python", "worker.py"]`.
- `config`: Dictionary of environment variables to merge into the subprocess environment (from `Transport.configure()`).
- Returns the `subprocess.Popen` object.
- The worker subprocess inherits a modified environment with transport configuration.

**`kill(proc: subprocess.Popen, graceful_timeout: float = 5.0) -> bool`**

Kills a worker subprocess. Graceful first, forceful if needed.

- Sends `SIGTERM` and waits up to `graceful_timeout` seconds.
- If the process is still alive, sends `SIGKILL`.
- Returns `True` if the process exited gracefully (SIGTERM worked).
- Returns `False` if SIGKILL was required.
- If `proc` is already dead, returns `True`.

**Gotcha:** On Windows, `SIGTERM` is not available. The implementation uses `SIGTERM` on Unix and falls back to `terminate()` on Windows. Windows behavior is untested per the design decision of Unix-first.

**`await_healthy(health_check_fn: Callable[[], HealthResult], timeout: float = 10.0, retries: int = 5) -> HealthResult`**

Polls a health check function until the worker is healthy or exhausted.

- `health_check_fn`: A zero-argument callable that returns `HealthResult`.
- `timeout`: Total time to wait across all retries.
- `retries`: Maximum number of attempts.
- Returns the last `HealthResult` (could be `UNHEALTHY` if all retries exhausted).
- Uses backoff between retries.
- Does not raise on failure — check `result.status`.

**Gotcha:** The health check function is typically `lambda: transport.health_check(timeout)` or a custom function. Make sure the transport is started before calling this.

**`rollback_and_restart(safe_path: Path, target_path: Path, cmd: list[str], config: dict[str, str]) -> subprocess.Popen`**

Restores the safe snapshot and spawns a new worker from it.

- Copies `safe_path` to `target_path`.
- Spawns a new worker process using `cmd` and `config`.
- Returns the new `subprocess.Popen`.
- Used internally by `Supervisor.update()` during rollback.

---

### `SnapshotManager`

Immutable versioned backups with a `.safe` pointer to the last-known-good version.

**When to use it:** Passed to `Supervisor` constructor. Can also be used standalone for file versioning.

#### Constructor

```python
SnapshotManager(snapshot_dir: str | Path, max_snapshots: int = 10)
```

| Parameter | Description |
|-----------|-------------|
| `snapshot_dir` | Directory where snapshots are stored. Created if it doesn't exist. |
| `max_snapshots` | Maximum number of snapshots to keep (prune keeps this many + `.safe`). Default 10. |

Snapshot directory structure:
```
.hearthphoenix/
├── snapshots/
│   ├── snapshot-20250101-120000/
│   ├── snapshot-20250101-130000/
│   └── ...
└── safe -> snapshots/snapshot-20250101-120000/
```

#### Methods

**`snapshot(source_path: str | Path, label: str | None = None) -> Snapshot`**

Creates a timestamped backup of `source_path`.

- Copies the file or directory at `source_path` to `snapshot_dir/snapshot-YYYYMMDD-HHMMSS/`.
- `label`: Optional human-readable label stored with the snapshot.
- Returns a `Snapshot` object with `path`, `timestamp`, `label` attributes.
- If `source_path` doesn't exist, raises `FileNotFoundError`.

**`promote(snapshot: Snapshot) -> None`**

Promotes a snapshot to the `.safe` slot.

- Updates the `.safe` symlink (or pointer file on systems without symlinks) to point to `snapshot.path`.
- The `.safe` snapshot is never pruned — it's always preserved.
- Raises `ValueError` if the snapshot doesn't exist in the snapshot directory.

**`restore(target_path: str | Path) -> Path`**

Restores the `.safe` snapshot to `target_path`.

- Copies the contents of `.safe` to `target_path`, overwriting if it exists.
- Returns the resolved `Path` to the restored file.
- Raises `RuntimeError` if no `.safe` snapshot exists.

**`prune(keep: int = 5) -> None`**

Removes old snapshots, keeping the most recent `keep` snapshots (plus the `.safe` snapshot, always preserved).

**`get_safe_path() -> Path | None`**

Returns the path to the current safe snapshot, or `None` if no `.safe` exists yet.

**`list_snapshots() -> list[Snapshot]`**

Returns a list of `Snapshot` objects, newest first. The `.safe` snapshot is included in this list.

#### `Snapshot` (dataclass)

```python
Snapshot:
    path: Path         # Path to the snapshot directory
    timestamp: float   # Creation time (time.time())
    label: str | None  # Optional human label
```

---

### `Transport` (ABC)

Abstract base class for pluggable parent↔child communication channels.

**When to implement:** When you need a new way for the supervisor to communicate with the worker. The five built-in implementations cover most use cases.

#### Abstract Methods

**`configure() -> dict[str, str]`**

Returns environment variables the worker subprocess needs to connect back to this transport.

Example for `RestTransport`: `{"HEARTH_PHOENIX_TRANSPORT": "rest", "HEARTH_PHOENIX_REST_PORT": "9876"}`.

These are merged into the worker's subprocess environment by `WorkerLifecycle.spawn()`.

**`health_check(timeout: float) -> HealthResult`**

Checks the worker's health through this transport. Returns a `HealthResult`.

**`is_connected() -> bool`**

Returns `True` if the transport believes it is connected to a live worker.

#### Optional Hooks

**`on_supervisor_start() -> None`**

Called by `Supervisor.start()` before the worker is spawned. Use to bind sockets, start server threads, etc.

**`on_supervisor_stop() -> None`**

Called by `Supervisor.stop()` after the worker is killed. Use for cleanup.

**`shutdown(graceful: bool = True) -> None`**

Called by `Supervisor.stop()`. Use to close connections, stop accept threads, etc. If `graceful=False`, the transport should shut down immediately.

---

### Transport Implementations

#### `RestTransport`

HTTP-based transport. The supervisor starts an HTTP server; the worker responds to health check endpoints.

```python
RestTransport(port: int = 9876)
```

- **Mechanism:** HTTP localhost. The supervisor makes `GET /health` requests.
- **Use case:** Easy debugging (you can `curl` the health endpoint), language-agnostic (any process that speaks HTTP can be supervised).
- **Env vars sent to worker:** `HEARTH_PHOENIX_TRANSPORT=rest`, `HEARTH_PHOENIX_REST_PORT=<port>`.
- **Gotcha:** The port must be available. If port is in use, `on_supervisor_start()` will raise.

#### `SocketTransport`

Unix domain socket transport (TCP fallback on Windows).

```python
SocketTransport(socket_path: str | None = None, port: int | None = None)
```

- **Mechanism:** Unix domain socket (Linux/macOS) or TCP socket (Windows fallback). JSON lines protocol.
- **Use case:** Fast local-only communication. No HTTP overhead. No port conflicts.
- **Env vars sent to worker:** `HEARTH_PHOENIX_TRANSPORT=socket`, `HEARTH_PHOENIX_SOCKET_PATH=<path>` (or `HEARTH_PHOENIX_SOCKET_PORT=<port>` on Windows).
- **Gotcha:** On Unix, the socket file must be on a filesystem that supports Unix domain sockets (not NFS). If `socket_path` is `None`, a temp path is generated.

#### `FileTransport`

Shared file heartbeat. The supervisor polls a JSON heartbeat file written by the worker.

```python
FileTransport(heartbeat_path: str | None = None)
```

- **Mechanism:** The worker writes a heartbeat JSON file; the supervisor reads it.
- **Use case:** No ports, simple polling. Works in container environments where sockets/ports are restricted.
- **Env vars sent to worker:** `HEARTH_PHOENIX_TRANSPORT=file`, `HEARTH_PHOENIX_FILE_PATH=<path>`.
- **Gotcha:** Polling-based, so health detection has inherent latency. The supervisor reads the file on each `health_check()` call. If the worker crashes between writes, the supervisor sees a stale heartbeat until the next poll.
- **Gotcha:** If `heartbeat_path` is `None`, a temp path is generated. Clean up temp files on shutdown.

#### `PipeTransport`

stdin/stdout JSON lines transport. The worker reads commands from stdin and writes responses to stdout.

```python
PipeTransport()
```

- **Mechanism:** The supervisor writes JSON lines to the worker's stdin and reads responses from stdout.
- **Use case:** No filesystem, no ports. Direct parent↔child pipe. Fast and simple.
- **Env vars sent to worker:** `HEARTH_PHOENIX_TRANSPORT=pipe`.
- **Gotcha:** Since the transport uses the subprocess pipes, the worker must NOT write arbitrary data to stdout — only JSON lines formatted for the transport. Use stderr for logging.
- **Gotcha:** The supervisor and worker must agree on the JSON line protocol. The `WorkerApp` SDK handles this automatically.

#### `CliTransport`

Command invocation transport. The supervisor runs a health check command and inspects the exit code.

```python
CliTransport(health_cmd: list[str] | None = None)
```

- **Mechanism:** The supervisor runs `health_cmd` as a subprocess. Exit code 0 means healthy; non-zero means unhealthy.
- **Use case:** One-shot or polling workers that don't maintain persistent connections. Language-agnostic.
- **Env vars sent to worker:** `HEARTH_PHOENIX_TRANSPORT=cli`, `HEARTH_PHOENIX_CLI_CMD=<cmd>`.
- **Gotcha:** Each health check spawns a new subprocess, so it's slow for frequent polling. Best for workers where health is expensive or performed infrequently.
- **Gotcha:** If `health_cmd` is `None`, a default is used. The default behavior depends on the implementation.

---

### `HealthResult` and `HealthStatus`

#### `HealthStatus` (enum)

```python
class HealthStatus(enum.Enum):
    HEALTHY = "healthy"        # Worker is operating normally
    DEGRADED = "degraded"      # Worker is alive but impaired
    UNHEALTHY = "unhealthy"    # Worker is not reachable or failing
```

#### `HealthResult`

```python
HealthResult:
    status: HealthStatus       # HEALTHY, DEGRADED, or UNHEALTHY
    details: dict              # Arbitrary extra information from the check
    latency: float             # How long the check took (seconds)
```

Created by transport health checks and custom health functions. The supervisor uses `status` to make state-machine decisions. `details` is advisory — it appears in `status()` output but does not affect behavior. `latency` is for monitoring and debugging.

---

### `CrashLoopDetector`

Sliding-window crash counter that detects crash loops and escalates to unrecoverable.

**When to use it:** Used internally by `Supervisor`. Can be used standalone for any crash-detection scenario.

#### Constructor

```python
CrashLoopDetector(
    threshold: int = 3,
    window_seconds: float = 30.0,
    max_restarts: int = 10,
    restart_window_seconds: float = 300.0,
)
```

| Parameter | Description |
|-----------|-------------|
| `threshold` | Number of crashes within `window_seconds` to trigger crash-loop detection. |
| `window_seconds` | Sliding window for crash-loop detection. |
| `max_restarts` | Maximum restarts within `restart_window_seconds` before giving up. |
| `restart_window_seconds` | Sliding window for the "give up" threshold. |

Two-stage escalation:
1. **Crash loop:** `crash_count > threshold` within `window_seconds` → crash loop detected.
2. **Give up:** `restart_count > max_restarts` within `restart_window_seconds` → give up entirely.

#### Methods

**`record_crash() -> bool`**

Records a crash. Returns `True` if a crash loop is detected (crash count exceeded threshold within the window).

**`record_restart() -> None`**

Records a restart attempt. Used by the supervisor after each automatic restart.

**`give_up() -> bool`**

Returns `True` when `max_restarts` has been exceeded within `restart_window_seconds`. After this, the supervisor enters `"unrecoverable"` state and stops trying.

**`reset() -> None`**

Clears all recorded crashes and restarts. Called when a worker is successfully hotswapped.

#### Properties

- `crash_count: int` — Current number of crashes inside the window.
- `restart_count: int` — Current number of restarts inside the restart window.

---

### `Contract`, `WorkerContract`, and Decorators

The contract system lets workers declare which operations they support, and the supervisor verifies those declarations at runtime.

#### `Contract` (base class)

Base class for all HearthPhoenix contracts. Provides `@precondition`, `@postcondition`, and `@invariant` decorators for design-by-contract validation.

```python
from hearthphoenix.contracts import Contract, precondition, postcondition, invariant

class MyComponent(Contract):
    @precondition("x must be positive")
    def validate_x(self):
        assert self.x > 0

    @postcondition("result must not be None")
    def validate_result(self, result):
        assert result is not None
```

- Pre/post/invariant violations raise `ContractViolationError` at runtime (fail-fast).
- Contract enforcement can be disabled globally with `HEARTH_PHOENIX_CONTRACTS=0`.

#### `WorkerContract`

Subclass of `Contract` for workers that want to declare which operations they support with guaranteed verification.

```python
from hearthphoenix.contracts import WorkerContract, contract, Operation

class MyWorkerContract(WorkerContract):
    @contract(Operation.STOP)
    def graceful_shutdown(self, timeout: float = 5.0) -> bool:
        """Handle SIGTERM and return True if cleanly shut down."""
        ...

    @contract(Operation.HEALTH_CHECK)
    def health(self) -> HealthResult:
        """Return current health status."""
        ...

    @contract(Operation.STATE_TRANSFER)
    def serialize(self, path: Path) -> None:
        """Save worker state to path."""
        ...

    @contract(Operation.STATE_TRANSFER)
    def deserialize(self, path: Path) -> None:
        """Restore worker state from path."""
        ...
```

- The `@contract` decorator takes an `Operation` enum value — **not** a string.
- Multiple methods can be decorated with the same operation (e.g., `serialize` and `deserialize` both map to `Operation.STATE_TRANSFER`).
- Declared contracts are verified in an isolated subprocess with a 5.0-second timeout per contract.
- Unverified contracts → `BEST_EFFORT` instead of `GUARANTEED`.

#### `Operation` (enum)

```python
class Operation(enum.Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    HEALTH_CHECK = "health_check"
    HOTSWAP = "hotswap"
    ROLLBACK = "rollback"
    STATE_TRANSFER = "state_transfer"
```

#### Decorators

**`@contract(op: Operation)`**

Marks a method as fulfilling a worker contract. Used with `WorkerContract` subclasses.

**`@precondition(description: str)`**

Marks a method as a precondition validator. The method should raise `AssertionError` or return `False` if the precondition is violated.

**`@postcondition(description: str)`**

Marks a method as a postcondition validator. Receives the return value of the decorated function.

**`@invariant(description: str)`**

Marks a method as an invariant check. Invariants should hold true at all times after initialization.

#### `ContractVerifier`

Verifies declared contracts by running them in an isolated subprocess.

```python
ContractVerifier(timeout: float = 5.0)
```

- `timeout`: Maximum time (seconds) per contract verification. If a contract method hangs, it's marked unverified with `error="timeout"`.
- Each contract method is called in isolation — no shared state with other verifications.
- Verification results are cached via `VerifiedContractCache`.

#### `VerifiedContractCache`

Caches verification results to avoid re-verifying on every start.

- Cache key: SHA256 of the worker file.
- Cache location: `~/.hearthphoenix/<worker_hash>/verified_contracts.json`.
- **Known limitation:** If the worker imports other modules and those change, the cache is not invalidated (only the worker file hash is used). Documented in the code as a known limitation.

#### `VerificationReport`

```python
VerificationReport:
    worker_hash: str                    # SHA256 of worker file
    verified: dict[str, bool]           # operation name → verified?
    errors: dict[str, str | None]       # operation name → error message (or None)
    timestamp: float                    # when verification ran
```

#### `ContractViolationError`

Raised when a contract precondition, postcondition, or invariant is violated.

#### `run_contract_verification(worker_path: Path) -> VerificationReport`

Convenience function that runs the full verification pipeline on a worker file. Returns a `VerificationReport`.

---

### `CapabilityScanner` and `Capability`

The capability scanner analyzes worker source code via AST to detect what the worker supports.

#### `Capability` (enum)

```python
class Capability(enum.Enum):
    SIGTERM_HANDLER = "sigterm"                # Handles SIGTERM or SIGINT
    HEALTH_CHECK = "health_check"              # Defines health/status function or /health route
    STATE_SERIALIZATION = "state_serialization" # Defines serialize/deserialize or checkpoint/restore
    WORKER_APP = "worker_app"                  # Subclasses WorkerApp
    KNOWN_TRANSPORT = "known_transport"        # Imports hearthphoenix.transports or references env var
    CONTRACT_DECLARED = "contract_declared"    # Declares a WorkerContract with @contract operations
```

#### `CapabilityScanner`

```python
CapabilityScanner()
```

Scans a Python source file using AST analysis. Detects which `Capability` enums apply.

Detection rules:
- `SIGTERM_HANDLER`: Script handles `SIGTERM` or `SIGINT` (signal.signal, or WorkerApp auto-install).
- `HEALTH_CHECK`: Script defines `health()`, `health_check()`, `status()`, or a `/health` route.
- `STATE_SERIALIZATION`: Script defines `serialize_state`/`deserialize_state` or `checkpoint`/`restore`.
- `WORKER_APP`: Script subclasses `WorkerApp` from `hearthphoenix.worker`.
- `KNOWN_TRANSPORT`: Script references `HEARTH_PHOENIX_TRANSPORT` or imports from `hearthphoenix.transports`.
- `CONTRACT_DECLARED`: Script declares a `WorkerContract` subclass with `@contract`-decorated operations.

#### `CapabilityReport`

```python
CapabilityReport:
    detected: set[Capability]              # Capabilities found
    missing: set[Capability]               # Capabilities not found
    guarantee_level: str                   # Highest GuaranteeLevel name achievable
    risks: list[str]                       # Human-readable warnings
    recommendations: list[str]             # Suggestions to improve cooperation
```

Returned by `CapabilityScanner.scan()` and `Supervisor.wrap_worker()`.

#### `GuaranteeLevel` (legacy enum)

```python
class GuaranteeLevel(enum.IntEnum):
    BRUTE_FORCE = 0       # SIGKILL, cold start, no verification
    GRACEFUL = 1          # SIGTERM handler detected
    HEALTH_VERIFIED = 2   # Health endpoint detected
    STATE_PRESERVING = 3  # State serialization hooks detected
    FULL_COOPERATION = 4  # Full WorkerApp with contracts
```

**Note:** This is the legacy monolithic guarantee level. It's still present for backward compatibility but is superseded by the per-operation `GuaranteeMatrix` system. `CapabilityReport.guarantee_level` returns the highest level achievable.

---

### `GuaranteeMatrix` and `DowngradeEngine`

The per-operation guarantee system. Replaces the legacy monolithic `GuaranteeLevel`.

#### `PerOperationGuarantee` (enum)

```python
class PerOperationGuarantee(enum.Enum):
    GUARANTEED = "guaranteed"        # Verified to work
    BEST_EFFORT = "best_effort"      # Expected to work, not verified
    NOT_SUPPORTED = "not_supported"  # Known to not work
    UNKNOWN = "unknown"              # Not yet checked
```

#### `GuaranteeMatrix`

Computes per-operation guarantee levels from detected capabilities.

```python
GuaranteeMatrix()
```

**`compute(capabilities: set[Capability]) -> dict[Operation, PerOperationGuarantee]`**

Returns a dict mapping each `Operation` to its guarantee level.

Rules:
- `start` → always `GUARANTEED` (nothing needed).
- `rollback` → always `GUARANTEED` (snapshots always work).
- `stop` → `GUARANTEED` if `SIGTERM_HANDLER` detected and verified; otherwise `BEST_EFFORT`.
- `restart` → same as `stop`.
- `health_check` → `GUARANTEED` if `HEALTH_CHECK` detected and verified; otherwise `NOT_SUPPORTED`.
- `hotswap` → `GUARANTEED` if `HEALTH_CHECK` detected; otherwise `BEST_EFFORT`.
- `state_transfer` → `GUARANTEED` if `STATE_SERIALIZATION` detected and verified; otherwise `NOT_SUPPORTED`.

#### `DowngradeEngine`

Handles runtime failure detection and guarantee downgrades.

```python
DowngradeEngine()
```

**`record_failure(operation: Operation, failure_type: str) -> DowngradeResult`**

Records a runtime failure and returns the resulting downgrade.

| Failure type | Affected operation | New guarantee |
|-------------|-------------------|---------------|
| `"sigterm_ignored"` | `stop`, `restart` | `BEST_EFFORT` |
| `"health_timeout"` | `health_check`, `hotswap` | `BEST_EFFORT` |
| `"health_error"` | `health_check`, `hotswap` | `NOT_SUPPORTED` |
| `"serialize_error"` | `state_transfer` | `NOT_SUPPORTED` |
| `"deserialize_error"` | `state_transfer` | `NOT_SUPPORTED` |
| `"state_transfer_crash"` | `state_transfer` | `NOT_SUPPORTED` |

Downgrades persist for the lifetime of the current worker process.

#### `DowngradeResult`

```python
DowngradeResult:
    operation: Operation
    previous: PerOperationGuarantee
    current: PerOperationGuarantee
    reason: str
```

---

### `WorkerApp`

SDK base class for building HearthPhoenix-compatible workers.

**When to use it:** When writing a new worker from scratch. Using `WorkerApp` gives you automatic transport bootstrap, signal handling, and health endpoint registration.

```python
from hearthphoenix.worker import WorkerApp

app = WorkerApp()

@app.health_check
def health():
    return {"status": "ok", "uptime": 123.4}

@app.run
def main():
    # Business logic here
    while True:
        do_work()

@app.shutdown
def cleanup():
    print("Shutting down gracefully")

if __name__ == "__main__":
    app.start()
```

#### Decorators

**`@app.health_check`**

Registers a health check function. Must return a dict (converted to `HealthResult` automatically) or a `HealthResult` directly. The function should be fast (it's called for each health poll).

**`@app.run`**

Registers the main entry point. Required. This function is called after transport bootstrap and signal handler installation. It should block for the lifetime of the worker.

**`@app.shutdown`**

Registers a shutdown handler. Called when the worker receives `SIGTERM`. Use for graceful cleanup — close connections, flush buffers, save state.

#### `app.start()`

Bootstraps the worker:
1. Reads transport configuration from environment variables (`HEARTH_PHOENIX_TRANSPORT`, etc.).
2. Installs the matching transport client.
3. Installs signal handlers (SIGTERM → graceful shutdown, SIGINT → graceful shutdown).
4. Starts the health endpoint.
5. Calls the `@app.run` decorated function.

**Gotcha:** `app.start()` blocks until the `@app.run` function returns or the worker is killed. It does not return normally.

---

### `install_graceful_shutdown`

Standalone function that installs SIGTERM/SIGINT handlers without using `WorkerApp`.

```python
from hearthphoenix.worker.signals import install_graceful_shutdown

def cleanup():
    print("Shutting down...")

install_graceful_shutdown(cleanup)
```

- Registers `cleanup` as the handler for `SIGTERM` and `SIGINT`.
- The handler calls `cleanup()` then exits.
- If `cleanup` takes longer than a timeout (default 5s), the process is forcefully terminated.
- Used internally by `WorkerApp`, but available standalone for workers that don't use the full SDK.

---

## Interface Translation / Wrapping Layer

### `DaemonWrapper`

Top-level orchestrator for wrapping external daemons. Owns daemon lifecycle, interface registry, translation engine, and optional file health monitor.

**When to use it:** When you have an external daemon (a process you don't control) that you want to expose through multiple frontend interfaces. Use `Supervisor.wrap_daemon()` for the quick path, or construct directly for full control.

#### Constructor

```python
DaemonWrapper(
    daemon_cmd: list[str],
    backend: InterfaceAdapter,
    frontends: list[InterfaceAdapter],
    lifecycle: WorkerLifecycle | None = None,
    health_check: Callable[[], HealthResult] | None = None,
    file_monitor: FileHealthMonitor | None = None,
)
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `daemon_cmd` | Yes | Command list to spawn the daemon. |
| `backend` | Yes | Adapter that connects TO the daemon. Must have `direction="backend"` or `direction="bidirectional"`. |
| `frontends` | Yes | List of adapters that expose interfaces TO callers. Must have `direction="frontend"` or `direction="bidirectional"`. |
| `lifecycle` | No | `WorkerLifecycle` for spawn/kill. If `None`, a default is created. |
| `health_check` | No | Custom health callable. If provided, overrides backend health for state-machine decisions. |
| `file_monitor` | No | Optional `FileHealthMonitor` for advisory heartbeat file polling. |

#### Methods

**`start() -> None`**

1. Spawns the daemon via `lifecycle.spawn(daemon_cmd)`.
2. Starts the backend adapter (connects to daemon).
3. Starts all enabled frontend adapters (binds/listens).
4. State → `"running"`.

**`stop() -> None`**

1. Stops all frontend adapters.
2. Stops the backend adapter.
3. Kills the daemon via `lifecycle.kill()`.
4. State → `"stopped"`.

**`status() -> dict`**

Returns:
```python
{
    "daemon_pid": int | None,
    "state": str,                        # "stopped" | "running" | "degraded" | "unrecoverable"
    "backend": {
        "name": str,
        "health": HealthResult,
        "connected": bool,
    },
    "frontends": {
        "<name>": {
            "enabled": bool,
            "health": HealthResult,
            "queue_size": int,
        },
        ...
    },
    "file_monitor": HealthResult | None,  # only if file_monitor configured
}
```

**`toggle_frontend(name: str, enabled: bool) -> None`**

Enables or disables a frontend adapter at runtime without restarting the daemon.

- If enabling: calls `adapter.start()`.
- If disabling: calls `adapter.stop()`.
- The daemon and backend are unaffected.
- Raises `KeyError` if no frontend with that name exists.

#### State Machine

Same states as `Supervisor` (`stopped`, `running`, `degraded`, `unrecoverable`) but driven by backend health (or custom health callable if provided).

---

### `InterfaceRegistry`

Directory of all adapters in a `DaemonWrapper`. Tracks names, types, and enabled/disabled state.

```python
InterfaceRegistry(backend: InterfaceAdapter)
```

The backend adapter is required at construction. Frontends are added afterward via `register()`.

#### Methods

**`register(adapter: InterfaceAdapter, queue_size: int = 100) -> None`**

Registers a frontend adapter by its `name` and allocates a `BoundedQueue(queue_size)` for it.

**`unregister(name: str) -> None`**

Removes a frontend adapter and its queue. Raises `KeyError` if not found.

**`enable(name: str) -> None` / `disable(name: str) -> None`**

Toggle a frontend on/off at runtime. Raises `KeyError` if the name is unknown.

**`list_frontends() -> dict[str, bool]`**

Returns a mapping of frontend name → enabled flag.

**`start_all() -> None` / `stop_all() -> None`**

Start the backend and all enabled frontends / stop all frontends and the backend.

**`get_queue(name: str) -> BoundedQueue | None`**

Returns the frontend's bounded queue (see *Bounded Queue* below).

#### Properties

**`backend -> InterfaceAdapter`** — the backend adapter.
**`frontends -> dict[str, InterfaceAdapter]`** — name → frontend adapter map.

---

### `InterfaceAdapter` (ABC)

Abstract base class for all adapters (frontend, backend, bidirectional).

```python
class InterfaceAdapter:
    name: str
    direction: InterfaceDirection
    supports_passthrough: bool
```

#### Abstract Methods

**`start() -> None`**

Bind/listen (frontend) or connect (backend). Called by `DaemonWrapper.start()` or `toggle_frontend()`.

**`stop() -> None`**

Unbind/disconnect. Called by `DaemonWrapper.stop()` or `toggle_frontend()`.

**`send(message: Message, timeout: float = 30.0) -> Message`**

Send a message and return the response.

- For frontend adapters: receives messages FROM callers and forwards them.
- For backend adapters: sends messages TO the daemon.
- `timeout`: Maximum time to wait for a response.
- Returns a `Message` (never raises on timeout — returns an error `Message`).
- **Gotcha:** The 30-second default timeout may be too long for health checks and too short for long-running daemon operations. Tune per use case.

**`health_check(timeout: float) -> HealthResult`**

Check the adapter's health. For a backend adapter, this checks the daemon connection. For a frontend adapter, this checks the listening socket.

---

### Adapter Implementations

#### `HttpAdapter`

```python
HttpAdapter(
    name: str,
    port: int,
    direction: InterfaceDirection,
    host: str = "127.0.0.1",
)
```

- **Mechanism:** HTTP/1.1 REST server (frontend) or client (backend). JSON body.
- **Frontend mode:** Listens on `host:port`. Responds to HTTP requests, converts to `Message`, and returns JSON responses.
- **Backend mode:** Connects to `host:port` and sends JSON requests.
- **Passthrough:** Yes (`supports_passthrough=True`).
- **Gotcha:** Default host is `127.0.0.1` (localhost only). Change to `0.0.0.0` to expose to the network, but be aware of security implications.

#### `SocketAdapter`

```python
SocketAdapter(
    name: str,
    socket_path: str,
    direction: InterfaceDirection,
    port: int | None = None,       # TCP fallback on Windows
)
```

- **Mechanism:** JSON lines over Unix domain socket (Linux/macOS) or TCP (Windows fallback).
- **Frontend mode:** Binds to `socket_path` and accepts connections.
- **Backend mode:** Connects to `socket_path`.
- **Passthrough:** Yes (`supports_passthrough=True`).
- **Gotcha:** On Unix, `socket_path` must be on a filesystem that supports Unix domain sockets. Clean up the socket file on stop.

#### `CliAdapter`

```python
CliAdapter(
    name: str,
    cmd: list[str],
    direction: InterfaceDirection,
)
```

- **Mechanism:** Spawns a subprocess for each message. Sends JSON on stdin, reads JSON from stdout.
- **Frontend mode:** Callers invoke a CLI command that speaks JSON.
- **Backend mode:** Invokes the daemon's CLI interface.
- **Passthrough:** Yes (`supports_passthrough=True`).
- **Gotcha:** Each message spawns a new subprocess. High-latency, not suitable for high-throughput scenarios.

#### `PipeAdapter`

```python
PipeAdapter(
    name: str,
    direction: InterfaceDirection,
)
```

- **Mechanism:** stdin/stdout JSON lines.
- **Frontend mode:** Reads JSON from stdin, writes responses to stdout.
- **Backend mode:** Writes JSON to daemon stdin, reads from daemon stdout.
- **Passthrough:** Yes (`supports_passthrough=True`).
- **Gotcha:** Only works when the adapter owns the pipe (e.g., wrapper spawning a subprocess). Cannot connect to an already-running daemon's pipes.

---

### `TranslationEngine`

Routes messages between frontend adapters and the backend adapter. Handles passthrough detection and structural translation.

```python
TranslationEngine(
    backend: InterfaceAdapter,
    frontends: dict[str, InterfaceAdapter],
    translator: MessageTranslator | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `backend` | The backend adapter that connects to the daemon. |
| `frontends` | Mapping of frontend name → frontend adapter that exposes interfaces to callers. |
| `translator` | Optional `MessageTranslator`. Defaults to one pre-registered with the 4 built-in adapter wire formats. |

The maximum message size is the module-level constant `MAX_MESSAGE_SIZE` (1 MB); it is not a constructor parameter.

#### Methods

**`route(source: InterfaceAdapter, message: Message) -> Message`**

Routes a message from a frontend to the backend and returns the response.

1. Rejects the message with an `action="error"` `Message` if its serialized size exceeds `MAX_MESSAGE_SIZE`.
2. Derives the source and backend protocol types from each adapter's class name (`_detect_adapter_type`: substring match on `socket`/`http`/`cli`/`pipe`).
3. Passthrough: if the source and backend protocol types match **and** the source has `supports_passthrough=True`, forwards the canonical `Message` directly to the backend (no structural transform).
4. Otherwise takes the translated path: applies any registered `Message → Message` transform for the `(src_type, backend_type)` pair, then forwards. Structural translation is currently identity (proposed-but-unimplemented — see `MessageTranslator.translate`).
5. Sends to backend via `backend.send(message, timeout=30.0)`.

**Gotcha:** The protocol type is derived from the adapter's **class name**, not a `_protocol` attribute or class identity. A custom adapter whose class name contains none of the known substrings gets a type equal to its lowercased class name.

---

### `MessageTranslator`

Handles structural translation between different adapter protocols. Used internally by `TranslationEngine` when passthrough is not possible.

```python
MessageTranslator()
```

**`translate(message: Message, src_type: str, backend_type: str) -> Message`**

Applies a registered `Message → Message` structural transform for the `(src_type, backend_type)` protocol pair (protocol types are short strings like `"socket"`/`"http"`). Returns the message **unchanged** unless a transform has been registered — structural protocol translation is a proposed-but-unimplemented feature, and this method is its extension point.

**`register_transform(src_type: str, backend_type: str, transform) -> None`**

Registers a `Message → Message` callable for a protocol pair, consumed by `translate()`.

**`to_message(adapter_type: str, raw_data) -> Message` / `from_message(adapter_type: str, message: Message) -> Any`**

Convert between a canonical `Message` and an adapter type's wire format, using converters registered via `register()`. The default translator (`_build_default_translator`) pre-registers `socket`/`http`/`cli`/`pipe`.

**Note:** These conversion functions are *not* invoked by `TranslationEngine.route()` — each adapter self-serializes inside its own `send()`. They are scaffolding for the structural-translation feature.

---

### `Message`

Canonical message type for the interface translation layer.

```python
@dataclass(frozen=True)
class Message:
    action: str            # Operation to perform (e.g., "health", "status", "query")
    payload: dict          # Operation-specific data (default: {})
    metadata: dict         # Routing info, timestamps, correlation IDs (default: {})
    version: int = 1       # Message schema version
```

Used as the common currency between adapters. All adapters convert their native wire format to/from `Message`.

**There is no `error` field.** Errors are signaled by convention with `action == "error"` and a `payload` describing the failure — e.g. `Message(action="error", payload={"reason": "message_too_large"})`. The `Message` is frozen (immutable).

---

### `InterfaceDirection` (enum)

```python
class InterfaceDirection(enum.Enum):
    FRONTEND = "frontend"        # Exposes an interface for callers
    BACKEND = "backend"          # Connects to the daemon
    BIDIRECTIONAL = "bidirectional"  # Can serve either role
```

---

### `FileHealthMonitor`

Polls a heartbeat file written by the daemon. Advisory only — does not affect the daemon wrapper state machine.

```python
FileHealthMonitor(heartbeat_path: str, stale_timeout: float = 30.0)
```

| Parameter | Description |
|-----------|-------------|
| `heartbeat_path` | Path to the heartbeat file the daemon writes. |
| `stale_timeout` | Seconds after which the heartbeat is considered stale. Default 30.0. |

#### Methods

**`health_check() -> HealthResult`**

Reads the heartbeat file and returns a `HealthResult`:
- `HEALTHY`: File exists and is newer than `stale_timeout`.
- `DEGRADED`: File exists but is older than `stale_timeout`.
- `UNHEALTHY`: File doesn't exist or can't be read.

**`read_status() -> dict | None`**

Parses the heartbeat file as JSON and returns the dict, or `None` if the file doesn't exist or is invalid JSON.

**Important:** Results appear in `DaemonWrapper.status()["file_monitor"]` but are **advisory only**. They do not drive the state machine. Backend health is canonical.

---

### Bounded Queue

Each frontend adapter has a bounded message queue (default max 100 messages).

```python
BoundedQueue(max_size: int = 100)
```

#### Behavior on Overflow

When the queue is full and a new message arrives:
1. The oldest message is dropped (FIFO eviction).
2. The new message is enqueued.
3. An error `Message` is returned to the caller:
   ```python
   Message(action="error", payload={"reason": "queue_overflow", "dropped": 1})
   ```

This ensures backpressure propagates to callers rather than silently queuing indefinitely.

**Status:** The `BoundedQueue` is allocated per frontend (`InterfaceRegistry.register(queue_size=100)`) and exposed via `get_queue()` / `enqueue_request()`, but it is **not currently exercised by the live request path** — `TranslationEngine.route()` is synchronous (the adapter handler returns a response on the same thread), so it forwards directly to the backend without enqueuing. The drop-oldest overflow policy described here applies if/when an async/streaming request path is added. See `design/adaptive-translation-contracts-design.md` §4.

---

## Environment Variables

### Global Configuration

| Variable | Values | Default | Effect |
|----------|--------|---------|--------|
| `HEARTH_PHOENIX_CONTRACTS` | `1` or `0` | `1` | Enable/disable runtime contract checking globally. Set to `0` to skip all `@precondition`/`@postcondition`/`@invariant` checks and `WorkerContract` verification. |
| `HEARTH_PHOENIX_LOG_FORMAT` | `text` or `json` | `text` | Log output format. `json` emits structured JSON logs for ingestion by log aggregators. |
| `HEARTH_PHOENIX_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` | Logging verbosity. `DEBUG` includes transport-level details and health check latency. |

### Transport Configuration (injected into worker)

These are set by each transport's `configure()` method and injected into the worker's subprocess environment. Workers read them to know which transport to use and how to connect.

| Variable | Transport | Purpose |
|----------|-----------|---------|
| `HEARTH_PHOENIX_TRANSPORT` | All | Transport type identifier: `"rest"`, `"socket"`, `"file"`, `"pipe"`, or `"cli"` |
| `HEARTH_PHOENIX_REST_PORT` | RestTransport | HTTP port for health endpoint |
| `HEARTH_PHOENIX_SOCKET_PATH` | SocketTransport | Path to Unix domain socket |
| `HEARTH_PHOENIX_SOCKET_PORT` | SocketTransport (Windows) | TCP port for socket transport |
| `HEARTH_PHOENIX_FILE_PATH` | FileTransport | Path to shared heartbeat file |
| `HEARTH_PHOENIX_CLI_CMD` | CliTransport | Health check command to execute |

### Configuring Logging

```python
from hearthphoenix import configure_logging

# Human-readable
configure_logging(json_format=False, level="INFO")

# Structured JSON
configure_logging(json_format=True, level="DEBUG")
```

Or use environment variables before importing:
```bash
export HEARTH_PHOENIX_LOG_FORMAT=json
export HEARTH_PHOENIX_LOG_LEVEL=DEBUG
```

---

## Usage Patterns

### Pattern 1: Simple Worker with Auto-Configuration

```python
from hearthphoenix import Supervisor

supervisor, report = Supervisor.wrap_worker("./worker.py")
print(f"Guarantee level: {report.guarantee_level}")
supervisor.start()

# Later, update the worker
result = supervisor.update("./worker_v2.py")
if result["success"]:
    print("Hotswap committed")
else:
    print(f"Hotswap rolled back: {result['health'].status}")

supervisor.stop()
```

### Pattern 2: Manual Setup with Custom Transport

```python
from hearthphoenix import Supervisor, WorkerLifecycle, SnapshotManager
from hearthphoenix.transports import RestTransport

transport = RestTransport(port=9876)
snapshots = SnapshotManager("./snapshots")
lifecycle = WorkerLifecycle(log_mode="inherit")

supervisor = Supervisor(
    transport=transport,
    snapshot_manager=snapshots,
    lifecycle=lifecycle,
    worker_cmd=["python", "worker.py"],
    worker_path="./worker.py",
)
supervisor.start()

# Check status
s = supervisor.status()
print(f"Worker PID: {s['worker_pid']}, State: {s['state']}")
```

### Pattern 3: Worker with WorkerApp SDK

```python
# worker.py
from hearthphoenix.worker import WorkerApp

app = WorkerApp()

@app.health_check
def health():
    return {"status": "ok", "requests_served": request_count}

@app.run
def main():
    # Your business logic
    serve_forever()

@app.shutdown
def cleanup():
    close_connections()

if __name__ == "__main__":
    app.start()
```

### Pattern 4: Worker with Contract Declarations

```python
# worker.py
from hearthphoenix.contracts import WorkerContract, contract, Operation
from hearthphoenix import HealthResult, HealthStatus

class MyContract(WorkerContract):
    @contract(Operation.STOP)
    def graceful_shutdown(self, timeout: float = 5.0) -> bool:
        cleanup()
        return True

    @contract(Operation.HEALTH_CHECK)
    def health(self) -> HealthResult:
        return HealthResult(status=HealthStatus.HEALTHY, details={"load": 0.5}, latency=0.01)

    @contract(Operation.STATE_TRANSFER)
    def serialize(self, path):
        import json
        path.write_text(json.dumps({"counter": counter}))

    @contract(Operation.STATE_TRANSFER)
    def deserialize(self, path):
        import json
        global counter
        counter = json.loads(path.read_text())["counter"]
```

### Pattern 5: Wrapping an External Daemon

```python
from hearthphoenix import Supervisor
from hearthphoenix.wrappers.adapters import SocketAdapter, HttpAdapter, CliAdapter

wrapper, report = Supervisor.wrap_daemon(
    ["./anobios", "--config", "/etc/anobios.conf"],
    backend=SocketAdapter("backend", socket_path="/tmp/anobios.sock", direction="backend"),
    frontends=[
        HttpAdapter("http", port=8080, direction="frontend"),
        SocketAdapter("socket", socket_path="/tmp/hp.sock", direction="frontend"),
        CliAdapter("cli", cmd=["hearthphoenix-cli"], direction="frontend"),
    ],
)

wrapper.start()
print(wrapper.status())

# Disable the HTTP frontend without restarting the daemon
wrapper.toggle_frontend("http", enabled=False)

wrapper.stop()
```

---

## Common Gotchas

1. **`worker_path` must be the actual executed file**, not a wrapper script. The supervisor snapshots and restores this exact path.

2. **PipeTransport and stdout:** The worker must NOT write arbitrary data to stdout. Only JSON lines for the transport. Use stderr for logging.

3. **Health check must return fast.** The supervisor polls health frequently. A slow health check delays detection of worker failure.

4. **Cache invalidation:** Contract verification is cached by worker file hash. If your worker imports other modules and those change, the cache won't invalidate. Delete `~/.hearthphoenix/<hash>/verified_contracts.json` manually after dependency changes.

5. **Only one `update()` at a time.** The supervisor holds a lock during hotswap. Concurrent update calls will block or raise.

6. **Rollback can fail.** If both the new and old worker are unhealthy, the supervisor enters `"unrecoverable"` state. Have a plan for manual recovery.

7. **Adapter passthrough is class-based.** `TranslationEngine` checks `frontend.__class__ == backend.__class__` for passthrough. Wrapping adapters breaks this check.

8. **FileHealthMonitor is advisory.** It won't restart the daemon or affect state. Don't rely on it for automated recovery — use backend health for that.

9. **Unix-first.** SIGTERM, Unix domain sockets, and other primitives are Unix-only. Windows behavior is untested. SocketTransport has a TCP fallback on Windows but it's not validated.

10. **Venv pytest:** The development dependencies (`pytest`, `pytest-asyncio`) must be installed in the virtual environment to run the test suite. See `pyproject.toml` optional-dependencies `dev`.
