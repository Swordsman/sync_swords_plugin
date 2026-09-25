# Agent & Tool Integrations

Wiring DeepSeek into coding agents / IDE tools.

OpenAI-compat: base_url api.deepseek.com (some need /v1). Anthropic-compat: api.deepseek.com/anthropic. Thinking-mode compat behaviors: -> tool-calling.md.

## Interactive-setup tools — the row below IS the whole setup

| Tool | Setup |
|---|---|
| OpenCode | ≥ v1.14.24. TUI: `/connect` → enter `deepseek` → select provider → API key → select model |
| Kilo Code | `npm install -g @kilocode/cli` → `kilo` → TUI: `/connect` → DeepSeek → API key → `/models` → choose model |
| OpenClaw | `curl -fsSL https://openclaw.ai/install.sh \| bash` → `openclaw onboard --install-daemon` → select DeepSeek, API key, model. TUI, Web UI, terminal chat |
| AstrBot | Install via uv or Docker → Web UI `localhost:6185` → Providers → Add → DeepSeek → paste API key. Supports QQ, WeChat, Feishu, Telegram |
| Hermes Agent | Install script from `NousResearch/hermes-agent` repo → `hermes setup` → Quick Setup → DeepSeek → API key → base URL `https://api.deepseek.com` → model |
| Reasonix | DeepSeek-native, no translation shim. `npx reasonix code` in project dir. Flash by default; `/pro` arms Pro next turn; `/preset max` for full session. Key via built-in wizard → `~/.reasonix/config.json` |
| Langcli | `npm i -g langcli-com` → `langcli`. Requires LangRouter account (free trial) |

## Config-file tools — read ONLY the file for the tool you're configuring

| Tool | File |
|---|---|
| Claude Code | `integrations/claude-code.md` |
| GitHub Copilot (VS Code) / Copilot CLI | `integrations/copilot.md` |
| Oh My Pi | `integrations/oh-my-pi.md` (built-in entries incomplete — custom models.yml required) |
| nanobot | `integrations/nanobot.md` |
| Crush | `integrations/crush.md` |
| Deep Code | `integrations/deep-code.md` |
| WorkBuddy / CodeBuddy | `integrations/workbuddy.md` |
| Pi (pi-mono) | `integrations/pi.md` |

## External

- Community integrations directory: https://github.com/deepseek-ai/awesome-deepseek-integration
- Agent-framework integrations: https://github.com/deepseek-ai/awesome-deepseek-agent
