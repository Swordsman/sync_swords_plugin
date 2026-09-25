# Oh My Pi on DeepSeek

Oh My Pi's built-in DeepSeek entries are **incomplete — always use this custom config**. Write `~/.omp/agent/models.yml`:

```yaml
providers:
  deepseek:
    baseUrl: https://api.deepseek.com/openai/completions
    apiKey: DEEPSEEK_API_KEY
    authHeader: true
    models:
      deepseek-v4-pro:
        name: DeepSeek V4 Pro
        reasoning: true
        thinking:
          minLevel: high
          maxLevel: xhigh
          mode: effort
        input: text
        contextWindow: 1000000
        maxTokens: 384000
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: true
          maxTokensField: max_tokens
          reasoningEffortMap: {high: high, xhigh: max}
          supportsToolChoice: false
          requiresReasoningContentForToolCalls: true
          requiresAssistantContentForToolCalls: true
        extraBody:
          thinking: {type: enabled}
      deepseek-v4-flash:
        name: DeepSeek V4 Flash
        reasoning: true
        thinking:
          minLevel: high
          maxLevel: xhigh
          mode: effort
        input: text
        contextWindow: 1000000
        maxTokens: 384000
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: true
          maxTokensField: max_tokens
          reasoningEffortMap: {high: high, xhigh: max}
          supportsToolChoice: false
          requiresReasoningContentForToolCalls: true
          requiresAssistantContentForToolCalls: true
        extraBody:
          thinking: {type: enabled}
```

Compat fields encode thinking-mode tool quirks (-> tool-calling.md).
