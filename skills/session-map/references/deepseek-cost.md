# DeepSeek cost: measurement and notation

## Policy (Joe, frozen)
- **Dollars only.** Write `$0.0006`, never a fractional-cent form. The double-unit form caused at least one real slip.
- **Cost claims are measured, never asserted (hard rule).**

## What the API reports
- DeepSeek responses carry token counts only, no cost field. Checked on 6 endpoint and stream variants, plus the official docs and change log.
- Cost is the usage fields priced at the published rates, checked against `GET /user/balance`. Rates are in this skill's `scripts/dsx.py` (`RATES`) and in the deepseek-api skill's `references/pricing-caching.md`.
- The balance is reported to the nearest $0.01, and charges post a few minutes late. Polling right after a call shows the old balance.

## Measured (2026-11-01)
- A Pro call with 28,160 cache-hit tokens and 18,075 output tokens was calculated at $0.036, and the balance dropped $0.04.
- The cache-hit part alone was about $0.0006. Output is nearly all the cost.

## Caching
- A full hit happens only on an earlier request's whole prompt, or on a prefix that two earlier requests shared. The first reuse of any other prefix only hits fixed-interval units.
- Calls with different thinking settings do not share cache. A thinking=max call got 0 hits on a prefix cached by thinking=auto calls.

## Tooling (done)
- This skill's `scripts/dsx.py` computes cost per call, keeps a 24h I/O log at `~/.dsx/io.jsonl`, raises cache-miss tripwires, and reconciles against the balance. 11 tests in `test_dsx.py`.
- Joe's winnow `ds` CLI has `--usage-out FILE` for per-turn cost tracking.

## Official caching rules (api-docs.deepseek.com/guides/kv_cache, read 2026-11-01)
- "Each request will produce two cache prefix units at the end position of the user input" (the end of the model output is also named as a boundary).
- "When the system detects a common prefix across multiple requests, it will persist that common prefix as an independent cache prefix unit."
- "For long inputs or long outputs, the system will carve out cache prefix units at fixed token intervals."
- "A subsequent request can only hit the cache if it fully matches a cache prefix unit."
- Cache lifetime: "usually within a few hours to a few days" once unused.
- The page states no limit on how many prefixes are cached, and no minimum size.
- The page says nothing about thinking or effort settings. That different thinking settings never share cache is measured here (2026-11-01), not documented.
