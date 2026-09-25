"""MCP tool-schema generation from a worker's interface.

The reusable core of design/mcp-transport-and-herd-manager.md: walk an
object's public callable interface and produce MCP-style tool
definitions — name from the function name, description from the
docstring, input schema from type hints. Because generation is a pure
function of the object, the schema can be regenerated the moment a
worker is hotswapped, which is the design's central requirement: agents
discover new tools the moment they exist.

No MCP SDK dependency — the output is plain dicts in the MCP tool-list
shape, consumable by any server implementation (stage 2 of the design
wires these into an actual MCP transport).
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Dict, List, Optional, get_args, get_origin

_TYPE_MAP: Dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
    type(None): "null",
}


def _json_type(annotation: Any) -> Dict[str, Any]:
    """Best-effort JSON-schema fragment for a Python type annotation."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    origin = get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        schema = _json_type(args[0]) if len(args) == 1 else {}
        if type(None) in get_args(annotation):
            # Optional[X] — nullable is expressed by omitting "required";
            # keep the base type here.
            return schema
        return schema
    if origin in (list, tuple, set):
        item_args = get_args(annotation)
        items = _json_type(item_args[0]) if item_args else {}
        return {"type": "array", **({"items": items} if items else {})}
    if origin is dict:
        return {"type": "object"}
    if annotation in _TYPE_MAP:
        return {"type": _TYPE_MAP[annotation]}
    if isinstance(annotation, str):
        # Unresolved forward reference / from __future__ annotations
        lowered = annotation.strip()
        for py, js in (("str", "string"), ("int", "integer"),
                       ("float", "number"), ("bool", "boolean"),
                       ("dict", "object"), ("list", "array")):
            if lowered == py or lowered.startswith(py + "["):
                return {"type": js}
        return {}
    return {}


def tool_from_callable(name: str, fn: Callable) -> Dict[str, Any]:
    """One MCP tool definition for a callable."""
    doc = inspect.getdoc(fn) or ""
    description = doc.split("\n\n")[0].strip() if doc else name
    properties: Dict[str, Any] = {}
    required: List[str] = []
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    if sig is not None:
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            properties[pname] = _json_type(hints.get(pname, param.annotation))
            if param.default is inspect.Parameter.empty:
                required.append(pname)
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


def generate_tools(worker: Any,
                   include: Optional[Callable[[str, Callable], bool]] = None,
                   ) -> List[Dict[str, Any]]:
    """MCP tool definitions for a worker's public callable interface.

    Public = attribute names not starting with underscore that resolve to
    callables. *include* further filters (name, callable) pairs. The
    result is deterministic (sorted by name) so schema diffs across
    hotswaps are meaningful.
    """
    tools: List[Dict[str, Any]] = []
    for name in dir(worker):
        if name.startswith("_"):
            continue
        member = getattr(worker, name, None)
        if not callable(member) or inspect.isclass(member):
            continue
        if include is not None and not include(name, member):
            continue
        tools.append(tool_from_callable(name, member))
    tools.sort(key=lambda t: t["name"])
    return tools


def schema_fingerprint(tools: List[Dict[str, Any]]) -> str:
    """Stable hash of a tool list — changes exactly when the interface does.

    Compare across a hotswap to know whether connected agents must be
    notified of a tool-list change.
    """
    import hashlib
    import json
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
