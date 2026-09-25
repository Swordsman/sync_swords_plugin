# Models, Pricing, Context Caching, Token Estimation

## Model selection

| | deepseek-v4-flash | deepseek-v4-pro |
|---|---|---|
| Architecture | 284B total / 13B active (MoE) | 1.6T total / 49B active (MoE) |
| Character | Fast, economical; reasoning close to Pro at ~1/10 cost | Top-tier reasoning, rich world knowledge, SOTA agent coding |
| Context / max output | 1M / 384K | 1M / 384K |
| Concurrency limit | 2500 | 500 |
| Input, cache hit (per 1M tokens) | $0.0028 | $0.003625 |
| Input, cache miss | $0.14 | $0.435 |
| Output | $0.28 | $0.87 |

- **[field note]** V4-Pro's listed prices began as a "75%-off launch promo" slated to end 2026-05-31; the promo pricing was made permanent — the table above is current.
- Both models support thinking + non-thinking, JSON Output, tool calls, chat-prefix (Beta); FIM (Beta) is Pro-only, non-thinking.
- Legacy `deepseek-chat` (-> flash non-thinking) and `deepseek-reasoner` (-> flash thinking) retire **2026-07-24**.
- Default choice heuristic **[field note]**: flash for verification/scouting/high-volume; pro for hard reasoning and agentic coding.

## Context caching (automatic, disk-based)

ON by default for every account — zero configuration, no storage fees. Overlapping request **prefixes** are served from cache at the cache-hit input price (up to ~50x cheaper input).

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

## Token estimation

Rough: 1 EN char ~ 0.3 tok, 1 ZH char ~ 0.6 tok. **[field note]** Likely stale for V4; trust `usage` fields from real responses.

## Billing mechanics

Billing: tokens x price. Granted balance consumed first, then topped-up. Balance never expires (topped-up) / may expire (granted). Endpoint: -> `ops-troubleshooting.md`.
