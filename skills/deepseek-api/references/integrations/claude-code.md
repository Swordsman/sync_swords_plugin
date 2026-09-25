# Claude Code on DeepSeek

## Setup (existing Claude Code install)

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<your-deepseek-api-key>
export ANTHROPIC_MODEL=deepseek-v4-pro
export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro
export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
export CLAUDE_CODE_EFFORT_LEVEL=max
```

Then run `claude` in any project directory.

Model mapping: -> anthropic-endpoint.md

## Notes

- Web search works natively; search summarization generates extra LLM requests (additional token cost).
- Effort: DeepSeek auto-raises `reasoning_effort` to `max` for Claude Code-shaped requests; `CLAUDE_CODE_EFFORT_LEVEL=max` aligns the client side.
