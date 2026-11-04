# Anthropic-Compatible Endpoint

Anthropic SDK/Messages API at `https://api.deepseek.com/anthropic`. Wiring specific tools: -> `integrations.md`.

## Quick start

```bash
pip install anthropic
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_API_KEY=${YOUR_DEEPSEEK_API_KEY}
```

```python
import anthropic
client = anthropic.Anthropic()
message = client.messages.create(
    model="deepseek-v4-pro",
    max_tokens=393216,          # mandatory here: use the max, never lower (thinking counts against it)
    system="You are a helpful assistant.",
    messages=[{"role": "user",
               "content": [{"type": "text", "text": "Hi, how are you?"}]}])
print(message.content)
```

`max_tokens` is required by the Anthropic format, so it can't be left unset: always `393216`. A lower cap starves thinking and can glitch the call and leave it hanging. **[field note]**

## Model mapping

| Requested | Serves |
|---|---|
| `deepseek-flash`, `deepseek-v4-pro` | as named (legacy `deepseek-v4-flash`, `deepseek-chat` also accepted) |
| `claude-opus*` | `deepseek-v4-pro` (billed at Pro price) |
| `claude-sonnet*` / `claude-haiku*` | `deepseek-flash` |
| any other `claude-*` name (e.g. `claude-3-5-sonnet-*`, `claude-instant-1`) | `deepseek-flash` |
| non-Claude unknown name (e.g. `gpt-4o`) | **HTTP 400** `The supported API model names are deepseek-flash, deepseek-v4-pro, ...` |

**[field note]** Verified 2026-10-13. The response `model` echoes the name you sent, so the serving model can't be read off the response; it was fingerprinted by image input: `claude-opus*` requests dropped the image like `deepseek-v4-pro` (input_tokens up only ~5, against ~180+ on flash; rechecked 2026-10-15), all other `claude-*` names tokenized it like `deepseek-flash`. The docs' "any unsupported name → deepseek-flash" holds only for `claude-*` names.

## Compatibility tables

### HTTP headers

| Header | Status |
|---|---|
| `x-api-key` | Fully supported |
| `anthropic-version` | Ignored |
| `anthropic-beta` | Ignored for `/messages`; `files-api-2025-04-14` required for Files API endpoints |

### Request fields

| Field | Status |
|---|---|
| `model`, `stop_sequences`, `stream`, `system` | Fully supported |
| `max_tokens` | Fully supported — mandatory in this format: set `393216` (see above) |
| `temperature` | Supported, range 0.0–2.0 (note: wider than Anthropic's 0–1); no effect in thinking mode |
| `top_p` | Only takes effect in thinking mode (lower bound 0.95); fixed at 1.0 in non-thinking mode |
| `thinking` | Supported (`budget_tokens` **ignored** — effort is the only lever) |
| `output_config` | Only `effort` supported (`"low"`/`"high"`/`"max"` — see `thinking-mode.md`) |
| `metadata` | Only `user_id` supported (`ops-troubleshooting.md`) |
| `top_k`, `container`, `mcp_servers`, `service_tier` | Ignored |

### Tools

| Field | Status |
|---|---|
| `name`, `input_schema`, `description` | Fully supported |
| `cache_control` | Ignored (DeepSeek's own prefix cache still applies automatically — `pricing-caching.md`) |
| `tool_choice`: `none`, `auto`, `any`, `tool` | Supported (`disable_parallel_tool_use` ignored). In thinking mode (the default) `tool` returns 400 `Thinking mode does not support this tool_choice`; `any` is accepted (verified 2026-10-15). Disable thinking to force a named tool |

Client-inserted tool calls mid-conversation are supported here (not on Chat Completions); mid-conversation system messages work on both. System-prompt updates differ per model — `GET /models` → `api_capabilities.anthropic_messages.system_prompt_update`: `deepseek-flash` = `in-history` (a later system message replaces the whole effective system prompt), `deepseek-v4-pro` = `leading-only` (only the leading system prompt counts; edit that one).

### Message content blocks

| Block | Status |
|---|---|
| string content, `text` | Fully supported (`cache_control`, `citations` ignored) |
| `thinking` | Supported |
| `tool_use` (`id`, `input`, `name`) | Fully supported (`cache_control` ignored) |
| `tool_result` (`tool_use_id`, `content`) | Fully supported (`cache_control`, `is_error` ignored) |
| `server_tool_use`, `web_search_tool_result` | Supported |
| `image` | Supported on `deepseek-flash`: `source.type` `base64` (jpeg/png/gif/webp), `url`, or `file` (needs `anthropic-beta: files-api-2025-04-14`). Limits: `vision.md`. **[field note]** `deepseek-v4-pro` is text-only: image blocks return 200 but aren't processed (input_tokens up only ~5; answers about the image are guesses: rechecked 2026-10-15, pro answered correctly with no image at all) |
| `document`, `search_result` | **NOT supported** |
| `redacted_thinking`, `code_execution_tool_result` | NOT supported |
| `mcp_tool_use`, `mcp_tool_result`, `container_upload` | NOT supported |
