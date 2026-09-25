# Errors, Rate Limits, Isolation, Ops Endpoints

## Error codes

| Code | Meaning | Cause | Fix |
|---|---|---|---|
| 400 | Invalid Format | Malformed request body — including **missing `reasoning_content` after tool calls in thinking mode** (`thinking-mode.md`) | Fix body per the error message hints |
| 401 | Authentication Fails | Wrong/missing API key | Check key; create at platform.deepseek.com/api_keys |
| 402 | Insufficient Balance | Out of balance | Top up at platform.deepseek.com/top_up |
| 422 | Invalid Parameters | Bad parameter values | Fix per error message hints |
| 429 | Rate Limit Reached | Too many **concurrent** requests (see below) | Reduce in-flight requests; backoff |
| 500 | Server Error | Server-side | Retry after brief wait |
| 503 | Server Overloaded | High traffic | Retry after brief wait |

Also watch `finish_reason: "insufficient_system_resource"` on otherwise-200 responses.

## Rate limits — concurrency, not RPM

- A request counts as one concurrent connection from send until the response completes.
- Limits: `deepseek-v4-pro` **500**, `deepseek-v4-flash` **2500** — account-level, all API keys combined.
- Exceeding -> HTTP 429. There is no requests-per-minute limit to tune around; throttle *in-flight* count.
- Higher concurrency is free on request via the capacity-expansion form linked from the rate-limit docs page.

## user_id

Body: `"user_id": "[a-zA-Z0-9_-]+"` (<=512, no PII). SDK: `extra_body={"user_id":...}`. Anthropic: `metadata:{"user_id":...}`.
Purpose: content safety, KV-cache privacy, scheduling. On raised-quota accounts: per-user concurrency cap (pro 500 / flash 2500); overflow 429s only that user.

## Keep-alive & timeouts

- While waiting for inference: non-streaming responses emit **empty lines**; streaming emits `: keep-alive` SSE comments. Hand-rolled parsers must tolerate both.
- Connection closes if inference hasn't started within **10 minutes**; responses never continue past 10 minutes. Set client timeouts to ~10 min — longer never helps. **[field note]**

## GET /models

```json
{"object": "list",
 "data": [{"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek"},
          {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"}]}
```

## GET /user/balance

```json
{"is_available": true,
 "balance_infos": [{"currency": "CNY",
                    "total_balance": "110.00",
                    "granted_balance": "10.00",
                    "topped_up_balance": "100.00"}]}
```

`is_available`: whether balance suffices for API calls. `currency`: `CNY` or `USD`. `total_balance` = granted + topped-up; deduction consumes granted first.
