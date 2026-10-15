# Pi (pi-mono) on DeepSeek

```bash
npm install -g @mariozechner/pi-coding-agent
```

Edit `~/.pi/agent/models.json` — the `compat` fields encode DeepSeek's thinking-mode quirks (`tool-calling.md`):

```json
{"providers": {"deepseek": {"baseUrl": "https://api.deepseek.com",
 "api": "openai-completions", "apiKey": "...",
 "models": [{"id": "deepseek-v4-pro", "contextWindow": 1000000,
 "maxTokens": 393216, "input": ["text"], "reasoning": true,
 "compat": {"requiresReasoningContentOnAssistantMessages": true,
            "thinkingFormat": "deepseek"}}]}}}
```

`maxTokens`: the max, `393216` — never lower.

Supports extensions, skills, prompt templates, themes, tree-structured sessions.
