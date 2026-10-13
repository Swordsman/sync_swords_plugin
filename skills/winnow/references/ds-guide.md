# ds — DeepSeek agent / write worker: operational guide

Internal reference for using `ds` effectively within winnow and elsewhere.
The `--help` text covers syntax; this covers the *why* and *when*.

## Models

- **pro** (`-m pro`): Full-power model. Use for critical reasoning, complex multi-step tasks, anything where accuracy matters more than speed.
- **flash** (`-m flash`): Fast, cheap, good enough for most extraction/formatting tasks. Not as smart as pro — don't rely on it for nuanced reasoning. Since 2026-10 this is `deepseek-flash`, DeepSeek-V4.1-Flash; the old `deepseek-v4-flash` name is retired and redirected to it.

## Output tokens: never cap them

Never limit DeepSeek's output (Joe: "max token capping on deepseek is no
bueno"). Thinking tokens count against `max_tokens`, so a cap starves or
truncates the answer. `ds` sends no `max_tokens` unless `--max-tokens` is
given, and refuses values under 100000 with thinking on; leave it unset.
Where an API makes `max_tokens` mandatory (the Anthropic-compatible
endpoint winnow's `deepseek-anthropic` backend uses), send the model's
full output capacity: 393,216 tokens for both flash and pro, per
`/models`.

## Transient glitches are normal

DeepSeek's API has occasional momentary glitches: a call stalls, or fails,
and the same call works seconds later (seen 2026-10-13: three calls hung
for 90 s each, then everything answered in 2 s). One hang is not evidence
of a code bug. Retry once before debugging, and design callers to retry:
winnow's deepseek client retries 3 times with backoff, and littlewing
keeps whatever a winnow run finished before a failure.

## Speed expectations

DeepSeek is fast. A call that hangs is either a transient glitch (see
above: retry once) or a configuration problem — check the arguments if
it hangs again.

- **Non-thinking calls**: typically <2 seconds for normal-sized responses.
- **Thinking calls**: typically <30 seconds. Only exceeds 5 minutes in extreme cases (near-max 1M token context).
- **Timeout**: winnow sends `--timeout 300`, room for max-effort thinking. The timeout is an *idle* timeout — seconds with no data from the API — not a total wall-clock limit. Max is 600 (API hard ceiling).

If a call hangs twice: check the arguments. Common causes are misconfigured thinking/reasoning params that choke the API.

## Streaming

**Always use streaming** (`--stream` is the default; `--no-stream` disables it). Streaming lets you see output arriving in real time, which is essential for diagnosing hangs. With `--no-stream`, a stuck call looks identical to a slow call.

When using `--out FILE`, tokens are flushed to disk as they arrive — use `tail -f FILE` to watch live.

## Thinking mode

`--think` controls reasoning/chain-of-thought:

- **Omit entirely**: API default (thinking on, high effort).
- `--think`: Bare flag = API default thinking.
- `--think off`: No thinking. Fastest.
- `--think low`: Low effort, the fastest thinking.
- `--think high`: Extended thinking.
- `--think max`: Maximum thinking budget.

**winnow always runs at `--think max`** (Joe, 2026-10-13: anything less is a
bad idea). winnow.py sends it by default; don't lower it to save time or
money without Joe's say-so. Run long extractions in the background.

## RE2 (re-reading)

`--re2 {paper,xml}` doubles the task instruction using the RE2 re-reading technique. Key properties:

- **Implies `--think off`** — RE2 is a non-thinking technique.
- Only doubles the *task instruction*, not piped/context content (unless `--re2-context` is also set).
- Trades increased input size for better comprehension on a single pass — nearly as smart as thinking mode but faster.
- Best for tasks that don't need multiple reasoning passes: extraction, formatting, classification, structured output.
- Less useful for tasks requiring iterative/recursive reasoning.

RE2 turns thinking off, so it does not fit winnow's max-effort rule; don't use it for winnow runs unless Joe asks.

## Thinking is on by default

Both pro and flash run reasoning by default — a minimal API call returns
`reasoning_content`. For dense prompts (like winnow's extractor/normalizer)
the reasoning chain can run 1-4 minutes even though the API round trip
itself is ~1.5s. If a call seems slow, it's probably thinking, not stuck:
check with streaming on (`--out FILE` + `tail -f`). At `--think max`,
expect several minutes per dense call.

## Sessions and persistence

`--persist` controls session persistence (context window continuity across calls):

- `--persist no`: Stateless single-shot call. No session file created. **Use this for winnow** — each extractor/normalizer call is independent (the orchestrator passes digest + registry explicitly, so a session would double up context).
- Note: ongoing persistence (`--persist on`/named sessions) has known quirks — Joe: "persist is a bit broken or something." Prefer `--session FILE.jsonl` explicitly or momentary `--persist no`.
- `--persist yes` / bare `--persist`: Creates/continues a session file in `~/.ds/sessions/`.
- `--persist NAME`: Target a named session.
- `--persist off`: Deactivate the current shell's session.

Session management commands: `--list-sessions`, `--resume QUERY`, `--session-info`, `--show-turn N`, `--grep-session PATTERN`, `--fork`.

## Quiet mode

`-q` / `--quiet` suppresses thinking output (sends it to /dev/null). Use when you only want the content output — e.g., when capturing stdout for programmatic use.

## Useful combos for winnow

```bash
# Standard winnow call (what winnow.py sends): max thinking, no output cap
ds --persist no -m flash --timeout 300 --stream -q --think max --system "PROMPT" "INPUT"

# Pro model for critical/complex extraction
ds --persist no -m pro --timeout 300 --stream -q --think max --system "PROMPT" "INPUT"

# Debugging: see what would be sent without calling the API
ds --persist no -m flash --system "PROMPT" "INPUT" --dry-run
```

## Other notable features

- **`--dry-run`**: Shows what would be sent without calling the API. Use to debug argument issues.
- **`--guarantee-json-output`**: Forces valid JSON output. Useful if the model is flaky about output format.
- **`--context FILE`**: Inject file contents into the user message. Repeatable.
- **`--help-me-out "what I want"`**: Meta-feature — ds reads its own help and generates a command for you.
- **`--balance`**: Check DeepSeek account balance.
- **`--alias`**: Save/load argument presets. Could be useful for winnow-specific configs.
- **MCP support**: `--mcp SERVER` connects to MCP servers for tool use. `--max-turns` caps the tool loop.
- **`--usage-out FILE`**: Per-turn cost tracking. `--usage-summary` aggregates across files.

## Fallback: raw API via curl

The `ds` harness needs the `openai` Python module, which fresh
containers may lack (`pip install openai` fixes it; this cost one retry
cycle on 2026-07-20). If ds is unusable, the deepseek-api skill
documents raw HTTPS access — a plain curl POST to the DeepSeek
chat-completions endpoint with `Authorization: Bearer $DEEPSEEK_API_KEY`
works from any container with network access. Same models, no local
dependencies. Joe's suggestion: keep this in mind whenever ds
misbehaves; the harness is a convenience, not a requirement.
