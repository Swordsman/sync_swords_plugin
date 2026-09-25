"""Shared utilities for UCF adapters. Each adapter provides its own:
  - ROLE_MAP: {native_role: ucf_type}
  - msg_to_ucf(msg, prev_id) -> dict
  - ucf_to_msg(ucf) -> dict
"""

import json
from pathlib import Path


def parse_tool_args(args, keep_raw: bool = False) -> dict:
    """Parse tool call arguments. If keep_raw=True and args is a string,
    returns {"_raw": args} to preserve exact formatting for roundtrips."""
    """Parse tool call arguments, handling both dict and JSON string forms."""
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": args}
    return args if isinstance(args, dict) else {}


def extract_tool_calls(tool_calls: list[dict], extra_fields: tuple = ()) -> list[dict]:
    """Extract tool calls into UCF parts. Preserves raw argument string in _native."""
    parts = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "{}")
        part = {
            "type": "tool_call",
            "tool_id": tc.get("id", ""),
            "tool_name": fn.get("name", ""),
            "arguments": parse_tool_args(raw_args) if isinstance(raw_args, str) else (raw_args if isinstance(raw_args, dict) else {}),
        }
        native = {}
        if isinstance(raw_args, str):
            native["_raw_args"] = raw_args
        for k in extra_fields:
            if k in tc:
                native[k] = tc[k]
        if native:
            part["_native"] = native
        parts.append(part)
    return parts


def restore_tool_calls(parts: list[dict], extra_fields: tuple = ()) -> list[dict]:
    """Restore tool calls from UCF parts. Uses raw args if preserved."""
    result = []
    for p in parts:
        if p.get("type") != "tool_call":
            continue
        extra = p.get("_native", {})
        args = extra.get("_raw_args") or json.dumps(p.get("arguments", {}))
        tc = {
            "id": p.get("tool_id", ""),
            "type": "function",
            "function": {
                "name": p.get("tool_name", ""),
                "arguments": args,
            },
        }
        for k in extra_fields:
            if k in extra:
                tc[k] = extra[k]
        result.append(tc)
    return result


def restore_tool_calls(parts: list[dict], extra_fields: tuple = ()) -> list[dict]:
    """Restore tool calls from UCF parts. Uses raw args if preserved."""
    result = []
    for p in parts:
        if p.get("type") != "tool_call":
            continue
        extra = p.get("_native", {})
        args = extra.get("_raw_args") or json.dumps(p.get("arguments", {}))
        tc = {
            "id": p.get("tool_id", ""),
            "type": "function",
            "function": {
                "name": p.get("tool_name", ""),
                "arguments": args,
            },
        }
        for k in extra_fields:
            if k in extra:
                tc[k] = extra[k]
        result.append(tc)
    return result


def content_parts_from_list(content: list) -> list[dict]:
    """Convert native content parts to UCF content parts.
    Handles text, text-like, thinking, think, tool_use, tool_call, tool_result.
    Preserves extra fields in _native.
    """
    parts = []
    for p in content:
        if not isinstance(p, dict):
            continue
        pt = p.get("type")
        part = None

        if pt in ("text",):
            part = {"type": "text", "text": p.get("text", "")}
            extra = {k: v for k, v in p.items() if k not in ("type", "text")}
        elif pt in ("thinking", "think"):
            part = {"type": "thinking", "thinking": p.get("thinking") or p.get("think", "")}
            extra = {k: v for k, v in p.items() if k not in ("type", "thinking", "think")}
        elif pt == "tool_use":
            part = {
                "type": "tool_call",
                "tool_id": p.get("id", ""),
                "tool_name": p.get("name", ""),
                "arguments": p.get("input", {}),
            }
            extra = {k: v for k, v in p.items() if k not in ("type", "id", "name", "input")}
        elif pt == "tool_result":
            part = {
                "type": "tool_result",
                "tool_id": p.get("tool_use_id", ""),
                "content": p.get("content", ""),
            }
            if p.get("is_error"):
                part["is_error"] = True
            extra = {k: v for k, v in p.items() if k not in ("type", "tool_use_id", "content", "is_error")}
        else:
            continue

        if extra:
            part["_native"] = extra
        parts.append(part)
    return parts


def content_parts_to_native(parts: list[dict], think_key: str = "think") -> list[dict]:
    """Convert UCF content parts back to native format.
    think_key: "think" for Kimi, "thinking" for Anthropic.
    """
    result = []
    for p in parts:
        pt = p.get("type")
        item = None
        if pt == "text":
            item = {"type": "text", "text": p.get("text", "")}
        elif pt == "thinking":
            item = {"type": think_key, think_key: p.get("thinking", "")}
        elif pt == "tool_call":
            item = {
                "type": "tool_use",
                "id": p.get("tool_id", ""),
                "name": p.get("tool_name", ""),
                "input": p.get("arguments", {}),
            }
        elif pt == "tool_result":
            item = {
                "type": "tool_result",
                "tool_use_id": p.get("tool_id", ""),
                "content": p.get("content", ""),
            }
            if "is_error" in p:
                item["is_error"] = p["is_error"]
        else:
            continue
        extra = p.get("_native", {})
        item.update(extra)
        result.append(item)
    return result


def build_ucf(msg_type: str, msg_id: str, prev_id: str | None,
              ts, data: dict, native: dict | None = None) -> dict:
    """Build a UCF record."""
    if native:
        data = dict(data)
        data["_native"] = native
    return {"v": 1, "type": msg_type, "id": msg_id, "parent_id": prev_id, "ts": ts, "data": data}


# ── Roundtrip testing ───────────────────────────────────────────────

def roundtrip_check(messages: list[dict], to_ucf_fn, from_ucf_fn,
                   is_conv_fn=None) -> dict:
    """Generic roundtrip test. If is_conv_fn is provided, only test messages
    where is_conv_fn(msg) is True — others are assumed passthrough."""
    result = {"pass": 0, "fail": 0, "failures": []}
    for msg in messages:
        if is_conv_fn and not is_conv_fn(msg):
            result["pass"] += 1
            continue
        ucf = to_ucf_fn(msg, None)
        if ucf is None:
            result["pass"] += 1
            continue
        back = from_ucf_fn(ucf)
        if _msg_equal(msg, back):
            result["pass"] += 1
        else:
            result["fail"] += 1
            if len(result["failures"]) < 3:
                result["failures"].append((msg, back))
    return result


def _msg_equal(a: dict, b: dict) -> bool:
    """Compare two messages for semantic equality.
    Only compares keys present in the original (a)."""
    common = {k for k in a if k in b}
    a_s = {k: a[k] for k in common}
    b_s = {k: b[k] for k in common}
    return a_s == b_s


# ── File I/O ────────────────────────────────────────────────────────

def load_jsonl(path: str) -> list[dict]:
    messages = []
    with open(path) as f:
        for line in f:
            if line := line.strip():
                messages.append(json.loads(line))
    return messages


def save_jsonl(path: str, messages: list[dict]) -> int:
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return len(messages)


def convert_file(input_path: str, output_path: str,
                 to_ucf_fn, from_ucf_fn, direction: str = "to-ucf"):
    messages = load_jsonl(input_path)
    if direction == "to-ucf":
        result = []
        prev_id = None
        for msg in messages:
            ucf = to_ucf_fn(msg, prev_id)
            if ucf:
                result.append(ucf)
                prev_id = ucf["id"]
    else:
        result = [from_ucf_fn(m) for m in messages]
    return save_jsonl(output_path, result)
