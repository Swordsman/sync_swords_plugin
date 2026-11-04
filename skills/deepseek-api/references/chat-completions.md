# POST /chat/completions — Full Reference

OpenAI-compatible. All parameters as JSON body. Streaming response schema: `streaming.md`.

## Request body

### messages (required, object[], ≥1)

OneOf four message types:

- **System**: `content` (string, req), `role: "system"`, `name` (opt — differentiate same-role participants). May also appear mid-conversation.
- **User**: `content` (string, or content-part array: `text` / `image_url` / `file` — images `deepseek-flash` only, see `vision.md`), `role: "user"`, `name` (opt).
- **Assistant**: `content` (string, nullable, req), `role: "assistant"`, `name` (opt), plus:
  - `prefix` (bool, Beta): force the model to start its answer with this message's content. Requires `/beta` base URL — see `structured-output.md`.
  - `reasoning_content` (string, nullable): CoT. Required to resend in requests carrying `tools` (`thinking-mode.md`); also usable as Beta CoT input with `prefix: true`.
  - `tool_calls` (array): tool invocations this message made — resend as received.
- **Tool**: `role: "tool"`, `content` (string or content-part array, req; may carry images), `tool_call_id` (string, req — the call this message answers).

### model (required, string)

`deepseek-flash` (DeepSeek-V4.1-Flash) or `deepseek-v4-pro`. `deepseek-v4-flash` is a retired legacy name: still accepted, served by V4.1 Flash and billed at the Flash price; the response reports `"model": "deepseek-flash"` (verified 2026-10-13). Unknown names → 400 `The supported API model names are deepseek-flash, deepseek-v4-pro, ...`.

### Optional parameters

| Param | Type / range | Default | Notes |
|---|---|---|---|
| `thinking` | `{"type": "enabled"\|"disabled"}` | enabled | Unset (with unset effort) = auto-adaptive effort **[field note, unverified since V4.1]**. Details: `thinking-mode.md` |
| `reasoning_effort` | `"none"` \| `"low"` \| `"high"` \| `"max"` | `high` | `none` disables thinking. Compat: `minimal` → `low`; `medium`/`xhigh` → `high`; `ultra` → `max` (`thinking-mode.md`). **[field note, unverified since V4.1]** complex agent requests (Claude Code, OpenCode) auto-get `max` |
| `max_tokens` | int 1–393216 (384K) | unset | **Leave unset** — the default is stable; setting it is brittle **[field note]**. Server default when unset: 8K non-thinking (verified 2026-10-13), 64K thinking, 128K at `max` effort (per docs). If a client requires it: `393216`, never lower — thinking tokens count against it and a low cap can hang the call. Input + output must fit 1M context |
| `temperature` | 0–2 | 1 | Alter this OR `top_p`, not both. Ignored in thinking mode |
| `top_p` | (0, 1] | 1 | Nucleus sampling. **Only takes effect in thinking mode** (values < 0.95 treated as 0.95); fixed at 1.0 in non-thinking mode |
| `stop` | string \| string[] | — | Up to 16 stop sequences |
| `stream` | bool | false | SSE. See `streaming.md` |
| `stream_options` | `{"include_usage": bool}` | — | Only with `stream: true` (otherwise HTTP 400); usage rides on the last chunk |
| `response_format` | `{"type": "text"\|"json_object"}` | text | JSON mode requirements and traps: `structured-output.md` |
| `tools` | object[] | — | Schema below; full guidance: `tool-calling.md` |
| `tool_choice` | `"none"` \| `"auto"` \| `"required"` \| `{"type":"function","function":{"name":"..."}}` | `auto` with tools, else `none` | `required` and named choices → **HTTP 400 in thinking mode**; `none`/`auto` fine — see `tool-calling.md` |
| `logprobs` | bool | — | Log probabilities per output token |
| `top_logprobs` | int 0–20 | — | Requires `logprobs: true` |
| `user_id` | string `[a-zA-Z0-9_-]+` ≤512 | — | Isolation/safety/cache/scheduling; no PII. Via SDK: `extra_body`. Details: `ops-troubleshooting.md` |
| `frequency_penalty`, `presence_penalty` | — | — | **Deprecated, accepted, inert** |

### Tool definition schema

```json
{"type": "function",
 "function": {"name": "...",          // req, [a-zA-Z0-9_-], ≤128 chars
              "description": "...",   // when/how to call
              "parameters": {...},    // JSON Schema; omit = no params
              "strict": false}}       // Beta strict mode — see tool-calling.md
```

## Response (non-streaming 200): `chat.completion`

```json
{
  "id": "930c60df-...",
  "object": "chat.completion",
  "created": 1705651092,
  "model": "deepseek-v4-pro",
  "system_fingerprint": "fp_a49d71b8a1",
  "choices": [{
    "index": 0,
    "finish_reason": "stop",
    "message": {
      "role": "assistant",
      "content": "Hello! How can I help you today?",
      "reasoning_content": "...",          // present in thinking mode
      "tool_calls": [{"id": "...", "type": "function",
                      "function": {"name": "...", "arguments": "..."}}]
    },
    "logprobs": {"content": [{"token": "...", "logprob": 0, "bytes": [72],
                              "top_logprobs": [...]}],
                 "reasoning_content": [...]}
  }],
  "usage": {
    "prompt_tokens": 16, "completion_tokens": 10, "total_tokens": 26,
    "prompt_tokens_details": {"cached_tokens": 0},
    "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 16,
    "completion_tokens_details": {"reasoning_tokens": 0}
  }
}
```

Notes:

- `finish_reason`: `stop` | `length` | `content_filter` | `tool_calls` | `insufficient_system_resource` | `aborted` (generation interrupted).
- `message.content` may carry text alongside `tool_calls` (observed 2026-10-13 on both models) — don't assume null.
- `usage.prompt_tokens` = `prompt_cache_hit_tokens` + `prompt_cache_miss_tokens` (cache mechanics: `pricing-caching.md`). `prompt_tokens_details.cached_tokens` (OpenAI-style) equals `prompt_cache_hit_tokens`.
- `completion_tokens` includes reasoning; subtract `reasoning_tokens` for visible-answer count.
- logprobs: `logprob` is `-9999.0` (sentinel) when token not in top-20; `bytes` is UTF-8 byte ints or null.
- `system_fingerprint` identifies backend config — useful for diffing behavior across runs.

## curl example

```bash
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
  -d '{
        "model": "deepseek-v4-pro",
        "messages": [
          {"role": "system", "content": "You are a helpful assistant."},
          {"role": "user", "content": "Hello!"}
        ],
        "stream": false
      }'
```

## Multi-round conversations

Stateless: resend full history as messages[]. Append `response.choices[0].message` verbatim. reasoning_content resend rules: -> thinking-mode.md. Client-inserted tool calls mid-conversation are not supported here (use the Anthropic endpoint or Responses API); mid-conversation system messages are.
