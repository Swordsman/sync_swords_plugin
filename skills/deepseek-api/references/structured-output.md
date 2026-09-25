# Structured Output — JSON Mode & Chat Prefix Completion

## JSON Output

Guarantees syntactically valid JSON. **Not** a beta feature — standard base URL.

All three requirements must hold:

1. Set `"response_format": {"type": "json_object"}`.
2. The word **"json"** must appear in the system or user prompt, AND include an example of the desired shape. Without this the model may emit an unending stream of whitespace until the token limit — a long-running, seemingly "stuck" request.
3. Set `max_tokens` generously — `finish_reason: "length"` means truncated (invalid) JSON.

Bug: occasional empty content; adjust prompt, retry.

```python
system = 'Parse question+answer as JSON. Example: {"question":"...","answer":"..."}\nOutput JSON only.'
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "system", "content": system},
              {"role": "user", "content": "Which is the longest river in the world? The Nile River."}],
    response_format={"type": "json_object"})
print(json.loads(response.choices[0].message.content))
```

A third option — schema-validated tool arguments (strict mode) — often beats both for extraction tasks; see `tool-calling.md`.

## Chat Prefix Completion (Beta)

Force the assistant's reply to begin with a prefix you supply. Requires `base_url = "https://api.deepseek.com/beta"`.

Rules:

- The LAST message in `messages[]` must be `role: "assistant"` with `"prefix": true`.
- Combine with `stop` to bound the output.
- That assistant message also accepts `reasoning_content` as CoT input (Beta; only with `prefix: true`).

Classic use — force pure code output:

```python
client = OpenAI(api_key="...", base_url="https://api.deepseek.com/beta")
messages = [
    {"role": "user", "content": "Please write quick sort code"},
    {"role": "assistant", "content": "```python\n", "prefix": True},
]
response = client.chat.completions.create(
    model="deepseek-v4-pro", messages=messages, stop=["```"])
print(response.choices[0].message.content)   # bare code, fenced off by stop
```
