# HearthPhoenix Usage Guide

This document covers the five things you'll actually do with HearthPhoenix, from
simplest to most advanced. If you're new, start at Pattern 1.

Each pattern is a concrete, copy-paste-friendly walkthrough. Deeper explanations
live in [ARCHITECTURE.md](ARCHITECTURE.md) and [API.md](API.md).

---

## Pattern 1: Standalone Worker (No Supervisor)

You don't need a supervisor to use `WorkerApp`. Sometimes you just want the SDK's
signal handling, health endpoints, and clean structure.

### The Worker

```python
# simple_worker.py
from hearthphoenix.worker import WorkerApp

app = WorkerApp()

@app.health_check
def health():
    return {"status": "ok"}

@app.run
def main():
    print("Worker running. Press Ctrl+C to stop.")
    try:
        while True:
            pass  # your business logic here
    except KeyboardInterrupt:
        pass  # WorkerApp handles SIGTERM/SIGINT automatically

@app.shutdown
def cleanup():
    print("Shutting down gracefully...")

if __name__ == "__main__":
    app.start()
```

### Run It

```bash
python simple_worker.py
# Ctrl+C to stop — cleanup() runs automatically
```

### What You Get

- `@app.health_check` registers a health endpoint that any transport can query.
- `@app.shutdown` runs when the process receives SIGTERM or SIGINT.
- `@app.run` is your main loop.
- No supervisor, no hotswap — just clean lifecycle management.

### When to Use

- You're prototyping or developing locally.
- You don't need hotswap yet but want the structure for later.
- You want signal handling without writing it yourself.

### Related Example

`examples/standalone_worker.py`

---

## Pattern 2: Supervised Worker with Hotswap

The flagship feature: an immortal supervisor that can hotswap your worker while
it's running — with automatic rollback if the new version fails health checks.

### The Worker (same as Pattern 1, saved as `worker.py`)

```python
# worker.py — same structure as Pattern 1
from hearthphoenix.worker import WorkerApp

app = WorkerApp()

@app.health_check
def health():
    return {"status": "ok"}

@app.run
def main():
    print("Worker v1 running.")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    app.start()
```

### The Supervisor Script

```python
# run_supervisor.py
from hearthphoenix import Supervisor

# wrap_worker() auto-detects capabilities and picks a transport
supervisor, report = Supervisor.wrap_worker("./worker.py")

print(f"Detected: {report.detected}")
print(f"Guarantee level: {report.guarantee_level}")
print(f"Risks: {report.risks}")

supervisor.start()
print(f"Worker PID: {supervisor.status()['worker_pid']}")

# ...worker is running...

# Update to a new version
result = supervisor.update("./worker_v2.py")
if result["success"]:
    print("Hotswap committed — new version is live.")
else:
    print(f"Hotswap rolled back: {result['health'].status}")
    print(f"Details: {result['health'].details}")

supervisor.stop()
```

### Run It

```bash
# Terminal 1: start the supervisor
python run_supervisor.py

# Terminal 2 (while supervisor is running): trigger an update
# (in a real scenario, you'd replace worker.py with worker_v2.py)
python -c "
from hearthphoenix import Supervisor
# This is conceptual — in practice, trigger update from your deployment system
"
```

### What You Get

- The supervisor monitors the worker process. If it crashes, the supervisor restarts it from the last known good snapshot.
- `supervisor.update()` is transactional: snapshot → stop old → start new → health check → commit or rollback.
- `supervisor.status()` gives you live state: PID, crash count, guarantees, snapshot count.
- `wrap_worker()` auto-selects a transport based on what your worker imports.

### Choosing a Transport Manually

`wrap_worker()` picks a transport for you. To choose one explicitly:

```python
from hearthphoenix import Supervisor, WorkerLifecycle, SnapshotManager
from hearthphoenix.transports import RestTransport

supervisor = Supervisor(
    transport=RestTransport(port=9876),
    snapshot_manager=SnapshotManager("./snapshots"),
    lifecycle=WorkerLifecycle(),
    worker_cmd=["python", "worker.py"],
    worker_path="./worker.py",
)
supervisor.start()
```

