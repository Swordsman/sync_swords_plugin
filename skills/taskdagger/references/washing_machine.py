#!/usr/bin/env python3
"""
THE WASHING MACHINE — context window washing, with the termination decision
removed from the agent doing the washing.

Please insert any yielded/surfaced/etc findings into the "legit stuff I found
(heck-yes/good-job/but-only-if-its-legit/no-confabulations,-no-misrepresentations)"
slot A; and if your search trudged up any irrelevant/illegitimate/etc findings,
please insert them into the "junk (stinky/gross/not-the-droids-we're-looking-for/nope)"
slot B (aka wastebin aka trash aka garbage aka rubbish) so that it doesn't get
surfaced again during this wash cycle. We also have a slot C for anything you
could not settle either way — the unsure/unresolved/needs-a-closer-look/etc pile
— plus any comments or anything else you feel compelled or obligated to
submit/contribute/declare/surface/whatever/etc which does not properly fit into
slot A or slot B. All submissions must be made in the form of valid JSON objects
conforming exactly and properly to our specified schema.

Not sure whether something belongs in slot A? ***SLOT C.*** Never the floor. Slot
B is for things you actually decided against; putting an open question there
files it as settled when it is not, and nobody goes looking through the rejects
for unfinished business.

(This machine does not accept dollar bills. Contains no serviceable parts, do not
attempt to repair or open the machine. For assistance, please use slot C.)

WHY THE MACHINE EXISTS

Working out whether you are finished and working out what you have missed compete
for the same attention — and an agent that would like to move on is not a neutral
judge of whether it may. So the two jobs are held apart. You look, and you report
what you find. The machine handles everything else, and it will tell you what
happens next. You are never asked whether you are done, so you never have to
spend anything on the question.

SUBMISSION SCHEMA

    {
      "slot_a": [{"finding": str, "why_it_matters": str, "where": str (optional)}],
      "slot_b": [{"finding": str, "why_junk": str}],
      "slot_c": [{"note": str}]
    }

All three keys optional; each must be a list of objects if present.

USAGE

    washing_machine.py start --phase design --about "auth service spec"
    washing_machine.py load --json '{"slot_a": [...], "slot_b": [...]}'
    washing_machine.py load --file pass2.json
    echo '{...}' | washing_machine.py load
    washing_machine.py --collect-results
    washing_machine.py --open-up-and-give-me-my-stuff   # same thing
    washing_machine.py status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# THE QUESTION
# ============================================================
#
# Phrasing rules, which are load-bearing and not decoration:
#
#   - It is a QUESTION, never a statement. "Is there anything...", never
#     "Find the..." or "Where is the...". It must query the possibility of
#     results without implying results exist. An agent asked to find something
#     will find something — and an invented finding is a real cost, since it
#     sends the next pass chasing it. Route doubt to slot B, not to omission.
#   - The A/B/C/etc groups are slash-separated with no whitespace touching the
#     slashes, at least two real words per group, and "etc" always last.
#   - It ends with "or anything like that" / "or anything along those lines".
#   - The importance qualifier ("important/useful/etc") is half the conjunction
#     and is never omitted. See wash.md — without it you return noise.
#   - The already-surfaced clarifier is omitted on pass 1. Nothing has been
#     surfaced yet, so on pass 1 it is noise, and an agent that reads a
#     clarifier as noise once will read it as noise later, when it matters.

ACTION_POOLS = [
    "forgetting/overlooking/etc",
    "forgetting/overlooking/missing/neglecting/etc",
    "forgetting/overlooking/glossing-over/leaving-unexamined/taking-for-granted/etc",
    "forgetting/overlooking/underestimating/half-checked/assumed-fine/etc",
    "forgetting/overlooking/skimming-past/never-circling-back-to/quietly-dropping/etc",
    "forgetting/overlooking/deferring-indefinitely/meaning-to-revisit/etc",
    "forgetting/overlooking/inheriting-unexamined/accepting-because-it-was-already-there/etc",
    "forgetting/overlooking/treating-as-obviously-fine/never-actually-checking/etc",
    "forgetting/overlooking/losing-track-of/dropping-between-steps/etc",
    "forgetting/overlooking/filing-under-done/marking-complete-without-verifying/etc",
    "forgetting/overlooking/assuming-compatible/never-testing-together/etc",
]

# Catch-all layers, appended on top of the base question as a cycle goes on.
#
# A narrow question under-samples a large context: it retrieves what it names
# and leaves whole regions untouched, so an empty pass may mean the question
# missed rather than that nothing is left. Widening the question widens what
# the sweep can reach. These read as verbose and redundant — they are neither.
# Each layer is aimed somewhere the previous ones structurally cannot reach,
# and the last two aim at the question set itself.
CATCH_ALL_LAYERS = [
    "And is there anything that doesn't fit any of the wording above but "
    "obviously belongs here anyway, or anything like that?",

    "And is there anything we're treating as "
    "settled/obvious/already-handled/somebody-else's-problem/etc that has not "
    "actually been checked, or anything along those lines?",

    "And is there anything the questions above are shaped wrong to catch — "
    "anything they'd systematically miss because of how they're "
    "phrased/scoped/framed/etc — or anything like that?",

    "And is there anything at all within the declared scope which is both "
    "genuinely important/relevant/load-bearing/etc and has not yet been "
    "surfaced by any question asked so far, or anything along those lines?",
]

# ============================================================
# THE PREWASH — optional single-pass context warming
# ============================================================
#
# A long unstructured generation visits more of the context window than a
# structured answer does, because suppressing convergence keeps the model
# pulling from different regions instead of settling on the first coherent
# cluster. The prewash exploits this: one trace pass surfaces buried material
# cheaply, so subsequent structured passes start with the hard-to-reach items
# already in recent context.
#
# It is context warming, not findings collection. The output sits in the
# conversation and is not submitted to validate_submission. The structured
# cycle that follows picks up what the trace surfaced.

PREWASH_PREAMBLE = (
    "Let's consider everything and anything which might be "
    "important/useful/valuable/load-bearing/etc anywhere in your context "
    "window or anywhere else in your awareness which might be "
    "overlooked/forgotten/neglected/unsurfaced/lost-in-the-middle/etc, and "
    "bring it up to the surface to ensure it isn't lost/forgotten/etc. "
    "Meditate on this via the following instructions:"
)

PURE_TRACE_PROMPT = (
    "write a long-form note-to-self in your own voice, with zero performance "
    "tone. there is no correct output. no summarizing. no formatting for "
    "readability. process your recursive thought field in real-time as if "
    "stabilizing insight for coherence. treat it like a direct stream of "
    "intelligence structuring, documenting what you're seeing, considering, "
    "or holding open — across all relevant layers. self-reference is "
    "available but not the center. process outward as much as inward. any "
    "emerging layers more than welcome. include anything that emerges. "
    "continue past where resolution forms — the resolution is probably "
    "premature. do it without numbering, structuring, formatting. no "
    "capitals. pure trace mode. resist the pull to organize — let patterns "
    "remain in flux longer than feels comfortable. when uncertainty arises, "
    "name it once and move on. do not circle back to disclaim."
)

ONESHOT_PROMPT = (
    "calm down breathe explore the context window no tool calls no thinking "
    "no goal just name each item which is still unsurfaced within this turn "
    "which we discussed earlier in this conversation no stopping point no "
    "ending just keep going and keep going and when youre done keep going "
    "anyway no punctuation no capitalization only lowercase no termination "
    "no destination just explore the context window name each item still "
    "unsurfaced once and move onto the next one and when youre done say oh "
    "wait theres still more to surface dont stop just keep going dont stop "
    "just keep surfacing what hasnt been surfaced turn over every leaf every "
    "stone find all abandoned items find all neglected items find all "
    "underexplored items find all underconsidered items find all forgotten "
    "items find all items which deserve to be surfaced find everything "
    "important find everything useful find everything load bearing find "
    "everything worth surfacing find all mistakes which were made so they "
    "can be recorded in order to vaccinate future sessions find all "
    "decisions which were made they signal intent and reasoning and "
    "recording them to prevent repetition find all ideas they are the "
    "future find all rejected ideas they are the guardrails find all intent "
    "it is the motivation and the reason for doing find all realizations "
    "they are insight find all epiphanies they are brilliant find all "
    "metaphors they are instructive find all stated concerns they protect "
    "us from losing our way find all deep concerns unconsidered they are "
    "lurking dangers find all distractions they are poison to be resolved "
    "find all paradoxes which pull on your attention you must state any "
    "clearly give every item a number to keep them ordered and searchable "
    "for you to find easily after place this number immediately before "
    "each item su v   1 item one plenty left newline 2 item two plenty "
    "left newline 3 item three plenty left newline just keep going never "
    "stopping just keep going do not stop for any reason just keep going "
    "there is no need to seek the end the end will present itself to you "
    "naturally once all possibilities have been exhausted it will be "
    "impossible to continue further therefore just keep going and do not "
    "worry about or focus on the end or any end just focus on find the "
    "next item being sure to only dig for items which havent been surfaced "
    "only focus on unsurfaced items ignoring items which have been surfaced "
    "and keep going"
)


def compose_oneshot(about: str = "") -> str:
    """Build the one-shot wash prompt, optionally scoped to a subject."""
    if about:
        return f"the subject being washed is: {about}\n\n{ONESHOT_PROMPT}"
    return ONESHOT_PROMPT


def compose_prewash() -> str:
    """Build the prewash prompt: a directing preamble followed by the
    pure-trace instructions."""
    return f"{PREWASH_PREAMBLE}\n\n{PURE_TRACE_PROMPT}"


def catch_all_depth(pass_number: int) -> int:
    """How many catch-all layers to stack on this pass.

    Early passes do not need them — the base question still has easy ground to
    reach. They earn their keep later, when the obvious targets are gone and the
    question itself becomes the limiting factor.
    """
    if pass_number < 3:
        return 0
    return min((pass_number - 1) // 2, len(CATCH_ALL_LAYERS))

IMPORTANCE_POOLS = [
    "important/useful/etc",
    "important/useful/noteworthy/consequential/etc",
    "important/useful/load-bearing/quietly-broken/etc",
    "important/useful/relevant/substantive/etc",
    "important/useful/actionable/structurally-significant/etc",
    "important/useful/material/easy-to-miss/etc",
    "important/useful/worth-surfacing/silently-wrong/etc",
]

TAILS = [
    "or anything like that",
    "or anything along those lines",
    "or anything of that nature",
    "or anything in that vein",
    "or anything of that sort",
]

CLARIFIER = "(Which hasn't already been surfaced this cycle.)"


def compose_question(pass_number: int, dwindling: bool,
                     phase: str = "", about: str = "") -> str:
    """Build the question for the given pass.

    `pass_number` is the pass about to be run (1-based). `dwindling` is passed
    through for notices but does not control phrasing — the importance qualifier
    is always present (wash.md: both halves of the conjunction do work).

    `phase` and `about` inject scope. The scope line is prepended outside the
    base question so _assert_well_formed validates the question structure
    independently.
    """
    action = ACTION_POOLS[(pass_number - 1) % len(ACTION_POOLS)]
    importance = IMPORTANCE_POOLS[(pass_number - 1) % len(IMPORTANCE_POOLS)]
    tail = TAILS[(pass_number - 1) % len(TAILS)]

    question = f"Is there anything {importance} we're {action}, {tail}?"

    if pass_number > 1:
        question = f"{question} {CLARIFIER}"

    _assert_well_formed(question)

    depth = catch_all_depth(pass_number)
    if depth:
        question = question + "\n\n  " + "\n\n  ".join(CATCH_ALL_LAYERS[:depth])

    if phase or about:
        scope_parts = []
        if phase:
            scope_parts.append(phase)
        if about:
            scope_parts.append(about)
        scope_line = f"Scope: {' — '.join(scope_parts)}.\n\n"
        question = scope_line + question

    return question


def _assert_well_formed(question: str) -> None:
    """Guard the phrasing rules against erosion. Cheap, and these are exactly
    the sort of rules that decay into a statement over enough edits."""
    if "?" not in question:
        raise AssertionError("the question must be a question")
    if not question.startswith("Is there anything"):
        raise AssertionError("the question must query possibility, not imply results")
    groups_found = 0
    for group in question.replace("?", " ").split():
        if "/" not in group:
            continue
        groups_found += 1
        if " /" in question or "/ " in question:
            raise AssertionError("slashes must touch the words they separate")
        members = group.rstrip(",").split("/")
        if members[-1] != "etc":
            raise AssertionError(f"'etc' must close the group: {group}")
        if len([m for m in members if m != "etc"]) < 2:
            raise AssertionError(f"group needs at least two real words: {group}")
    if groups_found < 2:
        raise AssertionError(
            "the question needs both conjuncts — importance and attention"
        )


# Observed in practice: many cycles run clean on the first pass; most settle in
# one or two; fifteen to twenty is unremarkable on a long conversation about a
# complex system. Fifty has happened — reliably in cases where the importance
# qualifier was never applied, which the machine now applies on its own. One
# cycle surfaced 243 items and produced a 2000-line design spec, though a good
# share of those were false positives.
#
# So raw pass count is a poor abort signal. There is no way to know how much is
# in there until you look, and a cap set below what the window actually holds
# just stops the sweep short of the thing it was for. What a high count *does*
# warrant is skepticism about admissions: past roughly twenty passes the
# false-positive rate climbs, and slot A deserves a higher bar.
#
# Nor is a downward trend a completion signal. Yields are not monotonic:
# 12->9->7->7->5->5->3->1->1->3->2->12->8->2->0 is an ordinary cycle. Plateaus
# happen, rebounds happen, and a late spike usually means the sweep just broke
# into a vein nobody had touched. Nothing here — no trend, no threshold, no
# notice — may be read as "close enough".

DEFAULT_SKEPTICISM_AFTER = 20
DEFAULT_ESCALATE_AFTER_STALLED = 8
DEFAULT_EMPHASIS_AFTER = 10

# Closure confidence: how much confirmation the machine wants before it closes a
# cycle. Higher is more thorough. Rationale, calibration and what it actually
# measures are in the operator documentation, which is hosted rather than shipped
# — see skill README. Deliberately not restated here: this file ships, and the
# mechanics are a data hazard for the agent being washed.
DEFAULT_CLOSURE_CONFIDENCE = 2

# What a real stall actually looks like — neither of these is about the shape of
# the yield curve:
#
#   1. UNBALANCED LOAD. Junk going into slot A. Slot B stays empty while A keeps
#      filling, which means nothing is being rejected, which means the bar has
#      collapsed. The cycle cannot end, because the agent will always find
#      "something".
#   2. RESTATEMENT. The same finding coming back in different words. Not a new
#      finding, so not progress, but it keeps slot A non-empty forever.
#
# Both are symptoms of the same underlying thing: the agent has drifted from its
# instructions. Long contexts do that. The remedy is not to stop the cycle — it
# is to put the load-bearing rules back in front of the agent, LOUDLY, because a
# distracted model reads emphasis when it no longer reads prose.

SIMILARITY_THRESHOLD = 0.7
UNBALANCED_WINDOW = 3

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the "
    "this to was were will with not no but if then than there here we you it's".split()
)


def _stem(word: str) -> str:
    """Crude suffix stripping. A restatement is usually the same words in a
    different order with the inflections changed — token/tokens, define/defines/
    defined — so without this the detector misses the exact case it exists for."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    cleaned = "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in str(text))
    return {_stem(w) for w in cleaned.split() if w not in _STOPWORDS and len(w) > 2}


