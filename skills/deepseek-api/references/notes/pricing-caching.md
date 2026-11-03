# User notes: pricing and caching

Measured in live use, not stated in DeepSeek's docs. Each note says when and how it was measured. Where the docs and a note disagree, check both, and re-measure if the note is old.

## Cache granularity: 128-token blocks (measured 2026-11-02)
- All 16 nonzero `prompt_cache_hit_tokens` values logged on 2026-11-01/02 are exact multiples of 128, for example 5,376, 13,184, 13,440, 43,008, 54,528 and 110,464. With 64-token blocks, that happening by chance has odds of about 1 in 65,000.
- The current kv_cache guide states no block size. 2024-era docs said 64.

## First reuse hits only part of a shared prefix (measured 2026-11-01)
- Pro, thinking=max. About 13k tokens of the winnow spec were shared with one earlier request, and 5,376 hit. After a second request had shared it, the next request hit 13,440.
- This fits the docs' rule that a common prefix becomes its own unit only once several requests share it.

## Thinking settings partition the cache (measured 2026-11-01)
- A `thinking=max` call got 0 hits on a prefix that `thinking=auto` calls had cached. The docs say nothing about thinking or effort.
- So treat model plus thinking setting as the cache key.

## Calculated vs measured cost (measured 2026-11-01, off-peak)
- A Pro call with 28,160 cache-hit tokens and 18,075 output tokens calculated to $0.036, and the balance dropped $0.04. The cache-hit part alone was about $0.0006. Output is nearly all the cost.

## Tools
- Joe's winnow `ds` CLI has `--usage-out FILE` for per-turn cost tracking.
