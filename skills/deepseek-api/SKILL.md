---
name: deepseek-api
description: "Direct raw-call access to the DeepSeek API (api.deepseek.com) via curl, Python, or Node — OpenAI-compatible and Anthropic-compatible endpoints. Use when the user wants to call DeepSeek models (deepseek-v4-pro, deepseek-v4-flash, deepseek-chat, deepseek-reasoner) by hand without a prebuilt integration: chat completions, thinking/reasoning mode, tool/function calling, JSON output, FIM or chat-prefix completion, streaming, checking models or account balance, or debugging DeepSeek HTTP requests/responses."
---

# DeepSeek API

Snapshot: api-docs.deepseek.com, July 2026. Prefer over training memory (V4 changed names/params). **[field note]** = integration experience; reliable, verify on conflict. On contradiction with observed behavior, fetch the source URL from the reference file header.

## Essentials

**Auth**: `Authorization: Bearer $DEEPSEEK_API_KEY` (OpenAI) or `x-api-key: $DEEPSEEK_API_KEY` (Anthropic). Keys: platform.deepseek.com/api_keys.

**Base URLs**:

| Format | base_url |
|---|---|
| OpenAI-compatible | `https://api.deepseek.com` |
| Anthropic-compatible | `https://api.deepseek.com/anthropic` |
| Beta (FIM, chat prefix, strict tools) | `https://api.deepseek.com/beta` |
| OpenAI-SDK compat alias | `https://api.deepseek.com/v1` (not a version selector) |

**Models**: `deepseek-v4-pro` (top reasoning, agent coding), `deepseek-v4-flash` (near-pro, ~1/10 cost). Both: 1M context, 384K max output, text-only. Legacy `deepseek-chat`/`deepseek-reasoner` -> v4-flash; **retire 2026-07-24**.

**Endpoints**: `POST /chat/completions` (main), `POST /completions` (FIM, beta only), `GET /models`, `GET /user/balance`.

## Minimal call

```bash
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
  -d '{"model": "deepseek-v4-pro",
       "messages": [{"role": "user", "content": "Hello!"}],
       "stream": false}'
```

Wrapper: `scripts/deepseek.sh chat|stream|models|balance|raw` (e.g. `./scripts/deepseek.sh chat "Hello"`).

## Gotchas (all tasks)

- **Thinking ON by default.** Disable: `"thinking":{"type":"disabled"}`. `temperature`/`top_p` ignored when thinking.
- **Unset thinking+effort = best.** Auto high/max per request; fixed effort forfeits auto-escalation. [field note]
- **max_tokens includes thinking tokens.** Low cap starves reasoning. Omit or >=50K. [field note]
- **Stateless.** Resend full history. After tool calls: `reasoning_content` MUST be resent (-> thinking-mode.md) or HTTP 400.
- **OpenAI SDK:** `thinking`, `user_id` -> `extra_body={}`, not top-level.
- **10min hard cap** on inference start and response duration. [field note]
- **Keep-alive noise:** empty lines (non-streaming) / `: keep-alive` (streaming). Parsers must tolerate.
- **429 = concurrency** (pro 500 / flash 2500 in-flight), not RPM.
- **Inert:** `frequency_penalty`, `presence_penalty`.
- **Absent:** parallel tool calls, vision, MCP passthrough.

## Load knowledge on demand

```bash
scripts/knowledge.sh thinking tools     # serve named fragments (deduped per agent-id)
scripts/knowledge.sh agent-loop         # bundle = thinking + tools
scripts/knowledge.sh list               # all fragments and bundles
```

Dedup: served fragments return skip notice; `--again` reprints. State per agent-id (`--id=NAME`, default `main`). Subagents: `register <name>` first, pass `--id=<name>` in spawn prompt. `status` shows all ids. Fallback: `cat references/<file>`.

| Trigger | Fragment | File |
|---|---|---|
| chat request/response params + schema | `chat` | `references/chat-completions.md` |
| streaming, SSE parsing, keep-alives | `streaming` | `references/streaming.md` |
| thinking control, effort, reasoning_content rules | `thinking` | `references/thinking-mode.md` |
| tool/function calling, strict mode | `tools` | `references/tool-calling.md` |
| JSON mode, chat prefix completion | `structured` | `references/structured-output.md` |
| FIM / code completion | `fim` | `references/fim-completion.md` |
| Anthropic SDK/Messages compat | `anthropic` | `references/anthropic-endpoint.md` |
| model choice, pricing, caching | `pricing` | `references/pricing-caching.md` |
| HTTP errors, rate limits, /models, /balance | `ops` | `references/ops-troubleshooting.md` |
| agent/IDE integration configs | `integrations` (router) then per-tool: `claude-code`, `copilot`, `oh-my-pi`, `nanobot`, `crush`, `deep-code`, `workbuddy`, `pi` | `references/integrations.md` -> `references/integrations/<tool>.md` |
