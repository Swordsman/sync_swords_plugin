# Claude Code on DeepSeek

## Setup (existing Claude Code install)

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<your-deepseek-api-key>
export ANTHROPIC_MODEL='deepseek-flash[1m]'
export ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-flash[1m]'
export ANTHROPIC_DEFAULT_SONNET_MODEL='deepseek-flash[1m]'
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-flash
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-flash
export CLAUDE_CODE_EFFORT_LEVEL=max
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=393216   # Claude Code always sends max_tokens: the max, never lower
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=786432
```

Then run `claude` in any project directory.

Model mapping: -> anthropic-endpoint.md

This is DeepSeek's official setup (docs, 2026-10-13): every slot on `deepseek-flash[1m]`, haiku and subagent on `deepseek-flash`, plus the auto-compact window. For a stronger Opus slot, `deepseek-v4-pro` is the option (text only, 3 to 4 times Flash's price). `max_tokens`: Claude Code always sends one (Anthropic format), hence `CLAUDE_CODE_MAX_OUTPUT_TOKENS=393216` above — never lower. (Unverified whether Claude Code clamps it for non-Claude models.)

## Notes

- Web search works natively; search summarization generates extra LLM requests (additional token cost).
- Effort: DeepSeek auto-raises `reasoning_effort` to `max` for Claude Code-shaped requests (unverified since V4.1); `CLAUDE_CODE_EFFORT_LEVEL=max` aligns the client side.
