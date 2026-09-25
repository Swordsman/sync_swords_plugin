"""Bidirectional deterministic converter: Claude Code ↔ UCF.

Claude wraps messages in session-envelopes with many event types.
Conversation messages (user/assistant/system) get proper UCF mapping.
Everything else is preserved via _native._passthrough.
"""

import json
from ucf_adapter_base import (
    content_parts_from_list, content_parts_to_native, build_ucf,
    roundtrip_check, convert_file,
)


ROLE_MAP_FWD = {"user": "user", "assistant": "assistant", "system": "system", "tool_result": "tool_result"}
ROLE_MAP_REV = {v: k for k, v in ROLE_MAP_FWD.items()}
SKIP_TYPES = {"queue-operation"}

ENVELOPE_FIELDS = (
    "sessionId", "permissionMode", "userType", "entrypoint",
    "cwd", "version", "gitBranch", "isSidechain", "promptId",
    "messageId", "snapshot", "attachment", "commitMessage",
    "autoMode", "worktree", "requestId",
)

MESSAGE_EXTRA = ("model", "id", "stop_reason", "stop_sequence", "usage", "type")


def claude_to_ucf_message(msg: dict, prev_id: str | None = None) -> dict | None:
    ctype = msg.get("type", "")
    if ctype in SKIP_TYPES:
        return None

    inner = msg.get("message", {})
    role = inner.get("role", ctype)
    ucf_type = ROLE_MAP_FWD.get(role, "meta")
    data: dict = {}
    native: dict = {}

    if ucf_type == "user":
        content = inner.get("content")
        data["content"] = content if content is not None else None
    elif ucf_type == "assistant":
        content = inner.get("content")
        parts = content_parts_from_list(content) if isinstance(content, list) else []
        data["content"] = parts
    elif ucf_type == "tool_result":
        data["tool_id"] = inner.get("tool_use_id", "") or msg.get("tool_id", "")
        data["content"] = inner.get("content", "") if inner else msg.get("content", "")
        is_err = inner.get("is_error") if inner else msg.get("is_error")
        if is_err is not None:
            data["is_error"] = is_err
    elif ucf_type == "system":
        content = inner.get("content")
        data["content"] = content if content is not None else None
    elif ucf_type != "meta":
        data["content"] = inner.get("content", "")

    if ucf_type == "meta":
        native["_passthrough"] = msg
    else:
        if ctype != role:
            native["_orig_type"] = ctype
        for k in ENVELOPE_FIELDS:
            if k in msg: native[k] = msg[k]
        for k in MESSAGE_EXTRA:
            if k in inner: native[k] = inner[k]

    return build_ucf(ucf_type, msg.get("uuid", ""), msg.get("parentUuid") or prev_id,
                     msg.get("timestamp", 0), data, native)


def ucf_to_claude_message(ucf: dict) -> dict:
    data = ucf.get("data", {})
    native = data.get("_native", {})

    if native.get("_passthrough"):
        return native["_passthrough"]

    role = ROLE_MAP_REV.get(ucf["type"], ucf["type"])
    inner: dict = {"role": role}

    if role == "user":
        inner["content"] = data.get("content")
    elif role == "assistant":
        parts = data.get("content", [])
        if parts:
            inner["content"] = content_parts_to_native(parts, think_key="thinking")
        else:
            inner["content"] = data.get("content")
    elif role == "tool_result":
        inner["tool_use_id"] = data.get("tool_id", "")
        inner["content"] = data.get("content", "")
        if "is_error" in data:
            inner["is_error"] = data["is_error"]
    elif role == "system":
        inner["content"] = data.get("content")

    for k in MESSAGE_EXTRA:
        if k in native: inner[k] = native[k]

    msg: dict = {
        "uuid": ucf.get("id", ""), "parentUuid": ucf.get("parent_id"),
        "type": native.get("_orig_type", role), "message": inner,
        "timestamp": ucf.get("ts"),
    }

    for k in ENVELOPE_FIELDS:
        if k in native: msg[k] = native[k]

    return msg


def claude_to_ucf(messages: list[dict]) -> list[dict]:
    result, pid = [], None
    for m in messages:
        u = claude_to_ucf_message(m, pid)
        if u: result.append(u); pid = u["id"]
    return result


def ucf_to_claude(messages: list[dict]) -> list[dict]:
    return [ucf_to_claude_message(m) for m in messages]


def is_claude_conv(msg: dict) -> bool:
    if msg.get("type") in SKIP_TYPES:
        return False
    role = msg.get("message", {}).get("role") or msg.get("type", "")
    return role in ROLE_MAP_FWD


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Claude Code ↔ UCF converter")
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
        r = roundtrip_check(msgs, claude_to_ucf_message, ucf_to_claude_message, is_claude_conv)
        t = r["pass"] + r["fail"]
        print(f"Claude: {r['pass']}/{t} pass ({r['pass']*100//t}%)")
        for a, b in r["failures"]:
            print(f"  Orig: {json.dumps(a)[:120]}")
            print(f"  Back: {json.dumps(b)[:120]}")
    else:
        n = convert_file(args.input, args.output, claude_to_ucf_message, ucf_to_claude_message, args.direction)
        print(f"Converted {n} messages")
