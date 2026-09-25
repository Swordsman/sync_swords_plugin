# provider-library

Offline LLM API documentation reference cache.

## What it does

Curated, offline copies of LLM provider API documentation for reference during development. Pre-scraped and indexed for AI-agent consumption.

## Available providers

| Provider | Status | Size |
|----------|--------|------|
| DeepSeek | Full skill (`/deepseek-api`) | curated |
| Anthropic | Raw docs | large (~360MB) |
| OpenRouter | Raw docs | ~5MB |
| Groq | Raw docs | ~49MB |
| Mistral | Raw docs | ~30MB |
| ElevenLabs | Raw docs | ~14MB |
| Gemini | Raw docs | small |
| Inception | Raw docs | small |
| FastHTML | Raw docs | small |

## Usage

For DeepSeek, use the dedicated `/deepseek-api` skill which has curated references and on-demand fragment loading.

For other providers, reference the upstream repo directly — the raw docs are too large to bundle in the plugin.

## Navigation

Each provider directory has an `INDEX.md` — always start there, never read `llms.txt`, `manifest.json`, or `download/` directly.

## Source

[Swordsman/provider-api-library](https://github.com/Swordsman/provider-api-library)
