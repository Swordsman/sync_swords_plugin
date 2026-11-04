# Tool Calls (Function Calling)

Works in non-thinking and thinking mode. Thinking-mode context rules (`reasoning_content` resend requirement): -> thinking-mode.md.

## Definition format

No documented tool-count cap (older docs said 128; 129 was accepted live 2026-10-13). Only `function` type:

```json
{"type": "function",
 "function": {"name": "get_weather",     // req, [a-zA-Z0-9_-], ≤128 chars
              "description": "Get weather of a location; user supplies location first.",
              "parameters": {             // JSON Schema; omit entirely = no params
                  "type": "object",
                  "properties": {"location": {"type": "string",
                                              "description": "City and state, e.g. San Francisco, CA"}},
                  "required": ["location"]},
              "strict": false}}           // Beta, see below
```

`tool_choice`: `"none"` | `"auto"` (default when tools present) | `"required"` | `{"type": "function", "function": {"name": "..."}}`.

## Basic loop (non-thinking)

```python
messages = [{"role": "user", "content": "How's the weather in Hangzhou and Beijing?"}]
message = client.chat.completions.create(
    model="deepseek-v4-pro", messages=messages, tools=tools,
    extra_body={"thinking": {"type": "disabled"}},
).choices[0].message

messages.append(message)                                   # assistant msg w/ tool_calls
for tool in message.tool_calls:                            # may be several (parallel)
    messages.append({"role": "tool", "tool_call_id": tool.id,  # your result
                     "content": run_tool(tool)})
final = client.chat.completions.create(
    model="deepseek-v4-pro", messages=messages, tools=tools,
    extra_body={"thinking": {"type": "disabled"}},
).choices[0].message
```

`run_tool` is your own function; it returns the tool's result as a string.

`finish_reason` is `tool_calls` on tool-call responses. `message.content` may still carry a short preamble ("I'll check both cities.") — observed non-null on both models 2026-10-13; don't assume null.

## Hard constraints and quirks

- **Parallel tool calls happen** — one assistant message can carry several `tool_calls` (verified 2026-10-13: flash thinking + non-thinking, pro non-thinking). Answer each `tool_call_id`.
- **Thinking mode**: requests carrying `tools` must resend prior `reasoning_content` (-> thinking-mode.md) or 400.
- **Thinking mode `tool_choice`**: `required` and named choices → HTTP 400 (`Thinking mode does not support this tool_choice`); `auto`/`none` work (verified 2026-10-13). Disable thinking to force a call.
- **[field note]** `tool_choice: "none"` drops the tool definitions from the prompt entirely (`prompt_tokens` shows it) — no tool-token cost, but the model can't see them.
- **[field note]** Keep `content` non-null on assistant tool-call messages in replayed history.
- **Mid-conversation inserts**: Chat Completions does not support client-inserted tool calls (ones the model didn't generate) mid-history; the Anthropic endpoint and Responses API do. Mid-conversation system messages work on all.

## Strict mode (Beta) — schema-guaranteed arguments

Guarantees tool-call arguments conform to the function's JSON Schema. Works in thinking and non-thinking mode.

1. Use `base_url = "https://api.deepseek.com/beta"`.
2. Set `"strict": true` on **every** function in `tools`.
3. The server validates your schema at request time; unsupported keywords → error.

### Supported JSON Schema subset

Types: `object`, `string`, `number`, `integer`, `boolean`, `array`, `enum`, `anyOf`.

| Type | Supported | NOT supported |
|---|---|---|
| object | — (see rules below) | — |
| string | `pattern`, `format` (`email`, `hostname`, `ipv4`, `ipv6`, `uuid`) | `minLength`, `maxLength` |
| number/integer | `const`, `default`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf` | — |
| array | `items` | `minItems`, `maxItems` |

Rules:

- Every object must list ALL properties in `required` and set `additionalProperties: false`.
- `anyOf`: match any one of several schemas (e.g. email OR phone shape).
- `$def` / `$ref`: reusable and recursive schemas — define under `$def`, reference with `"$ref": "#/$def/name"`.

### Worked $def example

```json
{
  "type": "object",
  "properties": {
    "report_date": {"type": "string"},
    "authors": {"type": "array", "items": {"$ref": "#/$def/author"}}
  },
  "required": ["report_date", "authors"],
  "additionalProperties": false,
  "$def": {
    "author": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "institution": {"type": "string"},
        "email": {"type": "string", "format": "email"}
      },
      "required": ["name", "institution", "email"],
      "additionalProperties": false
    }
  }
}
```
