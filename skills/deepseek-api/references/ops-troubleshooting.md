# Errors, Rate Limits, Isolation, Ops Endpoints

## Error codes

| Code | Meaning | Cause | Fix |
|---|---|---|---|
| 400 | Invalid Format | Malformed request body — including **missing `reasoning_content` in a request carrying `tools`** (`thinking-mode.md`), `required`/named `tool_choice` in thinking mode, `stream_options` without `stream: true`, unknown model name | Fix body per the error message hints |
| 401 | Authentication Fails | Wrong/missing API key | Check key; create at platform.deepseek.com/api_keys |
| 402 | Insufficient Balance | Out of balance | Top up at platform.deepseek.com/top_up |
| 422 | Invalid Parameters | Bad parameter values | Fix per error message hints |
| 429 | Rate Limit Reached | Too many **concurrent** requests (see below) | Reduce in-flight requests; backoff |
| 500 | Server Error | Server-side | Retry after brief wait |
| 503 | Server Overloaded | High traffic | Retry after brief wait |

Also watch `finish_reason: "insufficient_system_resource"` or `"aborted"` on otherwise-200 responses.

Error bodies are OpenAI-shaped: `{"error": {"message": "... (request_id: ...)", "type": "invalid_request_error", "param": null, "code": "invalid_request_error"}}` — quote the `request_id` when reporting.

## Transient glitches — retry once first

DeepSeek's API has occasional momentary glitches: a call stalls or fails and the identical request works seconds later. **Retry once before debugging.** Only a repeat failure is worth investigating. **[field note]**

- A hang is also the symptom of a low `max_tokens` with thinking on — leave it unset (or `393216` where mandatory) before suspecting the network. **[field note]**
- Thinking streams can be silent for up to about 70 s while `: keep-alive` lines still arrive (`streaming.md`); that's normal. No bytes and no keep-alives at all suggests a glitch: retry once.

## Rate limits — concurrency, not RPM

- A request counts as one concurrent connection from send until the response completes.
- Limits: `deepseek-v4-pro` **500**, `deepseek-flash` **2500** — account-level, all API keys combined.
- Exceeding -> HTTP 429. There is no requests-per-minute limit to tune around; throttle *in-flight* count.
- Higher concurrency is free on request via the capacity-expansion form linked from the rate-limit docs page.

## user_id

Body: `"user_id": "[a-zA-Z0-9_-]+"` (<=512, no PII). SDK: `extra_body={"user_id":...}`. Anthropic: `metadata:{"user_id":...}`.
Purpose: content safety, KV-cache privacy, scheduling. On raised-quota accounts: per-user concurrency cap (pro 500 / flash 2500); overflow 429s only that user.

## Keep-alive & timeouts

- While waiting for inference: non-streaming responses emit **empty lines**; streaming emits `: keep-alive` SSE comments. Hand-rolled parsers must tolerate both.
- Connection closes if inference hasn't started within **10 minutes**; responses never continue past 10 minutes. Set client timeouts to ~10 min — longer never helps. **[field note]**

## GET /models

Live response, 2026-10-13 (pro entry trimmed):

```json
{"object": "list",
 "data": [{"id": "deepseek-flash", "object": "model", "owned_by": "deepseek",
           "name": "DeepSeek-V4.1-Flash",
           "context_window": 1048576, "max_output_tokens": 393216,
           "input_modalities": ["text", "image"], "output_modalities": ["text"],
           "effort": {"supported_levels": ["low", "high", "max"], "default_level": "high"},
           "api_capabilities": {"anthropic_messages": {"system_prompt_update": "in-history"}}},
          {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro",
           "input_modalities": ["text"],
           "api_capabilities": {"anthropic_messages": {"system_prompt_update": "leading-only"}}, "...": "..."}]}
```

- `max_output_tokens` is the largest accepted `max_tokens` — the value to use where a client makes `max_tokens` mandatory.
- `effort.supported_levels` excludes `none` (which turns thinking off). `system_prompt_update`: `anthropic-endpoint.md`.
- Legacy `deepseek-v4-flash` is no longer listed but still accepted (served as `deepseek-flash`).

## GET /user/balance

```json
{"is_available": true,
 "balance_infos": [{"currency": "CNY",
                    "total_balance": "110.00",
                    "granted_balance": "10.00",
                    "topped_up_balance": "100.00"}]}
```

`is_available`: whether balance suffices for API calls. `currency`: `CNY` or `USD`. `total_balance` = granted + topped-up; deduction consumes granted first.
