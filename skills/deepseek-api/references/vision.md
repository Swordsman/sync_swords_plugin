# Vision — Image Input

`deepseek-flash` (V4.1 Flash) takes images natively; `deepseek-v4-pro` is text-only. Legacy `deepseek-v4-flash-vision-exp` is accepted but retired — served by `deepseek-flash`. Source: api-docs.deepseek.com/guides/vision, 2026-10-13.

## Sending images (Chat Completions)

`content` becomes an array of parts. Three ways in:

```json
{"model": "deepseek-flash",
 "messages": [{"role": "user", "content": [
   {"type": "text", "text": "What is in this image?"},
   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<B64>", "detail": "low"}}
 ]}]}
```

| Method | Part | Notes |
|---|---|---|
| Inline base64 | `{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}` | Counts toward the 48 MiB request body |
| External URL | `{"type": "image_url", "image_url": {"url": "https://..."}}` | ≤8192-char URL, ≤32 MiB image, download must finish in 60 s |
| Files API | `{"type": "file", "file_id": "file-api-..."}` or `{"type": "file", "file_data": "data:...", "filename": "x.jpg"}` | Upload once, reuse; `file_id` images up to 64 MiB. `file_id` / `file_data` mutually exclusive |

- `detail` (image_url only): `low` = downscale to 512×512 (faster, cheaper); `high` / `original` / `auto` keep the original.
- Formats: JPEG, PNG, GIF, WebP — detected from file content, not name or MIME type.
- Images go in **user** messages (the API reference also allows them in **tool** message content); in system or assistant messages → HTTP 400.
- Anthropic endpoint: `{"type": "image", "source": {"type": "base64"|"url"|"file", ...}}` — `anthropic-endpoint.md`. Responses API: `input_image` parts.
- **[field note]** Images sent to `deepseek-v4-pro` don't error (200) but aren't tokenized as images (2026-10-13) — check the model before blaming the prompt.

## Token cost

Images are resized before inference: below ~544×544 total pixels scaled up, larger scaled down to ~1300×1300 total pixels (aspect ratio kept). So **≤1024 tokens per image**, each image counted independently, billed with text tokens. Calculator: api-docs.deepseek.com/quick_start/token_usage. **[field note]** An 8×8 PNG cost ~180 tokens on 2026-10-13.

## Limits

| Limit | Value |
|---|---|
| Request body | 48 MiB |
| Single image (base64 / URL) | 32 MiB |
| Single image (Files API `file_id`) | 64 MiB |
| Images per request | 600 |
| Total image size per request | 64 MiB without `file_id` images; up to 200 MiB with them |
| Max dimension | 8192 px per side; 4096 px when a request has ≥15 images |
