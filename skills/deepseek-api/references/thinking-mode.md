# Thinking Mode

The model emits chain-of-thought (`reasoning_content`) before the final answer. Supported by both v4 models; **enabled by default**.

## The three states

| State | How | Behavior |
|---|---|---|
| **Unspecified** (default) | omit `thinking` AND `reasoning_effort` | Thinking on, API auto-selects effort per request: `high` for routine, `max` for hard tasks. **[field note]** Usually the best option — explicitly enabling at a fixed effort forfeits auto-escalation |
| **Enabled** | `{"thinking": {"type": "enabled"}}` | Locks thinking on at your `reasoning_effort`. **[field note]** Can take up to ~30 s on complex tasks; most reliable, especially v4-pro |
| **Disabled** | `{"thinking": {"type": "disabled"}}` | No CoT, no `reasoning_content`. **[field note]** Completes in seconds; fine for verification/scouting, weaker at problem-solving and creative work |

## Effort control

| | OpenAI format | Anthropic format |
|---|---|---|
| Toggle | `"thinking": {"type": "enabled"/"disabled"}` | native `thinking` field (`anthropic-endpoint.md`; `budget_tokens` ignored) |
| Effort | `"reasoning_effort": "high"` \| `"max"` | `"output_config": {"effort": "high"/"max"}` |

- Default effort `high`; complex agent requests (Claude Code, OpenCode) auto-get `max`.
- Compat mapping: `low`/`medium` → `high`; `xhigh` → `max`.
- **[field note]** Effort sets the proportion of the output budget spent on thinking tokens relative to answer tokens.
- OpenAI Python SDK: `reasoning_effort` is a normal kwarg, but `thinking` must go in `extra_body` (top-level fails client validation):

```python
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=messages,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)
```

## Parameter interactions

- `temperature`, `top_p`, `presence_penalty`, `frequency_penalty` are silently ignored in thinking mode (per docs; **[field note]** unverified against v4 — test before relying on it either way).
- **Do not restrict `max_tokens`.** Thinking tokens count against it; a low cap starves reasoning and the output degrades badly (incoherent or empty). Omit it or set it very high — **[field note]** treat ~50K as the floor when thinking is on. Max is 384K.
- CoT is returned as `reasoning_content`, a sibling of `content` (and `delta.reasoning_content` when streaming — accumulate separately, see `streaming.md`).

## Context rules for multi-turn (critical)

Between two user messages:

- **No tool calls occurred**: prior-turn `reasoning_content` does NOT need resending; if sent, it's ignored. Harmless either way.
- **Tool call(s) occurred**: prior `reasoning_content` MUST be resent in ALL subsequent requests. Omitting it → **HTTP 400**, no graceful recovery.

Safest pattern — append the SDK message object verbatim; it carries everything:

```python
messages.append(response.choices[0].message)   # content + reasoning_content + tool_calls
```

## Reasoning + tools loop

Same pattern as tool-calling.md basic loop, but `messages.append(msg)` preserves `reasoning_content` automatically. Loop until `msg.tool_calls is None`. All prior `reasoning_content` stays in history across turns.