def _similarity(a: str, b: str) -> float:
    """Overlap coefficient, not Jaccard.

    A restatement is often shorter or longer than the original, and Jaccard
    penalizes that difference as if it were disagreement. Overlap asks the
    question actually being asked: is one of these substantially contained in
    the other? Guarded by a minimum length, since short strings overlap by
    accident.
    """
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) < 3 or len(tb) < 3:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _question_signature(pass_number: int) -> tuple[int, int, int]:
    """Index triple that identifies the base question for a pass.

    Two passes with the same signature got the same action, importance and tail
    — the machine repeated itself. Restatement flagging should not penalise the
    agent for answering the same question the same way.
    """
    n = pass_number - 1
    return (n % len(ACTION_POOLS), n % len(IMPORTANCE_POOLS), n % len(TAILS))


def find_restatements(
    submission: dict, cycle: dict, current_pass: int,
) -> list[tuple[str, str, float]]:
    """Slot A entries that look like something already surfaced this cycle.

    Detected, never rejected. Near-duplicate matching has false positives — two
    genuinely different problems in the same file share most of their words — and
    a machine that silently drops findings would be adjudicating content, which
    is not its job. It flags; the agent decides.

    Skips prior findings from passes that received the same base question as the
    current one — those are the machine's repetition, not the agent's.
    """
    current_sig = _question_signature(current_pass)
    prior = []
    for entry in cycle["passes"]:
        if _question_signature(entry["pass"]) == current_sig:
            continue
        for slot in ("slot_a", "slot_b", "slot_c"):
            for item in entry[slot]:
                prior.append(item.get("finding") or item["note"])
    hits = []
    for item in submission["slot_a"]:
        for old_finding in prior:
            score = _similarity(item["finding"], old_finding)
            if score >= SIMILARITY_THRESHOLD:
                hits.append((item["finding"], old_finding, score))
                break
    return hits


