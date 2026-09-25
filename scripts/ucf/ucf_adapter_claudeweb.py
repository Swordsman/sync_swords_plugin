"""Bidirectional deterministic converter: Claude Web export ↔ UCF.

Claude Web exports are JSON arrays of conversations, each containing
chat_messages with sender (human/assistant), content blocks (text,
thinking, tool_use, tool_result, token_budget, flag), timestamps,
attachments, and files.

The adapter operates at message level. Use load_claudeweb_file() to
extract conversations, then convert individual message arrays.
"""

import json
import uuid
from datetime import datetime, timezone
from ucf_adapter_base import build_ucf, roundtrip_check


SENDER_MAP_FWD = {"human": "user", "assistant": "assistant"}
SENDER_MAP_REV = {v: k for k, v in SENDER_MAP_FWD.items()}

BLOCK_CORE_FIELDS = {
    "text": ("text",),
    "thinking": ("thinking", "summaries", "cut_off", "truncated", "signature", "alternative_display_type"),
    "tool_use": ("id", "name", "input"),
    "tool_result": ("tool_use_id", "name", "content", "structured_content", "is_error"),
    "token_budget": (),
    "flag": ("flag", "helpline"),
}


def _parse_ts(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            s = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _block_to_ucf(block: dict) -> dict:
    btype = block.get("type", "unknown")

    if btype == "text":
        part = {"type": "text", "text": block.get("text", "")}
        core_keys = {"type", "text"}
    elif btype == "thinking":
        part = {"type": "thinking", "thinking": block.get("thinking", "")}
        core_keys = {"type", "thinking"}
    elif btype == "tool_use":
        part = {
            "type": "tool_call",
            "tool_id": block.get("id", ""),
            "tool_name": block.get("name", ""),
            "arguments": block.get("input", {}),
        }
        core_keys = {"type", "id", "name", "input"}
    elif btype == "tool_result":
        part = {
            "type": "tool_result",
            "tool_id": block.get("tool_use_id", ""),
            "content": block.get("content", ""),
        }
        if "is_error" in block:
            part["is_error"] = block["is_error"]
        core_keys = {"type", "tool_use_id", "content", "is_error"}
    elif btype == "token_budget":
        part = {"type": "token_budget"}
        core_keys = {"type"}
    elif btype == "flag":
        part = {"type": "flag", "flag": block.get("flag", "")}
        core_keys = {"type", "flag"}
    else:
        part = {"type": btype}
        core_keys = {"type"}

    native = {k: v for k, v in block.items() if k not in core_keys}
    native["_key_order"] = list(block.keys())

    part["_native"] = native
    return part


def _ucf_block_to_native(part: dict) -> dict:
    ptype = part.get("type", "unknown")
    native = part.get("_native", {})
    key_order = native.get("_key_order")

    core = {}
    if ptype == "text":
        core = {"type": "text", "text": part.get("text", "")}
    elif ptype == "thinking":
        core = {"type": "thinking", "thinking": part.get("thinking", "")}
    elif ptype == "tool_call":
        core = {
            "type": "tool_use",
            "id": part.get("tool_id", ""),
            "name": part.get("tool_name", ""),
            "input": part.get("arguments", {}),
        }
    elif ptype == "tool_result":
        core = {
            "type": "tool_result",
            "tool_use_id": part.get("tool_id", ""),
            "content": part.get("content", ""),
        }
        if "is_error" in part:
            core["is_error"] = part["is_error"]
    elif ptype == "token_budget":
        core = {"type": "token_budget"}
    elif ptype == "flag":
        core = {"type": "flag", "flag": part.get("flag", "")}
    else:
        core = {"type": ptype}

    extra = {k: v for k, v in native.items() if k != "_key_order"}
    merged = {**core, **extra}

    if key_order:
        block = {}
        for k in key_order:
            if k in merged:
                block[k] = merged[k]
        for k in merged:
            if k not in block:
                block[k] = merged[k]
        return block
    return merged


def claudeweb_to_ucf_message(msg: dict, prev_id: str | None = None) -> dict:
    sender = msg.get("sender", "unknown")
    ucf_type = SENDER_MAP_FWD.get(sender, "meta")
    msg_id = msg.get("uuid") or str(uuid.uuid4())
    ts = _parse_ts(msg.get("created_at", 0))
    data: dict = {}
    native: dict = {}

    content_blocks = msg.get("content", [])
    if not isinstance(content_blocks, list):
        content_blocks = []

    if ucf_type == "user":
        text_parts = [b for b in content_blocks if b.get("type") == "text"]
        if text_parts:
            data["content"] = [_block_to_ucf(b) for b in content_blocks]
        else:
            data["content"] = msg.get("text", "")
    elif ucf_type == "assistant":
        data["content"] = [_block_to_ucf(b) for b in content_blocks]
    else:
        data["raw"] = msg

    if msg.get("attachments"):
        native["attachments"] = msg["attachments"]
    if msg.get("files"):
        native["files"] = msg["files"]
    if msg.get("text") is not None:
        native["text"] = msg["text"]
    if msg.get("updated_at"):
        native["updated_at"] = msg["updated_at"]
    if msg.get("created_at"):
        native["_ts_iso"] = msg["created_at"]

    return build_ucf(ucf_type, msg_id, prev_id, ts, data, native or None)


def ucf_to_claudeweb_message(ucf: dict) -> dict:
    data = ucf.get("data", {})
    native = data.get("_native", {})

    if ucf["type"] == "meta" and "raw" in data:
        return data["raw"]

    sender = SENDER_MAP_REV.get(ucf["type"], ucf["type"])
    msg: dict = {
        "uuid": ucf.get("id", ""),
        "sender": sender,
    }

    if native.get("text") is not None:
        msg["text"] = native["text"]
    if native.get("_ts_iso"):
        msg["created_at"] = native["_ts_iso"]
    elif ucf.get("ts", 0) > 0:
        msg["created_at"] = datetime.fromtimestamp(ucf["ts"], tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ")
    if native.get("updated_at"):
        msg["updated_at"] = native["updated_at"]

    content = data.get("content", [])
    if isinstance(content, list) and content:
        msg["content"] = [_ucf_block_to_native(p) for p in content]
    elif isinstance(content, str):
        msg["content"] = []

    if native.get("attachments"):
        msg["attachments"] = native["attachments"]
    else:
        msg["attachments"] = []
    if native.get("files"):
        msg["files"] = native["files"]
    else:
        msg["files"] = []

    return msg


def claudeweb_to_ucf(messages: list[dict]) -> list[dict]:
    result, pid = [], None
    for m in messages:
        u = claudeweb_to_ucf_message(m, pid)
        result.append(u)
        pid = u["id"]
    return result


def ucf_to_claudeweb(messages: list[dict]) -> list[dict]:
    return [ucf_to_claudeweb_message(m) for m in messages]


def is_claudeweb_conv(msg: dict) -> bool:
    return msg.get("sender") in SENDER_MAP_FWD


def load_claudeweb_file(path: str) -> list[dict]:
    """Load a conversations.json and return flat list of (conv_meta, messages) tuples."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    result = []
    for conv in data:
        if not isinstance(conv, dict):
            continue
        meta = {k: v for k, v in conv.items() if k != "chat_messages"}
        messages = conv.get("chat_messages", [])
        result.append((meta, messages))
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Claude Web ↔ UCF converter")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--direction", choices=["to-ucf", "from-ucf"], default="to-ucf")
    p.add_argument("--test", action="store_true")
    args = p.parse_args()

    if args.test:
        convs = load_claudeweb_file(args.input)
        total_pass, total_fail = 0, 0
        for meta, msgs in convs:
            r = roundtrip_check(msgs, claudeweb_to_ucf_message, ucf_to_claudeweb_message, is_claudeweb_conv)
            total_pass += r["pass"]
            total_fail += r["fail"]
            if r["failures"]:
                print(f"  Conv {meta.get('name', '?')}: {r['fail']} failures")
                for a, b in r["failures"]:
                    print(f"    Orig: {json.dumps(a)[:120]}")
                    print(f"    Back: {json.dumps(b)[:120]}")
        total = total_pass + total_fail
        print(f"Claude Web: {total_pass}/{total} pass ({total_pass*100//total if total else 0}%)")
    else:
        from ucf_adapter_base import save_jsonl
        convs = load_claudeweb_file(args.input)
        all_ucf = []
        for meta, msgs in convs:
            all_ucf.extend(claudeweb_to_ucf(msgs))
        save_jsonl(args.output, all_ucf)
        print(f"Converted {len(all_ucf)} messages from {len(convs)} conversations")
