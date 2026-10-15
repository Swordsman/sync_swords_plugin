# WorkBuddy / CodeBuddy on DeepSeek

Create `.codebuddy/models.json` (user or project level). Save as UTF-8 **without BOM**; restart to see the models in the selector. Set `DEEPSEEK_API_KEY` in the environment.

```json
{"models": [
  {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro",
   "url": "https://api.deepseek.com/v1/chat/completions",
   "apiKey": "${DEEPSEEK_API_KEY}", "maxInputTokens": 128000, "maxOutputTokens": 393216,
   "supportsToolCall": true, "supportsImages": false,
   "relatedModels": {"lite": "deepseek-flash", "reasoning": "deepseek-v4-pro"}}
]}
```

`maxOutputTokens`: the max, `393216` — never lower (the official sample's 8192 starves thinking). **[field note]**