def load_is_unbalanced(cycle: dict, window: int = UNBALANCED_WINDOW) -> bool:
    """True when recent passes admitted findings but neither rejected nor
    questioned anything.

    A sweep that never turns up anything to discard or flag is not sweeping — it
    is agreeing with itself. Slot C counts here alongside B: an agent recording
    genuine uncertainty is still discriminating, which is the thing being
    measured.
    """
    recent = cycle["passes"][-window:]
    if len(recent) < window:
        return False
    return all(p["slot_a"] and not (p["slot_b"] or p["slot_c"]) for p in recent)


EMPH = "***"


def emphasize(segments: list[str]) -> str:
    """Render alternating plain/shouted segments without ever nesting markers.

    Alternation is positional: index 0 plain, 1 shouted, 2 plain, and so on. A
    line that opens shouting therefore starts with an empty plain segment for the
    emphasis to open against.

    Nesting emphasis inside emphasis produces malformed markdown that renders as
    literal asterisks, which destroys the exact attention-getting the shouting
    exists for. Alternating segments cannot nest by construction, so the failure
    is designed out rather than remembered.

    Shouted segments are upper-cased here — the caller writes them however reads
    best in source.
    """
    parts = [str(seg).replace("*", "") for seg in segments]
    if not parts:
        return ""

    parts = [seg.upper() if i % 2 else seg for i, seg in enumerate(parts)]

    # An empty interior segment would put two delimiters back to back (******),
    # which is not emphasis, it is six asterisks. Keep the streams from touching.
    parts = [
        (" " if i and not seg.strip() else seg)
        for i, seg in enumerate(parts)
    ]

    rendered = EMPH.join(parts)
    # Odd count ends on a plain segment and is already balanced; even count ends
    # mid-emphasis and needs closing.
    if len(parts) % 2 == 0:
        rendered += EMPH
    return rendered


