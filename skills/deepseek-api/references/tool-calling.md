# Tool Calls (Function Calling)

Works in non-thinking and thinking mode. Thinking-mode context rules (`reasoning_content` resend requirement): -> thinking-mode.md.

## Definition format

Max **128** tools per request. Only `function` type:

```json
{"type": "function",
 "function": {"name": "get_weather",     // req, [a-zA-Z0-9_-], ≤64 chars
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
messages = [{"role": "user", "content": "How's the weather in Hangzhou?"}]
message = client.chat.completions.create(
    model="deepseek-v4-pro", messages=messages, tools=tools
).choices[0].message

tool = message.tool_calls[0]
messages.append(message)                                   # assistant msg w/ tool_calls
messages.append({"role": "tool", "tool_call_id": tool.id,  # your result
                 "content": "24℃"})
final = client.chat.completions.create(
    model="deepseek-v4-pro", messages=messages, tools=tools
).choices[0].message
```

`finish_reason` is `tool_calls` and `message.content` is null on tool-call responses.

## Hard constraints and quirks

- **No parallel tool calls** — at most one round of calls at a time.
- **Thinking mode**: after any tool-call turn, resend `reasoning_content` (-> thinking-mode.md) or 400.
- **[field note]** `tool_choice` rejected in thinking mode — omit it.
- **[field note]** Keep `content` non-null on assistant tool-call messages in replayed history.

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
