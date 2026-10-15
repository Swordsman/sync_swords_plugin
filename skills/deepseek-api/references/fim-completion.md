# FIM Completion (Beta) — POST /completions

Fill-in-the-middle between prefix + suffix. Beta endpoint only: `POST https://api.deepseek.com/beta/completions` (the non-beta path returns 400). Both models (`deepseek-flash`, `deepseek-v4-pro`; verified 2026-10-13), non-thinking, single-turn, output capped at 4K tokens.

## Request parameters

| Param | Notes |
|---|---|
| `model` (req) | `deepseek-flash` or `deepseek-v4-pro` |
| `prompt` (req) | Prefix text before the gap |
| `suffix` | Text after the gap |
| `max_tokens` | Leave unset. If a client forces a value, use `393216` (accepted, verified 2026-10-15); output is still capped at 4K. **[field note]** |
| `temperature` (0–2, default 1), `top_p` (≤1, default 1) | Alter one, not both |
| `echo` | Echo the prompt back in the output. Cannot be combined with `suffix` or `logprobs` |
| `logprobs` | int ≤ 20 — returns the sampled token plus top-N per position |
| `stop` | string or string[], up to 16 |
| `stream`, `stream_options.include_usage` | Same SSE semantics as chat — see `streaming.md` |
| `frequency_penalty`, `presence_penalty` | Deprecated, inert |

## Response: `text_completion`

```json
{
  "id": "...", "object": "text_completion", "created": 1718345013,
  "model": "deepseek-v4-pro", "system_fingerprint": "...",
  "choices": [{"index": 0, "finish_reason": "stop", "text": "...",
               "logprobs": {"text_offset": [0], "token_logprobs": [0.0],
                            "tokens": ["..."], "top_logprobs": [{}]}}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}
}
```

- `choices[].text` holds the completion (not `message`).
- `finish_reason`: `stop` | `length` | `content_filter` | `insufficient_system_resource` | `aborted`.
- FIM logprobs shape differs from chat: `tokens[]`, `token_logprobs[]`, `text_offset[]` (char offsets), `top_logprobs[]`.

## Sample

```python
from openai import OpenAI
client = OpenAI(api_key="...", base_url="https://api.deepseek.com/beta")
response = client.completions.create(
    model="deepseek-v4-pro",
    prompt="def fib(a):",
    suffix="    return fib(a-1) + fib(a-2)")
print(response.choices[0].text)
```