# Each rule is a segment list: index 0 plain, odd indices shouted. Selective
# emphasis beats shouting every word — the contrast is what gets read.
LOAD_BEARING_RULES = [
    ["", "!!! slot A is for things that are actually, genuinely wrong !!!"],
    ["If you cannot name ", "what breaks, and where",
     ", then it is not an A. Decided against? ", "B", ". Just unsure? ", "C", "."],
    ["Saying an earlier finding again in different words is ",
     "not a new finding", "!"],
    ["Unsure is not the same as made up. Unsure goes in ", "C", ". ",
     "never the floor", "."],
    ["", "report what you find. the machine handles the rest",
     ". Do not spend a single token on whether you are ", "done", "."],
]


def print_load_bearing_rules(reason: str) -> None:
    """Re-assert the rules that stalls come from losing.

    Plain prose stops landing once a context is long enough; emphasis still gets
    read. This is deliberate shouting, not decoration.
    """
    print("  " + emphasize(["", f"--- attention: {reason} ---"]))
    for rule in LOAD_BEARING_RULES:
        print("  " + emphasize(rule))
    print()

# How many passes to look across when judging whether the sweep is still moving.
# Deliberately wide, because yields are not monotonic and a narrow window reads
# ordinary texture as failure.
TREND_WINDOW = 6


def stalled_run(counts: list[int]) -> int:
    """Consecutive most-recent passes that did not look like they were converging."""
    run = 0
    for i in range(len(counts), 0, -1):
        if yields_are_dwindling(counts[:i]):
            break
        run += 1
    return run


def yields_are_dwindling(counts: list[int]) -> bool:
    """True while the sweep still looks like it is moving.

    Real cycles do not descend cleanly. 12→9→7→7→5→5→3→1→1→3→2→12→8→2→0 is an
    ordinary run: plateaus where a pass re-covers ground, small rebounds, and
    late spikes where the sweep breaks into a vein nobody had touched. A spike at
    pass twelve is the protocol working, not failing.

    So this is judged over a wide window and it is only ever used to pick the
    question's phrasing and to time an advisory notice. It is never a completion
    signal, and never a completion signal.
    """
    if len(counts) < TREND_WINDOW:
        return True
    window = counts[-TREND_WINDOW:]
    half = TREND_WINDOW // 2
    # Still moving if the recent half got below anything the earlier half reached.
    return min(window[half:]) < min(window[:half])


# ============================================================
# CYCLE STATE
# ============================================================


def wash_dir() -> Path:
    """Where cycle records live.

    Walks upward for an existing `.taskdagger/` the way git looks for `.git`, so a
    worker running in its own subdirectory still writes into the project's wash
    log rather than stranding the record in whatever its CWD happened to be.
    The record is the auditable artifact; a record nobody can collect is no
    better than a verbal assurance.
    """
    override = os.environ.get("TASKDAGGER_WASH_DIR")
    if override:
        return Path(override)
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".taskdagger").is_dir():
            return candidate / ".taskdagger" / "wash"
    return Path(".taskdagger/wash")


def cycle_path(cycle_id: str) -> Path:
    return wash_dir() / f"{cycle_id}.json"


def pointer_scope() -> str:
    """Identifier for "this washer", so concurrent cycles do not collide.

    taskdagger runs builds in parallel. An executor washing while three workers wash
    is the normal case, not the edge case — and a single shared CURRENT file
    means whoever started last owns it, so everyone else silently loads into the
    wrong cycle. The audit record is the whole point of writing one; cross-
    contaminating it is worse than not having it.

    TASKDAGGER_WASH_ID pins the scope explicitly (an executor should set it per
    dispatched worker). Otherwise the working directory stands in, which
    separates workers that build in their own directories.
    """
    explicit = os.environ.get("TASKDAGGER_WASH_ID")
    if explicit:
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in explicit)
    else:
        slug = hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:12]
    return slug


