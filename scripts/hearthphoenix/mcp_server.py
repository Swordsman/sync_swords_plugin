"""Minimal MCP server exposing a worker's interface as tools.

Stage 2 of design/mcp-transport-and-herd-manager.md: a stdio MCP server
(newline-delimited JSON-RPC 2.0) whose tool list is generated live from
the worker object via :mod:`hearthphoenix.mcp_schema`. Because the tool
list is regenerated on every ``tools/list`` request, a hotswapped worker
exposes its new capabilities to agents immediately — no restart, no
manual schema update. ``schema_fingerprint`` lets the host emit a
``notifications/tools/list_changed`` after a swap.

Pure stdlib — no MCP SDK. Usage:

    # As a library (e.g. from a daemon under a bootstrap):
    serve_worker(MyWorker())                      # blocks on stdio

    # From the shell:
    python -m hearthphoenix.mcp_server mypkg.workers:EchoWorker
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any, Callable, Dict, Optional, TextIO

from .mcp_schema import generate_tools, schema_fingerprint

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "hearthphoenix-worker", "version": "0.2.0"}

# JSON-RPC error codes
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class McpWorkerServer:
    """Serve one worker object's public interface over MCP stdio."""

    def __init__(self, worker: Any,
                 include: Optional[Callable[[str, Callable], bool]] = None) -> None:
        self.worker = worker
        self.include = include

    # -- tool surface (regenerated per request: hotswap-live) -------------

    def tools(self) -> list:
        return generate_tools(self.worker, include=self.include)

    def fingerprint(self) -> str:
        return schema_fingerprint(self.tools())

    def swap_worker(self, new_worker: Any,
                    out_stream: Optional[TextIO] = None) -> bool:
        """Replace the served worker (transactional hotswap seam).

        Emits ``notifications/tools/list_changed`` on *out_stream* (default
        stdout) when the interface fingerprint actually changed. Returns
        True if a notification was sent.
        """
        old_fp = self.fingerprint()
        self.worker = new_worker
        if self.fingerprint() == old_fp:
            return False
        stdout = out_stream if out_stream is not None else sys.stdout
        stdout.write(json.dumps(
            {"jsonrpc": "2.0",
             "method": "notifications/tools/list_changed"}) + "\n")
        stdout.flush()
        return True

    # -- request handling --------------------------------------------------

    def handle(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """One JSON-RPC request → response dict (None for notifications)."""
        method = request.get("method", "")
        req_id = request.get("id")
        is_notification = "id" not in request
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": SERVER_INFO,
                }
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                result = self._call_tool(request.get("params") or {})
            elif method == "ping":
                result = {}
            elif method.startswith("notifications/"):
                return None
            else:
                if is_notification:
                    return None
                return _error(req_id, METHOD_NOT_FOUND,
                              f"method not found: {method}")
        except _ParamError as e:
            return _error(req_id, INVALID_PARAMS, str(e))
        except Exception as e:
            return _error(req_id, INTERNAL_ERROR, f"{type(e).__name__}: {e}")
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        if not name or name.startswith("_"):
            raise _ParamError(f"invalid tool name: {name!r}")
        known = {t["name"] for t in self.tools()}
        if name not in known:
            raise _ParamError(f"unknown tool: {name!r}")
        fn = getattr(self.worker, name)
        arguments = params.get("arguments") or {}
        try:
            value = fn(**arguments)
        except TypeError as e:
            raise _ParamError(f"bad arguments for {name}: {e}") from e
        except Exception as e:
            return {"content": [{"type": "text",
                                 "text": f"{type(e).__name__}: {e}"}],
                    "isError": True}
        try:
            text = value if isinstance(value, str) else json.dumps(value)
        except TypeError:
            text = repr(value)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    # -- stdio loop --------------------------------------------------------

    def serve(self, in_stream: Optional[TextIO] = None,
              out_stream: Optional[TextIO] = None) -> None:
        """Blocking newline-delimited JSON-RPC loop (MCP stdio transport)."""
        stdin = in_stream if in_stream is not None else sys.stdin
        stdout = out_stream if out_stream is not None else sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                response: Optional[Dict[str, Any]] = _error(
                    None, PARSE_ERROR, f"parse error: {e}")
            else:
                response = self.handle(request)
            if response is not None:
                stdout.write(json.dumps(response) + "\n")
                stdout.flush()


class _ParamError(ValueError):
    pass


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def serve_worker(worker: Any, **kwargs) -> None:
    """Serve *worker* over MCP stdio (blocks)."""
    McpWorkerServer(worker, **kwargs).serve()


def main(argv: Optional[list] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or ":" not in args[0]:
        print("usage: python -m hearthphoenix.mcp_server MODULE:CLASS",
              file=sys.stderr)
        return 2
    module_name, class_name = args[0].split(":", 1)
    cls = getattr(importlib.import_module(module_name), class_name)
    serve_worker(cls())
    return 0


if __name__ == "__main__":
    sys.exit(main())
