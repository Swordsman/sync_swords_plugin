# Streaming (SSE)

Set `stream:true`. Response: `text/event-stream`, events as `data: {json}\n\n`, terminated by `data: [DONE]\n\n`.

## Chunk schema: `chat.completion.chunk`

```text
data: {"id":"...","choices":[{"index":0,"delta":{"content":"","role":"assistant"},"finish_reason":null,"logprobs":null}],"created":1718345013,"model":"deepseek-v4-pro","object":"chat.completion.chunk","system_fingerprint":"...","usage":null}

data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null,"index":0}], ...}

data: {"choices":[{"delta":{"content":""},"finish_reason":"stop","index":0}], ..., "usage":{"completion_tokens":9,"prompt_tokens":17,"total_tokens":26}}

data: [DONE]
```

- `delta` carries `content` / `reasoning_content` / `tool_calls` (instead of a full `message`); `delta.role` appears on the first chunk only.
- The final content chunk carries `finish_reason`.
- With `stream_options: {"include_usage": true}`: one extra chunk before `[DONE]` holds full-request `usage` and an **empty** `choices: []`; all other chunks carry `usage: null`. Guard for empty `choices` before indexing.

## Parsing rules (hand-rolled clients)

1. **Tolerate `: keep-alive` comment lines** between chunks — the server injects them during processing lag so the socket stays open. Naive line-by-line JSON parsers break here.
2. **Accumulate `reasoning_content` and `content` separately** — in thinking mode they arrive in alternating chunks:

```python
reasoning_content, content = "", ""
for chunk in response:
    if not chunk.choices:            # usage-only final chunk
        continue
    delta = chunk.choices[0].delta
    if getattr(delta, "reasoning_content", None):
        reasoning_content += delta.reasoning_content
    elif delta.content:
        content += delta.content
```

Then rebuild the assistant message from both parts when appending to history (`{"role": "assistant", "reasoning_content": ..., "content": ...}`).

## Timing behavior

- **Bursts and pauses are normal.** Thinking output may pause up to ~70 seconds, mostly right at the start, then arrive in a torrent. **[field note]** Longer initial silence generally predicts a longer stream to follow — don't kill the connection on early silence.
- **10-minute hard cap**: the server will not continue a response past 10 minutes from request start, and closes connections whose inference hasn't begun within 10 minutes. Set client timeouts to ~10 minutes; longer is never useful. **[field note]**

## When to stream at all [field note]

Non-thinking completes in ~2s (little benefit). Thinking benefits when monitoring for stuck/misdirected generation. If nothing monitors: non-streaming is simpler.
