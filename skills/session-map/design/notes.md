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
