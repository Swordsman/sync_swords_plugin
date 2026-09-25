# GitHub Copilot on DeepSeek — VS Code Extension & Copilot CLI

## Copilot Chat (VS Code extension)

Install the **"DeepSeek V4 for Copilot Chat"** extension from its GitHub repo. Requires VS Code **1.116+** and an active Copilot subscription.

- API key: Command Palette → `DeepSeek: Set API Key` (stored in the OS keychain).
- Model selection: Copilot Chat model picker.
- Thinking effort: gear icon → None / High / Max.
- Vision: DeepSeek is text-only, so the extension proxies images through another Copilot model for description first.

## Copilot CLI

Use the **Anthropic-compatible** endpoint — NOT the OpenAI one. **[field note]** The OpenAI-compat path in Copilot CLI has a `reasoning_content` echo bug; the Anthropic path avoids it.

```bash
export COPILOT_PROVIDER_TYPE=anthropic
export COPILOT_PROVIDER_BASE_URL=https://api.deepseek.com/anthropic
export COPILOT_PROVIDER_API_KEY=<your-deepseek-api-key>
export COPILOT_MODEL=deepseek-v4-pro
```
