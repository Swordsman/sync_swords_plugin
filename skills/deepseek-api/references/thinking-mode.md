# Thinking Mode

The model emits chain-of-thought (`reasoning_content`) before the final answer. Supported by both models (`deepseek-flash`, `deepseek-v4-pro`); **enabled by default**, default effort `high`.

## The three states

| State | How | Behavior |
|---|---|---|
| **Unspecified** (default) | omit `thinking` AND `reasoning_effort` | Thinking on at effort `high` (docs). **[field note, unverified since V4.1]** Was observed to auto-select effort per request (`high` routine, `max` hard tasks) — explicitly enabling at a fixed effort forfeits that |
| **Enabled** | `{"thinking": {"type": "enabled"}}` | Locks thinking on at your `reasoning_effort`. **[field note]** Can take up to ~30 s on complex tasks; most reliable, especially v4-pro |
| **Disabled** | `{"thinking": {"type": "disabled"}}` or `"reasoning_effort": "none"` | No CoT, no `reasoning_content`. **[field note]** Completes in seconds; fine for verification/scouting, weaker at problem-solving and creative work |

## Effort control

| | OpenAI format | Anthropic format | Responses API |
|---|---|---|---|
| Toggle | `"thinking": {"type": "enabled"/"disabled"}` | same `thinking` field (`anthropic-endpoint.md`; `budget_tokens` ignored) | `"reasoning": {"effort": "none"}` disables |
| Effort | `"reasoning_effort": "low"` \| `"high"` \| `"max"` (`"none"` disables) | `"output_config": {"effort": "low"/"high"/"max"}` | `"reasoning": {"effort": "low"/"high"/"max"}` |

- Default effort `high`. DeepSeek's guidance: `low` for simple tasks, `high` for daily agent work, `max` for complex scenarios. `GET /models` lists each model's `effort.supported_levels` and `default_level`.
- Compat mapping: `minimal` → `low`; `medium` → `high`; `xhigh` → **`high`** (older docs mapped it to `max` — clients that send `xhigh` expecting max must send `max`); `ultra` → `max`.
- **[field note, unverified since V4.1]** Complex agent requests (Claude Code, OpenCode) auto-get `max`.
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

- `temperature`, `presence_penalty`, `frequency_penalty` have no effect in thinking mode (accepted, no error).
- `top_p` **only** takes effect in thinking mode, effective range 0.95–1.0 (lower values treated as 0.95); in non-thinking mode it is fixed at 1.0.
- **Leave `max_tokens` unset.** The default is stable; setting it is brittle. Thinking tokens count against it — a low cap starves reasoning, degrades output (incoherent or empty) and can glitch the call and leave it hanging. Where a client makes it mandatory (Anthropic SDK / endpoint), set the max, `393216` — never lower. **[field note]** Unset default per API reference: 64K thinking, 128K at `max` effort (8K non-thinking, verified).
- CoT is returned as `reasoning_content`, a sibling of `content` (and `delta.reasoning_content` when streaming — accumulate separately, see `streaming.md`).

## Context rules for multi-turn (critical)

Keyed on whether the **request carries the `tools` parameter**:

- **No `tools` in the request**: prior-turn `reasoning_content` does NOT need resending; if sent, it's ignored. Harmless either way.
- **`tools` in the request**: ALL prior `reasoning_content` must be resent and is concatenated into context — per docs even for turns where no tool was called. Omitting it → **HTTP 400** (`The reasoning_content in the thinking mode must be passed back to the API`), no graceful recovery. **[field note]** Live 2026-10-13: the 400 fired for a tool-call turn missing it; a plain turn missing it was accepted — resend everything anyway.

Safest pattern — append the SDK message object verbatim; it carries everything:

```python
messages.append(response.choices[0].message)   # content + reasoning_content + tool_calls
```

## Reasoning + tools loop

Same pattern as tool-calling.md basic loop, but `messages.append(msg)` preserves `reasoning_content` automatically. Loop until `msg.tool_calls is None`. All prior `reasoning_content` stays in history across turns.