Transport tradeoffs:
- **RestTransport**: Debuggable (`curl localhost:9876/health`). Good default.
- **SocketTransport**: Faster, no port conflicts. Unix-only.
- **FileTransport**: No ports or sockets — polls a heartbeat file. Works anywhere.
- **PipeTransport**: stdin/stdout. Zero filesystem footprint. Worker cannot use stdout for logging.
- **CliTransport**: Runs a command for each health check. High overhead, language-agnostic.

### Related Example

`examples/supervised_hotswap.py`

---

## Pattern 3: Adding Contracts and Guarantees

Patterns 1 and 2 work fine without contracts. But if you declare contracts, the
supervisor can **prove** your worker handles certain operations correctly — giving
you `GUARANTEED` instead of `BEST_EFFORT` or `NOT_SUPPORTED`.

### Worker with Contracts

```python
# contract_worker.py
from pathlib import Path
from hearthphoenix.worker import WorkerApp
from hearthphoenix.contracts import WorkerContract, contract, Operation
from hearthphoenix import HealthResult, HealthStatus

app = WorkerApp()

# Declare what your worker supports
class MyContracts(WorkerContract):
    @contract(Operation.STOP)
    def graceful_shutdown(self, timeout: float = 5.0) -> bool:
        """Called during SIGTERM. Return True if clean shutdown."""
        cleanup_resources()
        return True

    @contract(Operation.HEALTH_CHECK)
    def health(self) -> HealthResult:
        """Return current health."""
        return HealthResult(status=HealthStatus.HEALTHY)

    @contract(Operation.STATE_TRANSFER)
    def serialize(self, path: Path) -> None:
        """Save worker state to disk."""
        import json
        path.write_text(json.dumps({"counter": counter}))

    @contract(Operation.STATE_TRANSFER)
    def deserialize(self, path: Path) -> None:
        """Restore worker state from disk."""
        import json
        global counter
        counter = json.loads(path.read_text())["counter"]

# Wire contracts to the app
app.contracts = MyContracts()

@app.health_check
def health():
    return {"status": "ok"}

@app.run
def main():
    global counter
    counter = 0
    while True:
        counter += 1
        # do work

if __name__ == "__main__":
    app.start()
```

### What Changed

With contracts declared:

1. **At startup**, the supervisor runs `ContractVerifier` in an isolated subprocess. Each `@contract` method is called and timed (5-second timeout per contract).

2. **Verified contracts → `GUARANTEED`.** Your `supervisor.status()` now shows:
   ```python
   "per_operation_guarantees": {
       "start": "GUARANTEED",
       "stop": "GUARANTEED",          # because graceful_shutdown passed verification
       "health_check": "GUARANTEED",  # because health() passed verification
       "hotswap": "GUARANTEED",
       "rollback": "GUARANTEED",
       "state_transfer": "GUARANTEED", # because serialize/deserialize passed
       "restart": "GUARANTEED",
   }
   ```

3. **Unverified contracts → `BEST_EFFORT`.** If a contract method times out or raises, that operation gets `BEST_EFFORT` instead of `GUARANTEED`.

4. **Verification is cached** to `~/.hearthphoenix/<worker_hash>/verified_contracts.json`. Subsequent starts skip re-verification.

5. **Runtime failures downgrade.** If `graceful_shutdown()` raises at runtime, `stop` downgrades from `GUARANTEED` to `BEST_EFFORT` for the rest of that worker's lifetime.

### When to Use Contracts

- You need stronger guarantees than "we think this will work."
- You're deploying to production and want the supervisor to catch regressions.
- You have state that must survive hotswaps.

### Gotcha

The cache key is the SHA256 of the worker file only. If your worker imports other
modules and those change, the cache won't invalidate. Delete the cache directory
manually after dependency changes.

### Related Example

`examples/contract_worker.py`

---

## Pattern 4: Wrapping an External Daemon

You have a daemon you can't modify (e.g., a compiled binary that speaks a custom
socket protocol). You want to expose it through HTTP, CLI, and socket interfaces
simultaneously — without touching the daemon's code.

