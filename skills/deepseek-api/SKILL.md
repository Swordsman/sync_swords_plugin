---
name: deepseek-api
description: "Direct raw-call access to the DeepSeek API (api.deepseek.com) via curl, Python, or Node — OpenAI-compatible and Anthropic-compatible endpoints. Use when the user wants to call DeepSeek models (deepseek-flash = V4.1 Flash, deepseek-v4-pro; legacy names deepseek-v4-flash, deepseek-chat, deepseek-reasoner) by hand without a prebuilt integration: chat completions, thinking/reasoning mode, tool/function calling, image input (vision), JSON output, FIM or chat-prefix completion, streaming, checking models or account balance, or debugging DeepSeek HTTP requests/responses."
---

# DeepSeek API

Snapshot: api-docs.deepseek.com + live API checks, 2026-10-13. Prefer over training memory (V4.1 changed names/params). **[field note]** = integration experience; reliable, verify on conflict. On contradiction with observed behavior, re-check api-docs.deepseek.com (change log: `/updates`).

## Essentials

**Auth**: `Authorization: Bearer $DEEPSEEK_API_KEY` (OpenAI) or `x-api-key: $DEEPSEEK_API_KEY` (Anthropic). Keys: platform.deepseek.com/api_keys.

**Base URLs**:

| Format | base_url |
|---|---|
| OpenAI-compatible | `https://api.deepseek.com` |
| Anthropic-compatible | `https://api.deepseek.com/anthropic` |
| Beta (FIM, chat prefix, strict tools) | `https://api.deepseek.com/beta` |
| OpenAI-SDK compat alias | `https://api.deepseek.com/v1` (not a version selector) |

**Models**: `deepseek-flash` (DeepSeek-V4.1-Flash: DeepSeek's recommended model (the docs say "Use deepseek-flash"; V4-Pro is being phased out), reported ahead of V4-Pro at ~1/4–1/3 Pro's cache-miss and output price (cache hit ~1/7); **text + image input**) and `deepseek-v4-pro` (DeepSeek-V4-Pro-0813, text-only). Both: 1M context (1048576), 384K max output (393216). `deepseek-v4-flash` is a **retired legacy name**: still accepted, served by V4.1 Flash at the Flash price (responses report `"model": "deepseek-flash"`); same for `deepseek-v4-flash-vision-exp`. Legacy `deepseek-chat`/`deepseek-reasoner` passed their 2026-07-24 retirement date but were still accepted on 2026-10-13 (served as deepseek-flash non-thinking/thinking) — don't build on them. [field note]

**Endpoints**: `POST /chat/completions` (main), `POST /completions` (FIM, beta only), `GET /models`, `GET /user/balance`. Also `POST /responses` (OpenAI Responses format, for Codex; not covered here — api-docs.deepseek.com/guides/responses_api).

## Minimal call

```bash
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
  -d '{"model": "deepseek-v4-pro",
       "messages": [{"role": "user", "content": "Hello!"}],
       "stream": false}'
```

Wrapper: `scripts/deepseek.sh chat|stream|models|balance|raw` (e.g. `./scripts/deepseek.sh chat "Hello"`). A prompt or body of any real size goes in a file or on stdin, never on the command line: `chat - < prompt.txt`, `raw chat/completions body.json`. Linux refuses any one argument over 128 KiB, and a resent conversation passes that quickly; the wrapper hands curl every body on stdin (`--data-binary @-`).

## Gotchas (all tasks)

- **Thinking ON by default** (effort `high`). Disable: `"thinking":{"type":"disabled"}` or `"reasoning_effort":"none"`. `temperature` ignored when thinking; `top_p` works only when thinking (floor 0.95), fixed at 1.0 otherwise.
- **Effort**: `low` / `high` / `max`. Unset thinking+effort was observed to auto-escalate hard requests to max; fixed effort forfeits that. [field note, unverified since V4.1]
- **Leave `max_tokens` unset.** The default is stable; setting it is brittle. (Unset default: 8K non-thinking, verified; 64K thinking, 128K at `max`, per docs; see chat-completions.md.) Where a client makes it mandatory (Anthropic SDK / endpoint), set the max, `393216` — never lower: thinking tokens count against it, and a low cap can glitch the call and leave it hanging. [field note]
- **Stateless.** Resend full history. Requests carrying `tools`: prior `reasoning_content` MUST be resent (-> thinking-mode.md) or HTTP 400.
- **OpenAI SDK:** `thinking`, `user_id` -> `extra_body={}`, not top-level.
- **10min hard cap** on inference start and response duration. [field note]
- **Keep-alive noise:** empty lines (non-streaming) / `: keep-alive` (streaming). Parsers must tolerate.
- **Transient glitches:** a call occasionally stalls or fails and works seconds later. Retry once before debugging (-> ops-troubleshooting.md). [field note]
- **429 = concurrency** (pro 500 / flash 2500 in-flight), not RPM.
- **Parallel tool calls happen**: one message can carry several `tool_calls` (both models; verified 2026-10-13). Answer each one.
- **Vision**: `deepseek-flash` only (-> vision.md). Pro is text-only.
- **Inert:** `frequency_penalty`, `presence_penalty`. **Absent:** MCP passthrough.

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
| image input, image limits, image tokens | `vision` | `references/vision.md` |
| JSON mode, chat prefix completion | `structured` | `references/structured-output.md` |
| FIM / code completion | `fim` | `references/fim-completion.md` |
| Anthropic SDK/Messages compat | `anthropic` | `references/anthropic-endpoint.md` |
| model choice, pricing, caching | `pricing` | `references/pricing-caching.md` |
| HTTP errors, glitches, rate limits, /models, /balance | `ops` | `references/ops-troubleshooting.md` |
| agent/IDE integration configs | `integrations` (router) then per-tool: `claude-code`, `copilot`, `oh-my-pi`, `nanobot`, `crush`, `deep-code`, `workbuddy`, `pi` | `references/integrations.md` -> `references/integrations/<tool>.md` |
