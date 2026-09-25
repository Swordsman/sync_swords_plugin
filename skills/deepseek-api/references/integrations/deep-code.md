# Deep Code on DeepSeek

```bash
npm install -g @vegamo/deepcode-cli
```

Edit `~/.deepcode/settings.json`:

```json
{"env": {"MODEL": "deepseek-v4-pro", "BASE_URL": "https://api.deepseek.com",
 "API_KEY": "...", "thinkingEnabled": true, "reasoningEffort": "max"}}
```

- Agent Skills go in `~/.agents/skills/` (user) or `./.deepcode/skills/` (project).
- Web search supported. VS Code extension available.
