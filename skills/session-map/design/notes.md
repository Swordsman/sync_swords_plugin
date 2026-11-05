# Session map / transcript survival (design note)

Status: built and run (session 32131678, 2026-11-01). The pipeline is in `/home/claude/session-map/`. Still to do: a memory-file pass, and joining the Gemini winnow with `session.wno`.

## Why
- **Joe's constraint (hard): no build without an intent map.** Any build starts from a fully traced purpose tree of the conversation (k26). The intent map was lost to compaction once already, which is what forced the pasted-transcript route.
- DeepSeek is used because it can hold the full transcript and survive compaction.

## Pipeline (capture, convert, process, map, consult)
- **Capture:** copy transcripts before compaction rewrites them (c431). The session JSONL was rewritten and the pre-compaction content lost; keep copies in `/home/claude/transcripts/` (c439). Known killers: a container reboot stops detached processes; a harness reload truncates the transcript (c437 to c438).
- **Convert:** ucf after parsing lines to dicts (`offload.md` item 1). A turn builder is still needed (a39).
- **Process:** `pipeline.py` makes a turn map and a winnow log per segment. `stage2.py` makes arcs and the reconcile report. `dsx.py` is the DeepSeek client (see `references/deepseek-cost.md`).
- **Map:** `session.wno` (the merged winnow log), `arcs.md`, `reconcile.md`, all in `/home/claude/session-map/out/`.
- **Consult:** the map is what future turns read instead of the raw transcript.

## Segmentation (Joe: "just do whatever makes sense")
- Segment 1: nothing prepended.
- Segment 2: a note that its compaction summary is lost.
- Segment 3: rebuilt from the live session file with speaker labels, with the second compaction summary prepended.
- The pastes: paste1 is near-empty (copying from the shared-chat viewport gave a partial transcript, c441 to c442); paste2 is the full conversation in order, with tool summaries (c443 to c444); attach3 is the Gemini log about compaction and handoffs (c445).

## Turn maps
- One sentence per turn, using Joe's verbatim prompt from the Gemini log.
- Turn-boundary check: Flash and Pro agreed on segment 1, with 48 exchanges against 97 turns. Two runs produce the same boundaries; identical wording must not be asked for (c455 to c456).
- Captures u-shaped attention (first and last turns) and anchors recall (c450 to c451).
- Open: does this achieve every-turn capture (q66)?

## Winnow run settings (Joe's)
- Winnows run on Pro with thinking at max effort, no max_tokens, and an empty system prompt.
- The full winnow spec goes first in the user prompt, so it caches across calls.
- Join via winnows, not raw text.

## Fixes the validator (`fold.py`) forced
- Code closes unbalanced forms, and wraps bare frames in `add:` (one log had 520).
- Semantic problems go back to DeepSeek together with `fold.py`'s report.

## 2026-11-04/05: compaction check and message agents (working copies in /home/claude/session-map)

- compaction_check.py: code flags absent identifiers, Jev Score 0-3 per message (3 planted controls per request),
  DeepSeek Flash thinking off then on with byte-identical prompts (Joe's framing as system prompt; INTRO/DEFINITIONS/
  LOG/SUMMARY/FLAGS/TASK; RE2). s2 test (568 blocks): Jev flagged 177; off found 150 lost (Jev had 148); on found 56
  and called 88 Jev flags covered; spot check of 6 off-only items: 4 real drops. On alone found the one real
  contradiction (criterion axis came from Paul & Elder research, not the collision test).
- Harness rewrites the session JSONL at compaction: the source log must be snapshotted before (PreCompact hook that
  only copies — proposed, awaiting Joe). Joe: script first, hook once proven; DeepSeek writes the final list.
- Open: final-list composition (on ∪ off-only-and-Jev≥2, or a third DeepSeek pass on off-only items).
- dsx fixes: thinking=off sends max_tokens=393216 (unset default stops at 8192); finish_reason=length raises
  TruncatedError after logging; persisted_prefix is linear (property-tested against the pairwise version); the log is
  read incrementally and written under a lock; shingles memoized; sqlite timeout 60s.
- msgagents.py: message agents on the dsx tree. system prompt -> [payload + prefilled ack] -> agent message ->
  prefilled ack (agent id) -> questions fork (trunk never grows). Agent table: parent_agent, status, superseded_by.
  broadcast() warms 2 calls then runs parallel; per-agent failures collected (BroadcastError). Shared payload goes
  BEFORE the agent's message so it caches once (measured: 7552 of ~8.2k prompt tokens hit per call).
- agent_check.py: the compaction check by message agents (SCORE + LOST per agent). 20-agent trial: controls 0/0/3.
- 2026-11-05 NLI ablation (/home/claude/ablation, pairs from gau's original_transcript_lazy_rip.txt): 151 built pairs
  (verbatim/paraphrase = supports, one-fact edit = contradicts, far sentence = neutral) + 40 real pairs labeled by
  DeepSeek Pro max (spot-checked: disagreements are genuinely ambiguous pairs). Built: DeepSeek Flash 150, Jev 147,
  ModernBERT 139. Real: DeepSeek 37, Jev 35, ModernBERT 26. NLI added as filter or vote: no accuracy gain. NLI
  confident >= 0.95 settled 80 pairs with 0 errors, so it is a safe free prefilter; worth it only at volume.
  Costs: Jev $0.0024 (191 pairs, 2 requests), Flash $0.04, Pro labels $0.13.
- 2026-11-05 decomposition test: DeepSeek Flash split the 40 real pairs into resolved atoms ($0.03). ModernBERT got
  WORSE: raw 26/40 -> atoms with premise joined 22/40 -> best single premise atom 9/40. The unrelated->contradiction
  bias fires per atom comparison and "any atom contradicted" amplifies it (19 of 25 neutrals became contradictions).
  The decomposition also had defects: references left unresolved ("picks this up without that framing"), an
  either/or split into two independent claims. A code rule (contradiction only if premise and hypothesis share >= 2
  content words) fixes built pairs (139 -> 146) but not real ones (26): those errors are missed inferential support.
  Verdict: the model is the limit. Decomposition quality needs its own check (Jev, not NLI).
