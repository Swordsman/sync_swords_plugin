# Models, Pricing, Context Caching, Token Estimation

Source: api-docs.deepseek.com/quick_start/pricing, 2026-10-13. Prices in USD per 1M tokens.

## Model selection

| | deepseek-flash | deepseek-v4-pro |
|---|---|---|
| Model version | DeepSeek-V4.1-Flash | DeepSeek-V4-Pro-0813 |
| Architecture | 552B MoE, causal encoder–decoder: 8B active for input, 16B for output | 1.6T total / 49B active (MoE) |
| Character | DeepSeek's default; reported ahead of V4-Pro on their benchmarks; faster, ~1/4–1/3 Pro's price | Top-tier reasoning, rich world knowledge, agent coding |
| Input | text + image (`vision.md`) | text only |
| Context / max output | 1M (1048576) / 384K (393216) | 1M (1048576) / 384K (393216) |
| Concurrency limit | 2500 | 500 |

## Pricing (peak / off-peak)

| | deepseek-flash off-peak | deepseek-flash peak | deepseek-v4-pro off-peak | deepseek-v4-pro peak |
|---|---|---|---|---|
| Input, cache hit | $0.003 | $0.006 | $0.022 | $0.044 |
| Input, cache miss | $0.15 | $0.3 | $0.66 | $1.32 |
| Output | $0.6 | $1.2 | $1.98 | $3.96 |

- **Peak hours**: 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday, excluding Chinese public holidays. All other hours are off-peak (half the peak rate), including weekends and Chinese public holidays in full. Schedule flexible batch work off-peak.
- Peak/off-peak pricing began 2026-08-16 16:00 UTC; the V4.1-Flash price cut took effect 2026-09-10 04:00 UTC.
- **Legacy names**: `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are still accepted, but those models are retired: requests are served by DeepSeek-V4.1-Flash and billed at the Flash price.
- **V4-Pro status**: the 2026-09-10 announcement said `deepseek-v4-pro` would route to V4.1-Flash from 2026-09-14; the change log reversed that — V4-Pro keeps being served, billing unchanged, until further notice. `GET /models` still lists it (2026-10-13).
- Both models support thinking + non-thinking, JSON Output, tool calls, Responses API, Anthropic API, chat-prefix (Beta), FIM (Beta, non-thinking only). Vision: flash only.
- Legacy `deepseek-chat` (-> flash non-thinking) and `deepseek-reasoner` (-> flash thinking) passed their announced 2026-07-24 retirement but were still accepted on 2026-10-13 (served as `deepseek-flash`). **[field note]** Don't build on them.
- Default choice heuristic **[field note]**: flash for verification/scouting/high-volume; pro for hard reasoning and agentic coding. Unverified since V4.1 — DeepSeek now positions V4.1 Flash ahead of V4-Pro.

## Context caching (automatic, disk-based)

ON by default for every account — zero configuration, no storage fees. Overlapping request **prefixes** are served from cache at the cache-hit input price (~50x cheaper input on flash, ~30x on pro).

Hit rules — only a FULL match of a persisted "cache prefix unit" hits (Sliding Window Attention; matching starts at token 0):

1. **Request boundaries**: each request persists units at end-of-user-input and end-of-model-output.
2. **Common-prefix detection**: a prefix shared across multiple requests gets persisted as its own unit (request 3 can hit what requests 1+2 merely shared).
3. **Fixed token intervals**: long inputs/outputs get units carved at intervals so long prefixes aren't all-or-nothing.

Properties:

- Best-effort — never guaranteed. Check per-request via `usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` (they sum to `prompt_tokens`).
- Construction takes seconds; unused cache clears after hours-days.
- Per-user isolation; output randomness unaffected (only the prefix is cached, not generations).
- Practical consequence: keep stable content (system prompt, docs) at the FRONT of `messages` and vary only the tail.
- **[field note]** 2024-era docs cited 64-token cache units; may have changed for v4.
- V4.1-Flash's KV cache needs 1/4 the HBM and 1/8 the SSD of the previous generation (DeepSeek, 2026-09-10) — cheaper cache hits for long agent contexts.

## Token estimation

Rough: 1 EN char ~ 0.3 tok, 1 ZH char ~ 0.6 tok (docs). **[field note]** Likely stale for V4; trust `usage` fields from real responses. Images: up to 1024 tokens each (`vision.md`).

## Billing mechanics

Billing: tokens x price (peak or off-peak rate). Granted balance consumed first, then topped-up. Balance never expires (topped-up) / may expire (granted). Endpoint: -> `ops-troubleshooting.md`.
