"""Bidirectional deterministic converter: DS session JSONL ↔ UCF.

DS session format is OpenAI/DeepSeek chat completions:
  {"role": "system", "content": "..."}
  {"role": "user", "content": "...", "name": "..."}
  {"role": "assistant", "content": "...", "reasoning_content": "...",
   "tool_calls": [{"id":"...","type":"function","function":{"name":"...","arguments":"..."}}]}
  {"role": "tool", "tool_call_id": "...", "content": "..."}
"""

import json
import uuid
from ucf_adapter_base import (
    extract_tool_calls, restore_tool_calls,
    build_ucf, roundtrip_check, convert_file,
)


ROLE_MAP_FWD = {"user": "user", "assistant": "assistant", "tool": "tool_result", "system": "system"}
ROLE_MAP_REV = {v: k for k, v in ROLE_MAP_FWD.items()}


def ds_to_ucf_message(msg: dict, prev_id: str | None = None) -> dict:
    role = msg.get("role", "unknown")
    ucf_type = ROLE_MAP_FWD.get(role, "meta")
    msg_id = str(uuid.uuid4())
    ts = msg.get("timestamp", 0)
    data: dict = {}
    native: dict = {}

    if ucf_type == "user":
        data["content"] = msg.get("content", "")
        if "name" in msg:
            native["name"] = msg["name"]
    elif ucf_type == "assistant":
        parts = []
        if msg.get("reasoning_content"):
            parts.append({"type": "thinking", "thinking": msg["reasoning_content"]})
        if msg.get("content"):
            parts.append({"type": "text", "text": msg["content"]})
        parts += extract_tool_calls(msg.get("tool_calls", []))
        data["content"] = parts
        if "prefix" in msg:
            native["prefix"] = msg["prefix"]
    elif ucf_type == "tool_result":
        data["tool_id"] = msg.get("tool_call_id", "")
        data["content"] = msg.get("content", "")
    elif ucf_type == "system":
        data["content"] = msg.get("content", "")
    else:
        data["raw"] = msg

    return build_ucf(ucf_type, msg_id, prev_id, ts, data, native or None)


def ucf_to_ds_message(ucf: dict) -> dict:
    role = ROLE_MAP_REV.get(ucf["type"], ucf["type"])
    data = ucf.get("data", {})
    native = data.get("_native", {})
    msg: dict = {"role": role}

    if role == "user":
        msg["content"] = data.get("content", "")
        if "name" in native:
            msg["name"] = native["name"]
    elif role == "assistant":
        parts = data.get("content", [])
        text = [p["text"] for p in parts if p.get("type") == "text"]
        thinking = [p["thinking"] for p in parts if p.get("type") == "thinking"]
        tool_calls = restore_tool_calls(parts)
        msg["content"] = "\n".join(text) if text else ""
        if thinking:
            msg["reasoning_content"] = "\n".join(thinking)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if "prefix" in native:
            msg["prefix"] = native["prefix"]
    elif role == "tool":
        msg["tool_call_id"] = data.get("tool_id", "")
        msg["content"] = data.get("content", "")
    elif role == "system":
        msg["content"] = data.get("content", "")

    return msg


def ds_to_ucf(messages: list[dict]) -> list[dict]:
    result, pid = [], None
    for m in messages:
        u = ds_to_ucf_message(m, pid); result.append(u); pid = u["id"]
    return result


def ucf_to_ds(messages: list[dict]) -> list[dict]:
    return [ucf_to_ds_message(m) for m in messages]


def is_ds_conv(msg: dict) -> bool:
    return msg.get("role") in ("user", "assistant", "tool", "system")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="DS session JSONL ↔ UCF converter")
    p.add_argument("input"); p.add_argument("output")
    p.add_argument("--direction", choices=["to-ucf", "from-ucf"], default="to-ucf")
    p.add_argument("--test", action="store_true")
    args = p.parse_args()

    if args.test:
        msgs = []
        with open(args.input) as f:
            for line in f:
                if line := line.strip():
                    msgs.append(json.loads(line))
        r = roundtrip_check(msgs, ds_to_ucf_message, ucf_to_ds_message, is_ds_conv)
        t = r["pass"] + r["fail"]
        print(f"Roundtrip: {r['pass']}/{t} pass ({r['pass']*100//t}%)")
        for a, b in r["failures"]:
            print(f"  Orig: {json.dumps(a)[:150]}")
            print(f"  Back: {json.dumps(b)[:150]}")
    else:
        n = convert_file(args.input, args.output, ds_to_ucf_message, ucf_to_ds_message, args.direction)
        print(f"Converted {n} messages")
