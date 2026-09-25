#!/usr/bin/env python3
"""Pattern 3: Worker with Contracts and Guarantees.

Demonstrates declaring WorkerContract operations so the supervisor can
verify them and provide GUARANTEED guarantees instead of BEST_EFFORT.

What contracts give you:
    - GUARANTEED: The supervisor proved this operation works
    - BEST_EFFORT: The supervisor thinks this will work (unverified)
    - NOT_SUPPORTED: The supervisor knows this won't work
    - UNKNOWN: Not yet checked

Run as a standalone worker (no supervisor) to see contract structure:
    python examples/contract_worker.py

To use with a supervisor, wrap this file with Supervisor.wrap_worker() and
check supervisor.status()["per_operation_guarantees"] after start.

See also:
    readme-docs/USAGE.md — Pattern 3 walkthrough
    readme-docs/API.md — Contract system reference
"""

import json
import logging
from pathlib import Path

from hearthphoenix.worker import WorkerApp
from hearthphoenix.contracts import WorkerContract, contract, Operation
from hearthphoenix import HealthResult, HealthStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("contract_worker")

app = WorkerApp()

# In-memory state we want to preserve across hotswaps
counter = 0


# ── Contract Declarations ──────────────────────────────────────────────
# These tell the supervisor: "I handle these operations. Verify me."

class MyContracts(WorkerContract):
    """Declares which operations this worker supports contractually."""

    @contract(Operation.STOP)
    def graceful_shutdown(self, timeout: float = 5.0) -> bool:
        """Handle SIGTERM. Return True if clean shutdown achieved."""
        logger.info("Graceful shutdown called (timeout=%s)", timeout)
        # Real workers would close connections, flush buffers, etc.
        return True

    @contract(Operation.HEALTH_CHECK)
    def health(self) -> HealthResult:
        """Return structured health status."""
        return HealthResult(
            status=HealthStatus.HEALTHY,
            details={"counter": counter, "service": "contract_worker"},
            latency=0.001,
        )

    @contract(Operation.STATE_TRANSFER)
    def serialize(self, path: Path) -> None:
        """Save worker state so it survives a hotswap."""
        logger.info("Serializing state to %s (counter=%d)", path, counter)
        path.write_text(json.dumps({"counter": counter}))

    @contract(Operation.STATE_TRANSFER)
    def deserialize(self, path: Path) -> None:
        """Restore worker state after a hotswap."""
        global counter
        data = json.loads(path.read_text())
        counter = data["counter"]
        logger.info("Deserialized state from %s (counter=%d)", path, counter)


# Attach contracts to the WorkerApp
app.contracts = MyContracts()


# ── Standard WorkerApp hooks ───────────────────────────────────────────

@app.health_check
def health():
    """Simple health check (also covered by the contract above)."""
    return {"status": "ok", "counter": counter}


@app.run
def main():
    """Main business logic."""
    global counter
    logger.info("Contract worker started. Counter initialized to %d.", counter)
    try:
        while True:
            counter += 1
            logger.info("Working... counter=%d", counter)
            import time
            time.sleep(3)
    except KeyboardInterrupt:
        pass


@app.shutdown
def cleanup():
    logger.info("Shutdown handler called (counter=%d).", counter)


if __name__ == "__main__":
    app.start()
