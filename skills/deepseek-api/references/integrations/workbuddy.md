# WorkBuddy / CodeBuddy on DeepSeek

Create `.codebuddy/models.json` (user or project level). Save as UTF-8 **without BOM**; restart to see the models in the selector. Set `DEEPSEEK_API_KEY` in the environment.

```json
{"models": [
  {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro",
   "url": "https://api.deepseek.com/v1/chat/completions",
   "apiKey": "${DEEPSEEK_API_KEY}", "maxInputTokens": 128000, "maxOutputTokens": 8192,
   "supportsToolCall": true, "supportsImages": false,
   "relatedModels": {"lite": "deepseek-v4-flash", "reasoning": "deepseek-v4-pro"}}
]}
```
