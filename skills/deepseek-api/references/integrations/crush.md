# Crush on DeepSeek

```bash
npm install -g @charmland/crush
```

Edit `~/.config/crush/crush.json`:

```json
{"providers": {"deepseek": {"type": "openai-compat", "base_url": "https://api.deepseek.com",
 "api_key": "...", "models": [{"id": "deepseek-v4-pro", "context_window": 1048576,
 "default_max_tokens": 32768, "can_reason": true}]}}}
```
