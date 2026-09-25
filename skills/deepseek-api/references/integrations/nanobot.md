# nanobot on DeepSeek

```bash
uv tool install nanobot-ai
nanobot onboard
```

Edit `~/.nanobot/config.json`:

```json
{"agents": {"defaults": {"model": "deepseek-v4-pro", "provider": "deepseek"}},
 "providers": {"deepseek": {"apiKey": "...", "apiBase": "https://api.deepseek.com/v1"}}}
```