### The Daemon

For this example, we'll wrap a simple echo daemon. In reality, this could be any
process: a database, a message broker, a legacy service.

```python
# echo_daemon.py — a pretend external daemon
import socket, json, sys

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind("/tmp/echo_daemon.sock")
sock.listen(1)
print("Echo daemon listening on /tmp/echo_daemon.sock", flush=True)

while True:
    conn, _ = sock.accept()
    with conn:
        data = conn.recv(4096)
        if data:
            request = json.loads(data)
            response = json.dumps({"echo": request, "status": "ok"})
            conn.sendall(response.encode())
```

### The Wrapper

```python
# wrap_daemon.py
from hearthphoenix import Supervisor
from hearthphoenix.wrappers.adapters import SocketAdapter, HttpAdapter

# The daemon speaks Unix socket JSON. We expose it via:
#   1. HTTP (for debugging / dashboard)
#   2. Another Unix socket (for programmatic access)
wrapper, report = Supervisor.wrap_daemon(
    daemon_cmd=[sys.executable, "./echo_daemon.py"],
    backend=SocketAdapter(
        "backend",
        socket_path="/tmp/echo_daemon.sock",
        direction="backend",        # connects TO the daemon
    ),
    frontends=[
        HttpAdapter(
            "http",
            port=8080,
            direction="frontend",    # exposes TO callers
        ),
        SocketAdapter(
            "socket",
            socket_path="/tmp/hp.sock",
            direction="frontend",
        ),
    ],
)

wrapper.start()
print(wrapper.status())

# Callers can now reach the daemon via:
#   curl -X POST http://localhost:8080/health
#   echo '{"action":"health"}' | nc -U /tmp/hp.sock

# Disable HTTP without restarting the daemon:
wrapper.toggle_frontend("http", enabled=False)
print("HTTP frontend disabled:", wrapper.status()["frontends"]["http"])

wrapper.stop()
```

### What's Happening

```
External caller → HttpAdapter (:8080) ──┐
External caller → SocketAdapter (hp.sock) ──┤
                                            ├── TranslationEngine ──→ Backend (echo_daemon.sock) ──→ Daemon
                                            │
                         (passthrough if same protocol, translate if different)
```

Callers talk to whichever frontend they prefer. The `TranslationEngine` routes
messages to the backend, translating between protocols when necessary. When the
frontend and backend use the same protocol (e.g., socket → socket), messages pass
through without translation — zero overhead.

### Health Aggregation

- **Backend health is canonical.** It drives the wrapper state machine. If the backend goes unhealthy, the wrapper enters `"degraded"` or `"unrecoverable"` state.
- **Frontend health is advisory.** Each frontend's health appears in `status()` but doesn't affect state.
- **FileHealthMonitor is advisory.** If you configure one to poll a heartbeat file, its results are displayed but ignored for state decisions.

### When to Use

- You have a third-party daemon you can't modify.
- You want to add HTTP access to a socket-only daemon.
- You need runtime toggling of interfaces (e.g., disable HTTP during maintenance).

### Related Example

`examples/daemon_wrapper_example.py`

---

## Pattern 5: Crash Recovery and Rollback

HearthPhoenix's safety net: what happens when things go wrong, and how to recover.

### Scenario 1: Worker Crashes at Runtime

If the running worker dies unexpectedly:

1. The monitor thread detects the PID exit.
2. `CrashLoopDetector.record_crash()` is called.
3. If fewer than `crash_threshold` crashes in `crash_window`:
   - The supervisor restores the `.safe` snapshot and restarts the worker.
   - State → `"degraded"`.
4. If crash loop detected (too many crashes too fast):
   - State → `"unrecoverable"`. Manual intervention required.

```python
# Configure crash sensitivity
supervisor = Supervisor(
    ...
    crash_threshold=5,         # allow 5 crashes before crash-loop
    crash_window=60.0,         # within 60 seconds
    cooldown_seconds=15.0,     # wait 15s between restarts
)
```

