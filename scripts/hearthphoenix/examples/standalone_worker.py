#!/usr/bin/env python3
"""Pattern 1: Standalone Worker (no supervisor).

The simplest possible HearthPhoenix worker. Uses WorkerApp for clean
lifecycle management without any supervisor process.

Run:
    python examples/standalone_worker.py
    # Press Ctrl+C to stop — notice the shutdown message

What it demonstrates:
    - @app.health_check — registers a health endpoint
    - @app.run — your main business logic
    - @app.shutdown — graceful cleanup on SIGTERM/SIGINT
"""

import time
import logging

from hearthphoenix.worker import WorkerApp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("standalone_worker")

app = WorkerApp()


@app.health_check
def health():
    """Called by transports to check worker health. Must return a dict."""
    return {"status": "ok", "service": "standalone_worker", "uptime": time.time() - start_time}


@app.run
def main():
    """Your business logic. This blocks for the lifetime of the worker."""
    global start_time
    start_time = time.time()
    logger.info("Worker started. Press Ctrl+C to stop.")
    try:
        while True:
            logger.info("Doing work...")
            time.sleep(5)
    except KeyboardInterrupt:
        pass  # WorkerApp handles SIGTERM/SIGINT via @app.shutdown


@app.shutdown
def cleanup():
    """Called on SIGTERM or SIGINT. Clean up resources here."""
    logger.info("Shutting down gracefully...")


if __name__ == "__main__":
    app.start()
