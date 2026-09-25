"""Cross-format message sanitization for UCF.

When converting UCF messages from one format to another, structural
incompatibilities arise that don't exist in same-format roundtrips.
This module provides provider-targeted repairs derived from Hermes
agent_runtime_helpers.py — every fix here corresponds to a real
production 400/empty-response that was diagnosed and solved.

Usage:
    from ucf_cross_format import prepare_for_ds, prepare_for_anthropic

    ucf_msgs = some_adapter.to_ucf(source_msgs)
    ds_msgs = [ucf_to_ds_message(u) for u in prepare_for_ds(ucf_msgs)]
"""

import json
import re
from copy import deepcopy


# ── Role alternation repair ───────────────────────────────────────
# Ported from: repair_message_sequence
# Cause: providers expect strict user/assistant alternation after
# system. Cross-format conversion can produce orphaned tool results
# (whose assistant was filtered as meta) or consecutive user messages
# (when non-conversational types between them were dropped).

def repair_role_alternation(messages: list[dict]) -> list[dict]:
    """Fix orphaned tool results and consecutive same-role messages.

    Operates on native-format messages (post ucf_to_X conversion).
    Returns a new list; input is not mutated.
    """
    if not messages:
        return messages

    msgs = [m for m in messages]

    # Pass 1: drop tool results with no matching assistant tool_call
    known_tc_ids: set = set()
    filtered = []
    for msg in msgs:
        role = msg.get("role", "")
        if role == "assistant":
            known_tc_ids = set()
            for tc in msg.get("tool_calls") or []:
                tid = tc.get("id") if isinstance(tc, dict) else None
                if tid:
                    known_tc_ids.add(tid)
            filtered.append(msg)
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if tid and tid in known_tc_ids:
                filtered.append(msg)
            # else: orphan — drop silently
        else:
            if role == "user":
                known_tc_ids = set()
            filtered.append(msg)

    # Pass 2: inject stub results for assistant tool_calls with no result
    surviving_result_ids = set()
    for msg in filtered:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id")
            if tid:
                surviving_result_ids.add(tid)

    patched = []
    for msg in filtered:
        patched.append(msg)
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tid = tc.get("id") if isinstance(tc, dict) else None
                if tid and tid not in surviving_result_ids:
                    fn = tc.get("function", {})
                    patched.append({
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": "[Result unavailable]",
                    })

    # Pass 3: merge consecutive user messages
    merged = []
    for msg in patched:
        if (
            merged
            and isinstance(msg, dict) and msg.get("role") == "user"
            and isinstance(merged[-1], dict) and merged[-1].get("role") == "user"
        ):
            prev_c = merged[-1].get("content", "")
            new_c = msg.get("content", "")
            if isinstance(prev_c, str) and isinstance(new_c, str):
                sep = "\n\n" if prev_c and new_c else ""
                merged[-1] = dict(merged[-1])
                merged[-1]["content"] = prev_c + sep + new_c
                continue
        merged.append(msg)

    return merged


# ── Tool call argument sanitization ───────────────────────────────
# Ported from: sanitize_tool_call_arguments
# Cause: corrupted JSON in tool_call arguments causes 400 on all providers.

def repair_tool_call_arguments(messages: list[dict]) -> list[dict]:
    """Fix invalid JSON in tool_call function arguments.

    Operates on native-format messages. Returns a new list.
    """
    result = []
    for msg in messages:
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            result.append(msg)
            continue

        msg = dict(msg)
        new_tcs = []
        for tc in msg["tool_calls"]:
            tc = dict(tc)
            fn = dict(tc.get("function", {}))
            args = fn.get("arguments")
            if args is None or args == "":
                fn["arguments"] = "{}"
            elif isinstance(args, str):
                if not args.strip():
                    fn["arguments"] = "{}"
                else:
                    try:
                        json.loads(args)
                    except json.JSONDecodeError:
                        fn["arguments"] = "{}"
            tc["function"] = fn
            new_tcs.append(tc)
        msg["tool_calls"] = new_tcs
        result.append(msg)

    return result


# ── Reasoning content padding for thinking providers ──────────────
# Ported from: copy_reasoning_content_for_api, reapply_reasoning_echo_for_provider
# Cause: DeepSeek V4, Kimi, MiMo thinking mode require reasoning_content
# on EVERY assistant message. Empty string "" is rejected by DS V4 Pro;
# must be at least " " (single space). Omitting during a tool-call
# sprint causes 400.

def pad_reasoning_content(messages: list[dict]) -> list[dict]:
    """Ensure all assistant messages have reasoning_content for thinking providers.

    Injects single-space padding where reasoning_content is absent or empty.
    Operates on DS-format messages (role/content/reasoning_content/tool_calls).
    Returns a new list.
    """
    result = []
    for msg in messages:
        if msg.get("role") != "assistant":
            result.append(msg)
            continue

        msg = dict(msg)
        rc = msg.get("reasoning_content")
        if rc is None:
            msg["reasoning_content"] = " "
        elif isinstance(rc, str) and rc == "":
            msg["reasoning_content"] = " "
        result.append(msg)

    return result


