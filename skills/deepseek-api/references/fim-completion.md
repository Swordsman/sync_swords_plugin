# FIM Completion (Beta) — POST /completions

Fill-in-the-middle between prefix + suffix. Beta endpoint only: `POST https://api.deepseek.com/beta/completions`. v4-pro only, non-thinking, single-turn, max_tokens capped at 4K.

## Request parameters

| Param | Notes |
|---|---|
| `model` (req) | `deepseek-v4-pro` |
| `prompt` (req) | Prefix text before the gap |
| `suffix` | Text after the gap |
| `max_tokens` | ≤ 4K |
| `temperature` (0–2, default 1), `top_p` (≤1, default 1) | Alter one, not both |
| `echo` | Echo the prompt back in the output |
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
- `finish_reason`: `stop` | `length` | `content_filter` | `insufficient_system_resource`.
- FIM logprobs shape differs from chat: `tokens[]`, `token_logprobs[]`, `text_offset[]` (char offsets), `top_logprobs[]`.

## Sample

```python
from openai import OpenAI
client = OpenAI(api_key="...", base_url="https://api.deepseek.com/beta")
response = client.completions.create(
    model="deepseek-v4-pro",
    prompt="def fib(a):",
    suffix="    return fib(a-1) + fib(a-2)",
    max_tokens=128)
print(response.choices[0].text)
```
