"""Bidirectional deterministic converter: Hermes ↔ UCF.

Hermes has three on-disk formats:
  1. JSONL context window (~/.hermes/sessions/<id>.jsonl)
     - First line may be role=session_meta (tools, model, platform)
     - Subsequent lines are messages with timestamps as ISO 8601
  2. Session JSON (~/.hermes/sessions/session_<id>.json)
     - Envelope: {session_id, model, base_url, platform, system_prompt, tools, messages}
  3. Saved JSON (~/.hermes/sessions/saved/hermes_conversation_<id>.json)
     - Envelope: {model, session_id, session_start, messages}

All three share the same message format within the messages array/lines.
"""

import json
import uuid
from datetime import datetime, timezone
from ucf_adapter_base import (
    extract_tool_calls, restore_tool_calls,
    build_ucf, roundtrip_check, convert_file, load_jsonl, save_jsonl,
)


ROLE_MAP_FWD = {"user": "user", "assistant": "assistant", "tool": "tool_result", "system": "system"}
ROLE_MAP_REV = {v: k for k, v in ROLE_MAP_FWD.items()}
TC_EXTRA = ("call_id", "response_item_id")


def _parse_ts(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _restore_ts(ts: float, as_iso: bool = False):
    if as_iso and ts > 0:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return ts


def hermes_to_ucf_message(msg: dict, prev_id: str | None = None) -> dict | None:
    role = msg.get("role", "unknown")

    if role == "session_meta":
        msg_id = str(uuid.uuid4())
        data = {k: v for k, v in msg.items() if k != "role"}
        return build_ucf("meta", msg_id, prev_id, _parse_ts(msg.get("timestamp", 0)), {"subtype": "session_meta", **data})

    ucf_type = ROLE_MAP_FWD.get(role, "meta")
    msg_id = msg.get("id") or str(uuid.uuid4())
    ts = _parse_ts(msg.get("timestamp", 0))
    data: dict = {}
    native: dict = {}

    if ucf_type == "user":
        data["content"] = msg.get("content", "")
        for k in ("message_id",):
            if k in msg:
                native[k] = msg[k]
        if msg.get("_empty_recovery_synthetic"):
            native["_empty_recovery_synthetic"] = True
    elif ucf_type == "assistant":
        parts = []
        rc = msg.get("reasoning_content") or ""
        if rc:
            parts.append({"type": "thinking", "thinking": rc})
        if msg.get("content"):
            parts.append({"type": "text", "text": msg["content"]})
        parts += extract_tool_calls(msg.get("tool_calls", []), TC_EXTRA)
        data["content"] = parts
        for k in ("finish_reason", "reasoning"):
            if k in msg:
                native[k] = msg[k]
        if msg.get("_empty_recovery_synthetic"):
            native["_empty_recovery_synthetic"] = True
    elif ucf_type == "tool_result":
        data["tool_id"] = msg.get("tool_call_id", "")
        data["content"] = msg.get("content", "")
        for k in ("name", "tool_name"):
            if k in msg:
                native[k] = msg[k]
    elif ucf_type == "system":
        data["content"] = msg.get("content", "")
    else:
        data["raw"] = msg

    # preserve original timestamp format for roundtrip
    if isinstance(msg.get("timestamp"), str):
        native["_ts_iso"] = msg["timestamp"]

    return build_ucf(ucf_type, msg_id, prev_id, ts, data, native or None)


def ucf_to_hermes_message(ucf: dict) -> dict:
    data = ucf.get("data", {})
    native = data.get("_native", {})

    if ucf["type"] == "meta" and data.get("subtype") == "session_meta":
        msg = {k: v for k, v in data.items() if k not in ("_native", "subtype")}
        msg["role"] = "session_meta"
        if native.get("_ts_iso"):
            msg["timestamp"] = native["_ts_iso"]
        return msg

    role = ROLE_MAP_REV.get(ucf["type"], ucf["type"])
    msg: dict = {"role": role}

    # restore timestamp
    if native.get("_ts_iso"):
        msg["timestamp"] = native["_ts_iso"]
    elif ucf.get("ts", 0) > 0:
        msg["timestamp"] = ucf["ts"]

    if role == "user":
        msg["content"] = data.get("content", "")
        for k in ("message_id",):
            if k in native:
                msg[k] = native[k]
        if native.get("_empty_recovery_synthetic"):
            msg["_empty_recovery_synthetic"] = True
    elif role == "assistant":
        parts = data.get("content", [])
        text = [p["text"] for p in parts if p.get("type") == "text"]
        thinking = [p["thinking"] for p in parts if p.get("type") == "thinking"]
        tool_calls = restore_tool_calls(parts, TC_EXTRA)
        msg["content"] = "\n".join(text)
        if thinking:
            msg["reasoning_content"] = "\n".join(thinking)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        for k in ("finish_reason", "reasoning"):
            if k in native:
                msg[k] = native[k]
        if native.get("_empty_recovery_synthetic"):
            msg["_empty_recovery_synthetic"] = True
    elif role == "tool":
        msg["tool_call_id"] = data.get("tool_id", "")
        msg["content"] = data.get("content", "")
        for k in ("name", "tool_name"):
            if k in native:
                msg[k] = native[k]
    elif role == "system":
        msg["content"] = data.get("content", "")

    return msg


def hermes_to_ucf(messages: list[dict]) -> list[dict]:
    result, pid = [], None
    for m in messages:
        u = hermes_to_ucf_message(m, pid)
        if u:
            result.append(u)
            pid = u["id"]
    return result


def ucf_to_hermes(messages: list[dict]) -> list[dict]:
    return [ucf_to_hermes_message(m) for m in messages]


def is_hermes_conv(msg: dict) -> bool:
    return msg.get("role") in ("user", "assistant", "tool", "system", "session_meta")


# ── File loading helpers ───────────────────────────────────────────

def load_hermes_file(path: str) -> tuple[list[dict], dict | None]:
    """Load any Hermes file format. Returns (messages, envelope_or_None)."""
    if path.endswith(".jsonl"):
        return load_jsonl(path), None
    with open(path) as f:
        data = json.load(f)
    envelope = {k: v for k, v in data.items() if k != "messages"}
    return data.get("messages", []), envelope


def save_hermes_file(path: str, messages: list[dict], envelope: dict | None = None):
    """Save in the appropriate Hermes format based on extension."""
    if path.endswith(".jsonl"):
        save_jsonl(path, messages)
    else:
        data = dict(envelope or {})
        data["messages"] = messages
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Hermes ↔ UCF converter")
    p.add_argument("input"); p.add_argument("output")
    p.add_argument("--direction", choices=["to-ucf", "from-ucf"], default="to-ucf")
    p.add_argument("--test", action="store_true")
    args = p.parse_args()

    if args.test:
        msgs, _ = load_hermes_file(args.input)
        r = roundtrip_check(msgs, hermes_to_ucf_message, ucf_to_hermes_message, is_hermes_conv)
        t = r["pass"] + r["fail"]
        print(f"Roundtrip: {r['pass']}/{t} pass ({r['pass']*100//t if t else 0}%)")
        for a, b in r["failures"]:
            print(f"  Orig: {json.dumps(a)[:150]}")
            print(f"  Back: {json.dumps(b)[:150]}")
    else:
        msgs, _ = load_hermes_file(args.input)
        if args.direction == "to-ucf":
            result = hermes_to_ucf(msgs)
        else:
            result = ucf_to_hermes(result := load_jsonl(args.input))
        save_jsonl(args.output, result)
        print(f"Converted {len(result)} messages")