# ── Content type normalization ────────────────────────────────────
# Cause: DS/OpenAI API expects string content for user/system/tool roles.
# Claude Web and other formats may produce list-of-parts content.
# Assistant content must be string (thinking goes in reasoning_content).

def normalize_content_types(messages: list[dict]) -> list[dict]:
    """Coerce content to string where the DS/OpenAI API requires it.

    - user/system/tool: content must be string (extract text from parts)
    - assistant: content must be string or null (never list)
    - None → ""

    Returns a new list.
    """
    result = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role in ("user", "system", "tool"):
            if isinstance(content, list):
                msg = dict(msg)
                texts = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        texts.append(p.get("text", ""))
                    elif isinstance(p, str):
                        texts.append(p)
                msg["content"] = "\n".join(texts)
            elif content is None:
                msg = dict(msg)
                msg["content"] = ""
        elif role == "assistant":
            if content is None:
                msg = dict(msg)
                msg["content"] = ""

        result.append(msg)

    return result


# ── Thinking-only turn removal ────────────────────────────────────
# Ported from: drop_thinking_only_and_merge_users
# Cause: assistant turns with only thinking content (no text, no tool_calls)
# violate role alternation when thinking is stripped for non-thinking
# providers. Drop them and merge any adjacent user messages left behind.

def drop_thinking_only_turns(messages: list[dict]) -> list[dict]:
    """Remove assistant messages that have only thinking content.

    After removal, merges any consecutive user messages.
    Operates on native-format messages. Returns a new list.
    """
    def _is_thinking_only(msg):
        if msg.get("role") != "assistant":
            return False
        if msg.get("tool_calls"):
            return False
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            return False
        rc = msg.get("reasoning_content")
        if isinstance(rc, str) and rc.strip() and rc.strip() != " ":
            return True
        return False

    kept = [m for m in messages if not _is_thinking_only(m)]

    # Merge consecutive user messages
    merged = []
    for m in kept:
        if (
            merged
            and m.get("role") == "user"
            and merged[-1].get("role") == "user"
        ):
            prev_c = merged[-1].get("content", "")
            cur_c = m.get("content", "")
            if isinstance(prev_c, str) and isinstance(cur_c, str):
                sep = "\n\n" if prev_c and cur_c else ""
                merged[-1] = dict(merged[-1])
                merged[-1]["content"] = prev_c + sep + cur_c
                continue
        merged.append(m)

    return merged


# ── Inline thinking tag stripping ─────────────────────────────────
# Ported from: strip_think_blocks
# Cause: some models embed reasoning in content via XML tags rather than
# structured fields. When the structured reasoning was already extracted,
# the inline tags are redundant and pollute the content.

_THINK_TAGS = ("think", "thinking", "reasoning", "thought", "REASONING_SCRATCHPAD")
_TOOL_CALL_TAGS = ("tool_call", "tool_calls", "tool_result",
                   "function_call", "function_calls")


def strip_inline_thinking(content: str) -> str:
    """Remove inline reasoning/thinking XML tags from content."""
    if not content:
        return ""
    # Closed tag pairs
    for tag in _THINK_TAGS:
        content = re.sub(
            rf'<{tag}>.*?</{tag}>',
            '', content, flags=re.DOTALL | re.IGNORECASE)
    # Inline tool-call XML blocks (Gemma, open models)
    for tag in _TOOL_CALL_TAGS:
        content = re.sub(
            rf'<{tag}\b[^>]*>.*?</{tag}>',
            '', content, flags=re.DOTALL | re.IGNORECASE)
    # <function name="...">...</function> at block boundaries
    content = re.sub(
        r'(?:(?<=^)|(?<=[\n\r.!?:]))[ \t]*'
        r'<function\b[^>]*\bname\s*=[^>]*>'
        r'(?:(?:(?!</function>).)*)</function>',
        '', content, flags=re.DOTALL | re.IGNORECASE)
    # Unterminated reasoning at block boundary
    content = re.sub(
        r'(?:^|\n)[ \t]*<(?:' + '|'.join(_THINK_TAGS) + r')\b[^>]*>.*$',
        '', content, flags=re.DOTALL | re.IGNORECASE)
    # Stray orphan tags
    content = re.sub(
        r'</?(?:' + '|'.join(_THINK_TAGS) + r')>\s*',
        '', content, flags=re.IGNORECASE)
    content = re.sub(
        r'</(?:' + '|'.join(_TOOL_CALL_TAGS) + r'|function)>\s*',
        '', content, flags=re.IGNORECASE)
    return content


def strip_thinking_from_content(messages: list[dict]) -> list[dict]:
    """Strip inline thinking tags from assistant content.

    Use when reasoning was already extracted into reasoning_content
    and the inline tags are redundant. Returns a new list.
    """
    result = []
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                stripped = strip_inline_thinking(content).strip()
                if stripped != content:
                    msg = dict(msg)
                    msg["content"] = stripped
        result.append(msg)
    return result


# ── Extract inline reasoning to structured field ──────────────────
# Ported from: extract_reasoning
# Cause: some providers embed reasoning in content via XML tags or
# deliver it via non-standard fields (reasoning, reasoning_details).
# Normalizing to reasoning_content makes cross-format chains work.

