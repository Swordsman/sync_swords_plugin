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
    max_tokens=100000,          # thinking is on by default — don't set this low
    system="You are a helpful assistant.",
    messages=[{"role": "user",
               "content": [{"type": "text", "text": "Hi, how are you?"}]}])
print(message.content)
```

## Model mapping

| Requested | Serves |
|---|---|
| `claude-opus*` | `deepseek-v4-pro` |
| `claude-sonnet*` / `claude-haiku*` | `deepseek-v4-flash` |
| any other unsupported name | `deepseek-v4-flash` |

## Compatibility tables

### HTTP headers

| Header | Status |
|---|---|
| `x-api-key` | Fully supported |
| `anthropic-beta`, `anthropic-version` | Ignored |

### Request fields

| Field | Status |
|---|---|
| `model`, `max_tokens`, `stop_sequences`, `stream`, `system` | Fully supported |
| `temperature` | Supported, range 0.0–2.0 (note: wider than Anthropic's 0–1) |
| `top_p` | Fully supported |
| `thinking` | Supported (`budget_tokens` **ignored** — effort is the only lever) |
| `output_config` | Only `effort` supported (`"high"`/`"max"` — see `thinking-mode.md`) |
| `metadata` | Only `user_id` supported (`ops-troubleshooting.md`) |
| `top_k`, `container`, `mcp_servers`, `service_tier` | Ignored |

### Tools

| Field | Status |
|---|---|
| `name`, `input_schema`, `description` | Fully supported |
| `cache_control` | Ignored (DeepSeek's own prefix cache still applies automatically — `pricing-caching.md`) |
| `tool_choice`: `none`, `auto`, `any`, `tool` | Supported (`disable_parallel_tool_use` ignored — parallel calls never happen anyway) |

### Message content blocks

| Block | Status |
|---|---|
| string content, `text` | Fully supported (`cache_control`, `citations` ignored) |
| `thinking` | Supported |
| `tool_use` (`id`, `input`, `name`) | Fully supported (`cache_control` ignored) |
| `tool_result` (`tool_use_id`, `content`) | Fully supported (`cache_control`, `is_error` ignored) |
| `server_tool_use`, `web_search_tool_result` | Supported |
| `image`, `document`, `search_result` | **NOT supported** — text-only model |
| `redacted_thinking`, `code_execution_tool_result` | NOT supported |
| `mcp_tool_use`, `mcp_tool_result`, `container_upload` | NOT supported |
