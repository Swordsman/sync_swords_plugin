#!/usr/bin/env python3
"""Example HTTP worker using the REST transport."""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from hearthphoenix.worker import WorkerApp

app = WorkerApp()
port = int(os.environ.get("HEARTH_PHOENIX_REST_PORT", "9876"))

logging.basicConfig(level=logging.INFO)


@app.health_check
def health():
    return {"status": "ok", "service": "http_worker"}


@app.run
def main():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body = json.dumps(health()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            logging.info(format, *args)

    server = HTTPServer(("127.0.0.1", port), Handler)
    logging.info("HTTP worker listening on port %s", port)
    server.serve_forever()


if __name__ == "__main__":
    app.start()