_INLINE_PATTERNS = (
    r"<think>(.*?)</think>",
    r"<thinking>(.*?)</thinking>",
    r"<thought>(.*?)</thought>",
    r"<reasoning>(.*?)</reasoning>",
    r"<REASONING_SCRATCHPAD>(.*?)</REASONING_SCRATCHPAD>",
)


def extract_reasoning_to_field(messages: list[dict]) -> list[dict]:
    """Promote inline/alternative reasoning to reasoning_content field.

    Checks: reasoning_content (already set), reasoning field,
    reasoning_details array, inline XML tags in content.
    Returns a new list.
    """
    result = []
    for msg in messages:
        if msg.get("role") != "assistant":
            result.append(msg)
            continue

        if msg.get("reasoning_content"):
            result.append(msg)
            continue

        parts = []

        # reasoning field (Hermes internal, MiniMax, etc.)
        r = msg.get("reasoning")
        if isinstance(r, str) and r.strip():
            parts.append(r)

        # reasoning_details array (OpenRouter unified)
        rd = msg.get("reasoning_details")
        if isinstance(rd, list):
            for detail in rd:
                if isinstance(detail, dict):
                    text = (detail.get("summary") or detail.get("thinking")
                            or detail.get("content") or detail.get("text"))
                    if text and text not in parts:
                        parts.append(text)

        # Inline XML tags in content
        if not parts:
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                for pattern in _INLINE_PATTERNS:
                    for block in re.findall(pattern, content, re.DOTALL | re.IGNORECASE):
                        cleaned = block.strip()
                        if cleaned and cleaned not in parts:
                            parts.append(cleaned)

        if parts:
            msg = dict(msg)
            msg["reasoning_content"] = "\n\n".join(parts)

        result.append(msg)

    return result


# ── Surrogate sanitization ────────────────────────────────────────
# Ported from: _sanitize_surrogates in chat_completion_helpers
# Cause: some models return invalid surrogate code points that crash
# json.dumps() on persist.

def sanitize_surrogates(text: str) -> str:
    """Replace invalid surrogate code points with replacement char."""
    if not text:
        return text
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def sanitize_message_surrogates(messages: list[dict]) -> list[dict]:
    """Sanitize surrogate code points in content and reasoning fields."""
    result = []
    for msg in messages:
        changed = False
        for field in ("content", "reasoning_content", "reasoning"):
            val = msg.get(field)
            if isinstance(val, str) and val:
                clean = sanitize_surrogates(val)
                if clean != val:
                    if not changed:
                        msg = dict(msg)
                        changed = True
                    msg[field] = clean
        result.append(msg)
    return result


# ── Composite pipelines ──────────────────────────────────────────
# Each pipeline chains the repairs needed for a specific target provider.

def prepare_for_ds(messages: list[dict], *, thinking: bool = True) -> list[dict]:
    """Full sanitization pipeline for DeepSeek API target.

    Args:
        messages: native-format messages (output of ucf_to_ds or similar)
        thinking: if True, pad reasoning_content for thinking mode

    Returns sanitized messages ready for the DS API.
    """
    messages = sanitize_message_surrogates(messages)
    messages = repair_tool_call_arguments(messages)
    messages = normalize_content_types(messages)
    messages = extract_reasoning_to_field(messages)
    messages = strip_thinking_from_content(messages)
    messages = repair_role_alternation(messages)
    if thinking:
        messages = pad_reasoning_content(messages)
    return messages


def prepare_for_openai(messages: list[dict]) -> list[dict]:
    """Full sanitization pipeline for OpenAI API target.

    OpenAI doesn't support reasoning_content — strip it.
    """
    messages = sanitize_message_surrogates(messages)
    messages = repair_tool_call_arguments(messages)
    messages = normalize_content_types(messages)
    messages = strip_thinking_from_content(messages)
    messages = drop_thinking_only_turns(messages)
    messages = repair_role_alternation(messages)
    # Remove reasoning fields OpenAI doesn't understand
    result = []
    for msg in messages:
        if msg.get("role") == "assistant":
            msg = {k: v for k, v in msg.items()
                   if k not in ("reasoning_content", "reasoning", "reasoning_details")}
        result.append(msg)
    return result


def prepare_for_anthropic(messages: list[dict]) -> list[dict]:
    """Full sanitization pipeline for Anthropic API target.

    Anthropic uses content block arrays, not flat strings.
    This normalizes to Anthropic's expected shape.
    """
    messages = sanitize_message_surrogates(messages)
    messages = repair_tool_call_arguments(messages)
    messages = strip_thinking_from_content(messages)
    messages = repair_role_alternation(messages)
    return messages


def prepare_generic(messages: list[dict]) -> list[dict]:
    """Minimal sanitization — repairs structural issues without
    provider-specific transforms."""
    messages = sanitize_message_surrogates(messages)
    messages = repair_tool_call_arguments(messages)
    messages = normalize_content_types(messages)
    messages = repair_role_alternation(messages)
    return messages
