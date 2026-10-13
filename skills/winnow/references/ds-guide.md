# ds — DeepSeek agent / write worker: operational guide

Internal reference for using `ds` effectively within winnow and elsewhere.
The `--help` text covers syntax; this covers the *why* and *when*.

## Models

- **pro** (`-m pro`): Full-power model. Use for critical reasoning, complex multi-step tasks, anything where accuracy matters more than speed.
- **flash** (`-m flash`): Fast, cheap, good enough for most extraction/formatting tasks. Not as smart as pro — don't rely on it for nuanced reasoning.

## Speed expectations

DeepSeek is fast. If a call is hanging, the configuration is wrong — it is not "thinking hard."

- **Non-thinking calls**: typically <2 seconds for normal-sized responses.
- **Thinking calls**: typically <30 seconds. Only exceeds 5 minutes in extreme cases (near-max 1M token context).
- **Timeout**: `--timeout 120` is generous. The timeout is an *idle* timeout — seconds with no data from the API — not a total wall-clock limit. Max is 600 (API hard ceiling).

If a call hangs: check the arguments. Common causes are misconfigured thinking/reasoning params that choke the API.

## Streaming

**Always use streaming** (`--stream` is the default; `--no-stream` disables it). Streaming lets you see output arriving in real time, which is essential for diagnosing hangs. With `--no-stream`, a stuck call looks identical to a slow call.

When using `--out FILE`, tokens are flushed to disk as they arrive — use `tail -f FILE` to watch live.

## Thinking mode

`--think` controls reasoning/chain-of-thought:

- **Omit entirely**: API default (model decides).
- `--think`: Bare flag = API default thinking.
- `--think off`: No thinking. Fastest.
- `--think high`: Extended thinking.
- `--think max`: Maximum thinking budget.

For winnow extraction/normalization, default (omit `--think`) is fine. The tasks are structured enough that explicit thinking isn't needed.

## RE2 (re-reading)

`--re2 {paper,xml}` doubles the task instruction using the RE2 re-reading technique. Key properties:

- **Implies `--think off`** — RE2 is a non-thinking technique.
- Only doubles the *task instruction*, not piped/context content (unless `--re2-context` is also set).
- Trades increased input size for better comprehension on a single pass — nearly as smart as thinking mode but faster.
- Best for tasks that don't need multiple reasoning passes: extraction, formatting, classification, structured output.
- Less useful for tasks requiring iterative/recursive reasoning.

For winnow: RE2 is a good fit for both the extractor and normalizer since they're doing structured extraction, not open-ended reasoning.

## Thinking is on by default

Both pro and flash run reasoning by default — a minimal API call returns
`reasoning_content`. For dense prompts (like winnow's extractor/normalizer)
the reasoning chain can run 1-4 minutes even though the API round trip
itself is ~1.5s. If a call seems slow, it's probably thinking, not stuck:
check with streaming on (`--out FILE` + `tail -f`). For single-pass
structured tasks, `--re2` (which implies `--think off`) is usually the
better trade.

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
# Standard winnow call (fast, structured extraction)
ds --persist no -m flash --timeout 120 --stream -q --system "PROMPT" "INPUT"

# RE2 variant (slightly smarter non-thinking, doubles input)
ds --persist no -m flash --timeout 120 --stream -q --re2 paper --system "PROMPT" "INPUT"

# Pro model for critical/complex extraction
ds --persist no -m pro --timeout 120 --stream -q --system "PROMPT" "INPUT"

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
