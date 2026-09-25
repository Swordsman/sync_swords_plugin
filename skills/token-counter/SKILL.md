---
name: token-counter
description: Estimate token counts for files and text. Use when you need to know how many tokens a file, code block, or text content contains. Helps with context window management, detecting bloat, and planning token hygiene.
---

# Token Counter

Estimate token counts for content before it enters your context window.

## When to Use

- Before reading large files into context
- When checking if AGENTS.md or other docs are getting too long
- To estimate if a subagent's output will fit in context
- For context budget planning during multi-step tasks

## How to Use

Run the token estimator script:

```bash
python3 .agents/skills/token-counter/scripts/count_tokens.py <file>
python3 .agents/skills/token-counter/scripts/count_tokens.py <file> --max 100
python3 .agents/skills/token-counter/scripts/count_tokens.py --text "your text here"
```

Output shows:
- Character count
- Estimated token count (using ~4 chars/token heuristic)
- Percentage of 26k context window
- Warning if file is large

## Heuristics

- ~4 characters per token (approximation)
- Code tends toward 3-4 chars/token
- English prose tends toward 4-5 chars/token
- This is an estimate, not exact (actual tokenization varies by model)

## Context Budget Guidelines

| Content Size | Action |
|-------------|--------|
| <1k tokens | Safe to read directly |
| 1k-5k tokens | Read if essential, consider summarizing |
| 5k-10k tokens | Use subagent to summarize |
| >10k tokens | Always delegate to subagent |

