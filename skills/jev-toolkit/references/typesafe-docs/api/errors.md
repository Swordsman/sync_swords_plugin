> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Request rules and errors

> Request limits, compression, and HTTP status codes

## Request rules

These rules apply to every request:

| Rule | Limit |
| - | - |
| Body size | At most 32 MiB. Headers don't count. |
| Encoding | UTF-8 JSON without a byte order mark (BOM). |
| Nesting | At most 64 nested levels of objects and arrays in each of `state`, `instructions`, and `criteria`. Flatten deeper content. |
| Numbers | Finite numbers only. `NaN`, `Infinity`, and numbers too large to represent, such as `1e400`, are rejected. Send identifiers and exact large quantities as strings. |

A body over 32 MiB returns `413`; the other rules return `400`.

### Compression

You can compress the body with `Content-Encoding: gzip` (or `x-gzip`) or `zstd`. Use one compression layer, and keep zstd's window at most 8 MiB. The 32 MiB limit applies to both the compressed and the decompressed body. An unsupported `Content-Encoding` or more than one layer returns `415`; a malformed compressed body returns `400`.

## Errors

Errors use standard HTTP status codes with a JSON body describing what went wrong.

| Status | Meaning |
| - | - |
| `400 Bad Request` | The body breaks a [request rule](#request-rules), such as invalid UTF-8, too much nesting, a number that isn't finite, or a malformed compressed body. With `max_tokens_exceeded`, the request is longer than the model's [context length](https://docs.typesafe.ai/models.md). |
| `401 Unauthorized` | Missing or invalid API key. Check the `Authorization` header. |
| `413 Payload Too Large` | The body is over 32 MiB. See [Request rules](#request-rules). |
| `415 Unsupported Media Type` | The body uses an unsupported `Content-Encoding` or more than one compression layer. See [Compression](#compression). |
| `422 Unprocessable Entity` | The request body failed validation, for example a missing required field or a malformed question. The body details the offending field. |
| `429 Too Many Requests` | You have exceeded your rate limit. Back off and retry after a short delay. |
| `529 Overloaded` | TypeSafe is temporarily overloaded. Retry after a short delay. |

## Handling rate limits

When you receive a `429 Too Many Requests` or `529 Overloaded` response, retry the request with exponential backoff instead of retrying immediately. Our client SDKs handle this automatically, so no extra handling is needed if you use one of our SDKs with its default retry policy.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.