### Scenario 2: Hotswap Produces an Unhealthy Worker

```python
result = supervisor.update("./worker_broken.py")
# result == {"success": False, "action": "rollback", "health": HealthResult(UNHEALTHY)}

# What happened:
# 1. Snapshot of current worker created
# 2. Old worker killed
# 3. New (broken) worker started
# 4. Health check failed
# 5. New worker killed
# 6. Safe snapshot restored to worker_path
# 7. Old worker restarted
# 8. Old worker health verified

# The supervisor is still running with the old worker.
print(supervisor.status()["state"])  # "running" (or "degraded")
```

### Scenario 3: Rollback Itself Fails

If both the new AND old worker are unhealthy after rollback:

```python
result = supervisor.update("./worker_broken.py")
# result == {"success": False, "action": "rollback", "health": HealthResult(UNHEALTHY)}

print(supervisor.status()["state"])  # "unrecoverable"
# Both versions are bad. Manual recovery needed:
# 1. Fix worker.py
# 2. supervisor.stop()
# 3. Fix the source
# 4. supervisor.start()  (or deploy a known-good snapshot manually)
```

### Scenario 4: Contract Downgrade at Runtime

If a contract-verified operation fails at runtime:

```python
# Worker declared @contract(Operation.STOP) and it was verified.
# At runtime, graceful_shutdown() raises an exception.
# DowngradeEngine detects this:
#   stop: GUARANTEED → BEST_EFFORT
# This downgrade persists for this worker's lifetime.

s = supervisor.status()
print(s["per_operation_guarantees"]["stop"])  # "BEST_EFFORT"
```

### Monitoring

Check `supervisor.status()` regularly. Key fields to watch:

```python
s = supervisor.status()
s["state"]                    # "running" is good; "degraded" needs attention; "unrecoverable" needs you
s["crash_count"]              # nonzero = recent crashes
s["hotswap_risk"]             # human-readable risk assessment
s["per_operation_guarantees"] # per-op guarantee levels
```

### Related Example

`examples/supervised_hotswap.py` (demonstrates update + rollback)

---

## Common Configuration

### Environment Variables

```bash
# Disable contract checking (useful in development)
export HEARTH_PHOENIX_CONTRACTS=0

# Structured JSON logging (for log aggregation)
export HEARTH_PHOENIX_LOG_FORMAT=json
export HEARTH_PHOENIX_LOG_LEVEL=DEBUG

# Text logging (default, human-readable)
export HEARTH_PHOENIX_LOG_FORMAT=text
export HEARTH_PHOENIX_LOG_LEVEL=INFO
```

### Programmatic Logging

```python
from hearthphoenix import configure_logging

# Equivalent to the env vars above
configure_logging(json_format=True, level="DEBUG")
```

### Transport Selection

| If you need... | Use... | Because... |
|---------------|--------|------------|
| Easy debugging | `RestTransport` | `curl localhost:9876/health` just works |
| Speed, no port conflicts | `SocketTransport` | Unix domain sockets are fast and local |
| Container/deployment simplicity | `FileTransport` | No ports, no sockets — just a file |
| Zero filesystem footprint | `PipeTransport` | stdin/stdout, no files at all |
| Language-agnostic worker | `RestTransport` or `CliTransport` | HTTP or subprocess — any language works |

### Snapshot Directory

Snapshots live under the path you pass to `SnapshotManager`:
```
./snapshots/
├── snapshot-20250101-120000/
├── snapshot-20250101-130000/
├── safe -> snapshot-20250101-120000/
```

The `safe` symlink is the rollback target. Never delete it manually.

### Contract Cache

```
~/.hearthphoenix/
└── <sha256_of_worker_file>/
    └── verified_contracts.json
```

Delete the hash directory to force re-verification on next start. Needed after
dependency changes (cache key is worker file hash only — a known limitation).

---

## Next Steps

- [ARCHITECTURE.md](ARCHITECTURE.md) — deep dive into design, data flow, threading, sequences.
- [API.md](API.md) — full reference for every class and method.
- [examples/](../examples/) — runnable example scripts for each pattern.