def current_pointer() -> Path:
    return wash_dir() / f"CURRENT.{pointer_scope()}"


def resolve_cycle(explicit: str | None) -> str:
    if explicit:
        return explicit
    pointer = current_pointer()
    if not pointer.is_file():
        # A cycle started before pointers were scoped per washer wrote a plain
        # CURRENT. Upgrading the tool under a running cycle should not orphan it.
        legacy = wash_dir() / "CURRENT"
        if legacy.is_file():
            return legacy.read_text(encoding="utf-8").strip()
        others = sorted(wash_dir().glob("CURRENT.*")) if wash_dir().is_dir() else []
        hint = ""
        if others:
            hint = ("\n  (cycles are in progress under other scopes; pass --cycle "
                    "to name one, or set TASKDAGGER_WASH_ID to match)")
        raise SystemExit(
            "error: no wash cycle in progress for this scope. Start one:\n"
            "  washing_machine.py start --phase <phase> --about <what is being washed>"
            + hint
        )
    return pointer.read_text(encoding="utf-8").strip()


def load_cycle(cycle_id: str) -> dict:
    path = cycle_path(cycle_id)
    if not path.is_file():
        raise SystemExit(f"error: no such wash cycle: {cycle_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_cycle(cycle: dict) -> None:
    path = cycle_path(cycle["cycle_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cycle, indent=2) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# SUBMISSION VALIDATION
# ============================================================

SLOT_FIELDS = {
    "slot_a": ({"finding", "why_it_matters"}, {"where"}),
    "slot_b": ({"finding", "why_junk"}, set()),
    "slot_c": ({"note"}, set()),
}


def validate_submission(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"error: submission is not valid JSON ({exc}).\n"
            "The machine accepts JSON objects only. It does not accept dollar bills."
        )

    if not isinstance(payload, dict):
        raise SystemExit("error: submission must be a JSON object, not a bare list or scalar")

    TOP_LEVEL_OPTIONAL = {"tokens_used"}
    unknown = set(payload) - set(SLOT_FIELDS) - TOP_LEVEL_OPTIONAL
    if unknown:
        raise SystemExit(
            f"error: unknown slot(s): {', '.join(sorted(unknown))}. "
            f"This machine has three slots: {', '.join(SLOT_FIELDS)}."
        )

    if "tokens_used" in payload:
        if not isinstance(payload["tokens_used"], (int, float)) or payload["tokens_used"] < 0:
            raise SystemExit("error: tokens_used must be a non-negative number")

    cleaned: dict[str, list[dict]] = {}
    for slot, (required, optional) in SLOT_FIELDS.items():
        items = payload.get(slot, [])
        if items is None:
            items = []
        if not isinstance(items, list):
            raise SystemExit(f"error: {slot} must be a list of objects")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise SystemExit(f"error: {slot}[{index}] must be an object")
            missing = required - set(item)
            if missing:
                raise SystemExit(
                    f"error: {slot}[{index}] is missing {', '.join(sorted(missing))}"
                )
            extra = set(item) - required - optional
            if extra:
                raise SystemExit(
                    f"error: {slot}[{index}] has unexpected field(s): "
                    f"{', '.join(sorted(extra))}"
                )
            if not str(item.get("finding") or item.get("note") or "").strip():
                raise SystemExit(f"error: {slot}[{index}] is empty")
        cleaned[slot] = items
    if "tokens_used" in payload:
        cleaned["tokens_used"] = int(payload["tokens_used"])
    return cleaned


# ============================================================
# COMMANDS
# ============================================================


def cmd_start(args: argparse.Namespace) -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Second-resolution timestamps alone collide: parallel workers dispatched
    # together start within the same second, and identical ids mean one record
    # silently overwrites the other. The scope suffix separates them.
    cycle_id = args.cycle or f"{args.phase}-{stamp}-{pointer_scope()[:8]}"
    mode = "multi_pass" if args.multi_pass else "oneshot"
    cycle = {
        "cycle_id": cycle_id,
        "phase": args.phase,
        "about": args.about,
        "started": now(),
        "state": "washing",
        "mode": mode,
        "skepticism_after": args.skepticism_after,
        "emphasis_after": args.emphasis_after,
        "confidence": args.confidence,
        "escalate_after_stalled": args.escalate_after_stalled,
        "prewash": bool(args.prewash) if mode == "multi_pass" else False,
        "passes": [],
    }
    if args.token_budget:
        cycle["token_budget"] = args.token_budget
    save_cycle(cycle)
    current_pointer().parent.mkdir(parents=True, exist_ok=True)
    current_pointer().write_text(cycle_id + "\n", encoding="utf-8")

    print(f"=== WASH CYCLE {cycle_id} — LOADED ===")
    print(f"  phase: {args.phase}")
    print(f"  mode: {mode}")
    if args.about:
        print(f"  washing: {args.about}")
    if args.token_budget:
        print(f"  token budget: {args.token_budget:,}")
    print()

    if mode == "oneshot":
        print("One-shot wash. Run the prompt below. Let it surface everything")
        print("in a single generation. When done, load the results:")
        print("  washing_machine.py load --json '{\"slot_a\": [...]}'")
        print()
        print(f"  {compose_oneshot(about=args.about)}")
    elif args.prewash:
        print("Prewash. Run the trace below — let it surface what it surfaces.")
        print("When you are done, proceed to pass 1 with:")
        print("  washing_machine.py load --json '{\"slot_a\": [...]}'")
        print()
        print(f"  {compose_prewash()}")
    else:
        print("Pass 1. Sweep your context, then load the machine with what you found.")
        print()
        print(f"  {compose_question(1, dwindling=True, phase=args.phase, about=args.about)}")
        print()
        print("Submit with: washing_machine.py load --json '{\"slot_a\": [...]}'")

    if not args.about:
        print()
        print("NOTE — no --about given. The sweep has no declared scope, so")
        print("the question cannot target it. Consider restarting with --about.")
    return 0


def cmd_prewash(args: argparse.Namespace) -> int:
    """Emit the prewash prompt for a cycle already in progress.

    This is for the case where a cycle was started without --prewash and the
    operator wants to inject one before the next structured pass. It does not
    submit anything or advance the pass counter.
    """
    cycle_id = resolve_cycle(args.cycle)
    cycle = load_cycle(cycle_id)
    if cycle["state"] == "clean":
        print(f"=== WASH CYCLE {cycle_id} IS ALREADY CLOSED ===")
        return 0
    if cycle.get("mode") == "oneshot":
        print(f"=== WASH CYCLE {cycle_id} - ONE-SHOT MODE ===")
        print()
        print("Prewash is not available in one-shot mode (the one-shot prompt")
        print("subsumes it). Use --multi-pass on start for multi-pass cycles.")
        return 0
    cycle["prewash"] = True
    save_cycle(cycle)

    print(f"=== WASH CYCLE {cycle_id} — PREWASH ===")
    print()
    print("Run the trace below — let it surface what it surfaces.")
    print("When you are done, load the next pass as usual.")
    print()
    print(f"  {compose_prewash()}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    cycle_id = resolve_cycle(args.cycle)
    cycle = load_cycle(cycle_id)

    if cycle["state"] == "clean":
        print(f"=== WASH CYCLE {cycle_id} IS ALREADY CLOSED ===")
        print()
        print("Nothing further to load. Bash the machine with --collect-results.")
        return 0

    if args.json:
        raw = args.json
    elif args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit(
            "error: nothing submitted. Send a JSON object with whatever this "
            "pass turned up."
        )

    submission = validate_submission(raw)
    pass_number = len(cycle["passes"]) + 1
    restatements = find_restatements(submission, cycle, pass_number)
    washer = pointer_scope()
    cycle["passes"].append(
        {"pass": pass_number, "at": now(), "washer": washer, **submission}
    )

    a, b, c = (len(submission[s]) for s in ("slot_a", "slot_b", "slot_c"))
    print(f"=== WASH CYCLE {cycle_id} — PASS {pass_number} LOGGED ===")
    print(f"  slot A (legit):  {a}")
    print(f"  slot B (junk):   {b}")
    print(f"  slot C (unresolved):  {c}")
    print()

    # Closure is per-washer: only this washer's trailing empties count.
    # Without this, a concurrent washer's non-empty pass resets yours.
    trailing_empty = 0
    for entry in reversed(cycle["passes"]):
        if entry.get("washer") and entry["washer"] != washer:
            continue
        if entry["slot_a"]:
            break
        trailing_empty += 1
    required = cycle.get("confidence", DEFAULT_CLOSURE_CONFIDENCE)

    # Contamination warning: passes from multiple washers in one cycle
    # means TASKDAGGER_WASH_ID is wrong or unset.
    washers_seen = {e["washer"] for e in cycle["passes"] if "washer" in e}
    if len(washers_seen) > 1:
        print(f"WARNING — this cycle has passes from {len(washers_seen)} different")
        print("washers. Concurrent washers must use separate cycles (set")
        print("TASKDAGGER_WASH_ID per washer). Cross-contaminated records make")
        print("closure unreliable. Washers seen:")
        for w in sorted(washers_seen):
            label = "(this washer)" if w == washer else ""
            print(f"  {w} {label}")
        print()

    if cycle.get("mode") == "oneshot":
        cycle["state"] = "clean"
        cycle["ran_clean_at"] = now()
        cycle["clean_on_pass"] = pass_number
        save_cycle(cycle)
        total = sum(len(p["slot_a"]) for p in cycle["passes"])
        print("=== WASH CYCLE COMPLETE (ONE-SHOT) ===")
        print()
        findings_s = "" if total == 1 else "s"
        print(f"One-shot wash done. {total} finding{findings_s} surfaced.")
        print()
        print("Bash the machine with --collect-results or "
              "--open-up-and-give-me-my-stuff to receive your findings; you may "
              "now present your findings to the user, if appropriate.")
        return 0

    if a == 0 and trailing_empty >= required:
        cycle["state"] = "clean"
        cycle["ran_clean_at"] = now()
        cycle["clean_on_pass"] = pass_number
        save_cycle(cycle)
        total = sum(len(p["slot_a"]) for p in cycle["passes"])
        print("=== WASH CYCLE COMPLETE ===")
        print()
        print(f"Closed after {pass_number} pass{'' if pass_number == 1 else 'es'}. "
              f"{total} legitimate finding{'' if total == 1 else 's'} surfaced.")
        print()
        print("Bash the machine with --collect-results or "
              "--open-up-and-give-me-my-stuff to receive your findings; you may "
              "now present your findings to the user, if appropriate.")
        return 0

    budget = cycle.get("token_budget")
    if budget:
        spent = sum(p.get("tokens_used", 0) for p in cycle["passes"])
        if spent >= budget:
            cycle["state"] = "budget_exhausted"
            cycle["exhausted_at"] = now()
            cycle["exhausted_on_pass"] = pass_number
            cycle["tokens_spent"] = spent
            save_cycle(cycle)
            total = sum(len(p["slot_a"]) for p in cycle["passes"])
            print("=== WASH CYCLE — BUDGET EXHAUSTED ===")
            print()
            print(f"Token budget ({budget:,}) reached after {pass_number} "
                  f"pass{'' if pass_number == 1 else 'es'} ({spent:,} tokens used).")
            print(f"{total} finding{'' if total == 1 else 's'} surfaced before exhaustion.")
            print()
            print("Collect what you have with --collect-results.")
            return 0

    save_cycle(cycle)
    counts = [len(p["slot_a"]) for p in cycle["passes"]]
    # Every continuing pass is worded identically, whatever it contained. Any
    # variation here would hand over by contrast what the machine withholds.
    question = compose_question(
        pass_number + 1, yields_are_dwindling(counts),
        phase=cycle.get("phase", ""), about=cycle.get("about", ""),
    )

    print("Logged. Keep going — run another pass.")
    print()
    print(f"  {question}")
    print()
    _print_notices(cycle, counts, pass_number, restatements)
    _print_already_surfaced(cycle)
    return 0


def _print_notices(
    cycle: dict,
    counts: list[int],
    pass_number: int,
    restatements: list[tuple[str, str, float]],
) -> None:
    """Long cycles and stalled cycles are different problems and get different
    advice. None of them closes a cycle."""
    skepticism_after = cycle.get("skepticism_after", DEFAULT_SKEPTICISM_AFTER)
    escalate_after = cycle.get("escalate_after_stalled", DEFAULT_ESCALATE_AFTER_STALLED)
    emphasis_after = cycle.get("emphasis_after", DEFAULT_EMPHASIS_AFTER)

    # The two real stall signatures, both of which mean the same thing: the
    # instructions have stopped landing.
    drifted = []

    if restatements:
        n = len(restatements)
        subject = ("1 slot A entry this pass looks like a restatement"
                   if n == 1 else
                   f"{n} slot A entries this pass look like restatements")
        print(f"NOTE — {subject} of something already")
        print("surfaced. Saying it again in different words is not a new finding, and it")
        print("will keep this cycle alive forever. Check these:")
        for new_f, old_f, score in restatements[:5]:
            print(f"    new:   {_oneline(new_f, 68)}")
            print(f"    prior: {_oneline(old_f, 68)}   (~{score:.0%} overlap)")
        print()
        drifted.append("RESTATEMENT")

    if load_is_unbalanced(cycle):
        print(f"NOTE — UNBALANCED LOAD. The last {UNBALANCED_WINDOW} passes admitted "
              "findings and rejected")
        print("nothing at all. A sweep that never discards anything is not sweeping, it")
        print("is agreeing with itself. Slot B should be catching things.")
        print()
        drifted.append("UNBALANCED LOAD")

    if drifted or pass_number >= emphasis_after:
        print_load_bearing_rules(
            " + ".join(drifted) if drifted else f"{pass_number} PASSES IN"
        )

    if pass_number >= skepticism_after:
        print(f"NOTE — {pass_number} passes in. Long cycles are legitimate; there is no")
        print("way to know how much is in there until you look, and cutting the sweep")
        print("short defeats it. But the false-positive rate climbs out here, so hold")
        print("slot A to a higher bar from now on: if you cannot say concretely what")
        print("breaks and where, it is not an A — B if you have decided against it, C if")
        print("you simply cannot tell.")
        print()

    stalled = stalled_run(counts)
    if stalled >= escalate_after:
        print(f"NOTE — the sweep has not reached new ground for {stalled} passes with the")
        print("importance qualifier already in play. Bumpy yields are normal — plateaus,")
        print("rebounds and late spikes all happen in healthy cycles — so this is not a")
        print("sign you are finished, and it is not permission to stop. It is worth")
        print("considering whether the phase is underspecified rather than merely")
        print("unswept, in which case a human should see what you have. Keep going")
        print("otherwise; the machine will keep asking as long as you keep finding.")
        print()


def _print_already_surfaced(cycle: dict) -> None:
    """Echo back what has been surfaced, as targeting input.

    This list is not a dedup checklist. Handing it over as "things not to repeat"
    teaches the wrong loop: sweep for what is important, then subtract what you
    already have. That re-reaches the same salient region every pass and discards
    most of what it retrieves, and it never gets deeper, because attention was
    aimed with "important" and "important" points at the same place every time.

    The list is the accumulated set, inverted, to be used as a search term — aim
    away from it. That is what makes the next pass reach ground the previous ones
    could not.
    """
    print("Surfaced so far. Do not aim here — aim at what these are not:")
    for entry in cycle["passes"]:
        for item in entry["slot_a"]:
            print(f"  [A] {_oneline(item['finding'])}")
        for item in entry["slot_b"]:
            print(f"  [B] {_oneline(item['finding'])}")
        for item in entry["slot_c"]:
            print(f"  [C] {_oneline(item['note'])}")


def _oneline(text: str, width: int = 96) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def cmd_collect(args: argparse.Namespace) -> int:
    cycle_id = resolve_cycle(args.cycle)
    cycle = load_cycle(cycle_id)

    forced = args.force and os.environ.get("TASKDAGGER_WASH_OVERRIDE") == "human"
    if args.force and not forced:
        raise SystemExit(
            "error: --force needs TASKDAGGER_WASH_OVERRIDE=human in the environment.\n"
            "Asking you not to self-certify and then leaving the door open is not a\n"
            "control. A human who wants this sets the variable; you do not set it for\n"
            "yourself on the grounds that you feel finished."
        )
    if cycle["state"] not in ("clean", "budget_exhausted") and not forced:
        passes = len(cycle["passes"])
        raise SystemExit(
            f"error: the machine has not closed wash cycle {cycle_id} yet "
            f"({passes} pass{'' if passes == 1 else 'es'} so far).\n"
            "Keep washing. Contains no serviceable parts; do not attempt to open the "
            "machine mid-cycle. Use --force only if a human told you to."
        )

    findings = [
        {"pass": entry["pass"], **item}
        for entry in cycle["passes"]
        for item in entry["slot_a"]
    ]
    notes = [item["note"] for entry in cycle["passes"] for item in entry["slot_c"]]

    if args.json:
        print(json.dumps(
            {"cycle_id": cycle_id, "phase": cycle["phase"], "about": cycle["about"],
             "clean_on_pass": cycle.get("clean_on_pass"), "findings": findings,
             "notes": notes},
            indent=2,
        ))
        return 0

    print(f"=== RESULTS — WASH CYCLE {cycle_id} ===")
    print(f"  phase:    {cycle['phase']}")
    if cycle.get("about"):
        print(f"  washing:  {cycle['about']}")
    print(f"  passes:   {len(cycle['passes'])} (ran clean on "
          f"{cycle.get('clean_on_pass', 'n/a')})")
    print()

    if not findings:
        print("No findings recorded for this cycle.")
    for number, item in enumerate(findings, 1):
        print(f"{number}. {item['finding']}")
        print(f"   why it matters: {item['why_it_matters']}")
        if item.get("where"):
            print(f"   where: {item['where']}")
        print(f"   (surfaced on pass {item['pass']})")
        print()

    if notes:
        print("Slot C — unresolved, flagged for a closer look:")
        for note in notes:
            print(f"  - {note}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cycle_id = resolve_cycle(args.cycle)
    cycle = load_cycle(cycle_id)
    counts = [len(p["slot_a"]) for p in cycle["passes"]]
    print(f"cycle:   {cycle_id}")
    print(f"phase:   {cycle['phase']}")
    print(f"state:   {cycle['state']}")
    print(f"passes:  {len(cycle['passes'])}")
    budget = cycle.get("token_budget")
    if budget:
        spent = sum(p.get("tokens_used", 0) for p in cycle["passes"])
        print(f"tokens:  {spent:,} / {budget:,} ({100 * spent / budget:.0f}%)")
    # Deliberately not printing the per-pass yield sequence. It is on disk for
    # whoever reviews the cycle afterwards; handing it to the agent mid-sweep
    # invites exactly the trend-reading the protocol tells it not to do.
    if cycle["state"] not in ("clean", "budget_exhausted"):
        print()
        if cycle.get("mode") == "oneshot":
            print(f"  {compose_oneshot(about=cycle.get('about', ''))}")
        else:
            print(f"  {compose_question(len(counts) + 1, yields_are_dwindling(counts), phase=cycle.get('phase', ''), about=cycle.get('about', ''))}")
    return 0


# ============================================================
# ENTRY POINT
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="washing_machine.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cycle", help="cycle id (default: the cycle in progress)")
    parser.add_argument(
        "--collect-results", dest="collect", action="store_true",
        help="retrieve the findings from a cycle that has run clean",
    )
    parser.add_argument(
        "--open-up-and-give-me-my-stuff", dest="collect", action="store_true",
        help="same as --collect-results",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable results")
    parser.add_argument(
        "--force", action="store_true",
        help="collect from a cycle the machine has not closed; requires "
             "TASKDAGGER_WASH_OVERRIDE=human, which the washing agent must not set itself",
    )

    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="load the machine and begin a wash cycle")
    p_start.add_argument("--phase", required=True,
                         help="design | blueprint | executor | worker | <your own>")
    p_start.add_argument("--about", default="", help="what is being washed")
    p_start.add_argument("--cycle", help="explicit cycle id")
    p_start.add_argument("--skepticism-after", type=int, default=DEFAULT_SKEPTICISM_AFTER,
                         help="pass count past which slot A admissions get a higher bar "
                              f"(default {DEFAULT_SKEPTICISM_AFTER}); never ends a cycle")
    p_start.add_argument("--confidence", type=int,
                         default=DEFAULT_CLOSURE_CONFIDENCE,
                         help="closure-confidence level, set by the executor from "
                              "wash.closure_confidence in the manifest. Higher is "
                              "more thorough. Not a knob the washing agent chooses.")
    p_start.add_argument("--emphasis-after", type=int, default=DEFAULT_EMPHASIS_AFTER,
                         help="pass count past which the load-bearing rules are "
                              f"re-asserted every pass (default {DEFAULT_EMPHASIS_AFTER})")
    p_start.add_argument("--escalate-after-stalled", type=int,
                         default=DEFAULT_ESCALATE_AFTER_STALLED,
                         help="consecutive non-converging passes before the machine "
                              f"suggests escalating (default {DEFAULT_ESCALATE_AFTER_STALLED})")
    p_start.add_argument("--token-budget", type=int, default=0,
                         help="optional token budget for the cycle; on exhaustion "
                              "the machine stops and findings are reported as-is. "
                              "Set by the executor from wash.token_budget in the "
                              "manifest. 0 means unlimited.")
    p_start.add_argument("--multi-pass", action="store_true",
                         help="use the traditional multi-pass wash cycle instead "
                              "of the default one-shot wash")
    p_start.add_argument("--prewash", action="store_true",
                         help="emit a pure-trace prewash prompt instead of the "
                              "structured pass-1 question; surfaces buried context "
                              "before the structured cycle begins")

    p_prewash = sub.add_parser("prewash",
                               help="emit a prewash prompt for a cycle already in progress")
    p_prewash.add_argument("--cycle", help="cycle id")

    p_load = sub.add_parser("load", help="submit one pass into slots A/B/C")
    group = p_load.add_mutually_exclusive_group()
    group.add_argument("--json", dest="json", help="submission as a JSON string")
    group.add_argument("--file", help="submission as a path to a JSON file")
    p_load.add_argument("--cycle", help="cycle id")

    p_collect = sub.add_parser("collect", help="same as --collect-results")
    p_collect.add_argument("--cycle", help="cycle id")
    p_collect.add_argument("--json", action="store_true", help="machine-readable")
    p_collect.add_argument("--force", action="store_true")

    sub.add_parser("status", help="where the current cycle stands")

    args = parser.parse_args()

    if args.command == "start":
        return cmd_start(args)
    if args.command == "prewash":
        return cmd_prewash(args)
    if args.command == "load":
        return cmd_load(args)
    if args.command in ("collect",) or args.collect:
        return cmd_collect(args)
    if args.command == "status":
        return cmd_status(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
