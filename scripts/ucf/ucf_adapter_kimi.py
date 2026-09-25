"""Bidirectional deterministic converter: Kimi ↔ UCF."""

import json
import uuid
from ucf_adapter_base import (
    extract_tool_calls, restore_tool_calls,
    content_parts_from_list, content_parts_to_native, build_ucf,
    roundtrip_check, convert_file,
)


ROLE_MAP_FWD = {
    "user": "user", "assistant": "assistant", "tool": "tool_result",
    "_system_prompt": "system", "_usage": "usage", "_checkpoint": "checkpoint",
}
ROLE_MAP_REV = {v: k for k, v in ROLE_MAP_FWD.items()}
TC_EXTRA = ("call_id", "response_item_id")


def kimi_to_ucf_message(msg: dict, prev_id: str | None = None) -> dict:
    role = msg.get("role", "unknown")
    ucf_type = ROLE_MAP_FWD.get(role, "meta")
    msg_id = msg.get("id") or str(uuid.uuid4())
    ts = msg.get("timestamp", 0)
    data: dict = {}
    native: dict = {}

    if ucf_type in ("user", "system"):
        data["content"] = msg.get("content", "")
    elif ucf_type == "assistant":
        content = msg.get("content")
        if isinstance(content, list):
            parts = content_parts_from_list(content)
            native["_content_was_list"] = True
        else:
            parts = []
            if content:
                parts.append({"type": "text", "text": str(content)})
        parts += extract_tool_calls(msg.get("tool_calls", []), TC_EXTRA)
        data["content"] = parts
        for k in ("finish_reason", "reasoning"):
            if k in msg: native[k] = msg[k]
    elif ucf_type == "tool_result":
        data["tool_id"] = msg.get("tool_call_id", "")
        data["content"] = msg.get("content", "")
        if msg.get("is_error"): native["is_error"] = True
        if "name" in msg: native["name"] = msg["name"]
    elif ucf_type == "usage":
        for k in ("input_tokens", "output_tokens", "total_tokens", "token_count"):
            if k in msg: data[k] = msg[k]
    elif ucf_type == "checkpoint":
        data["checkpoint_id"] = msg.get("id", 0)
    else:
        data["raw"] = msg

    for k in ("message_id", "name", "token_count"):
        if k in msg: native[k] = msg[k]

    return build_ucf(ucf_type, msg_id, prev_id, ts, data, native)


def ucf_to_kimi_message(ucf: dict) -> dict:
    role = ROLE_MAP_REV.get(ucf["type"], ucf["type"])
    data = ucf.get("data", {})
    native = data.get("_native", {})
    msg: dict = {"role": role, "id": ucf.get("id"), "timestamp": ucf.get("ts")}

    if role in ("user", "_system_prompt"):
        msg["content"] = data.get("content", "")
    elif role == "assistant":
        parts = data.get("content", [])
        native_parts = [p for p in parts if p.get("type") != "tool_call"]
        tc_parts = [p for p in parts if p.get("type") == "tool_call"]
        was_list = native.get("_content_was_list", False)
        has_non_text = any(p.get("type") != "text" for p in native_parts)
        if was_list or has_non_text:
            msg["content"] = content_parts_to_native(native_parts, think_key="think") if native_parts else []
        elif native_parts:
            text = [p.get("text", "") for p in native_parts if p.get("type") == "text"]
            msg["content"] = "\n".join(text)
        tool_calls = restore_tool_calls(tc_parts, TC_EXTRA)
        if tool_calls: msg["tool_calls"] = tool_calls
        for k in ("finish_reason", "reasoning"):
            if k in native: msg[k] = native[k]
    elif role == "tool":
        msg["tool_call_id"] = data.get("tool_id", "")
        msg["content"] = data.get("content", "")
        if native.get("is_error"): msg["is_error"] = True
        if "name" in native: msg["name"] = native["name"]
    elif role == "_usage":
        for k in ("input_tokens", "output_tokens", "total_tokens", "token_count"):
            if k in data: msg[k] = data[k]
    elif role == "_checkpoint":
        msg["id"] = data.get("checkpoint_id", 0)

    for k in ("message_id", "token_count"):
        if k in native: msg[k] = native[k]

    return msg


def kimi_to_ucf(messages: list[dict]) -> list[dict]:
    result, pid = [], None
    for m in messages:
        u = kimi_to_ucf_message(m, pid); result.append(u); pid = u["id"]
    return result


def ucf_to_kimi(messages: list[dict]) -> list[dict]:
    return [ucf_to_kimi_message(m) for m in messages]


def is_kimi_conv(msg: dict) -> bool:
    return msg.get("role") in ROLE_MAP_FWD


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Kimi ↔ UCF converter")
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
        r = roundtrip_check(msgs, kimi_to_ucf_message, ucf_to_kimi_message, is_kimi_conv)
        t = r["pass"] + r["fail"]
        print(f"Kimi: {r['pass']}/{t} pass ({r['pass']*100//t}%)")
        for a, b in r["failures"]:
            print(f"  Orig: {json.dumps(a)[:120]}")
            print(f"  Back: {json.dumps(b)[:120]}")
    else:
        n = convert_file(args.input, args.output, kimi_to_ucf_message, ucf_to_kimi_message, args.direction)
        print(f"Converted {n} messages")
