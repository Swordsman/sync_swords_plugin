#!/usr/bin/env python3
"""winnow v0.2 streaming extraction orchestrator (spec section 9).

Drives the core loop over a turn-tagged transcript:

    turns -> extractor (loose, LLM) -> normalizer (strict) -> delta -> log

The extractor sees only the tiered digest (digest.py, spec section 10) plus
the new turns. Stage B is split per the spec: an optional LLM pass for the
semantic rules (R1/R3/R5/R6/R9/R10), then a procedural pass that enforces
the mechanical ones (R7 ann order, R8 serial ids, R11 dedup, reference
validation) regardless of what any model emitted.

Transcript format: turns are introduced by a header line `[tN speaker]`
(e.g. `[t1 user]`); everything until the next header is that turn's text.

Usage:
    python3 winnow.py transcript.txt --out log.wno
    python3 winnow.py transcript.txt --out log.wno --replay fixtures.txt
    python3 winnow.py transcript.txt --out log.wno --per-turn

Live mode needs the `anthropic` package and an API credential; --replay
mode (canned responses separated by lines containing only %%%) needs
neither and exists for tests and offline development.
"""
import argparse
import json
import re
import sys
import types

import basis
import digest as digest_view
import trouble
from fold import (Graph, Lit, parse, tokenize, sx, anns, ETYPES, FRAMES,
                  STATUSES, parse_sig, sig_misfit)

ID_PREFIX = {"claim": "c", "decision": "d", "question": "q",
             "constraint": "k", "def": "f", "action": "a", "artifact": "r"}
ANN_ORDER = ["status", "conf", "status-conf", "strength", "by",
             "src", "time", "modal", "neg"]
DEFAULT_MODEL = "claude-opus-4-8"

SEED_SIGS = {
    "fails": ("THING failed in the way KIND names",
              ["THING", "KIND:termid"]),
    "causes": ("CAUSE brings about EFFECT",
               ["CAUSE", "EFFECT"]),
    "maps-to": ("SOURCE corresponds to TARGET",
                ["SOURCE", "TARGET"]),
}

EXTRACTOR_SYSTEM = """\
You're taking working notes on a live conversation, for a future reader \
with zero patience for transcript archaeology -- probably us, later. You \
get two things: the note graph so far (a digest of what's live, not the \
whole graph), and the newest turns.

Jot what changed, as winnow delta ops -- new claims, decisions, \
constraints, questions, definitions, actions, and links between them. \
Loose syntax is fine; a normalizer cleans up after you. What matters:

- capture every commitment, correction, requirement, and open thread
- when someone's joking, keep the payload, drop the joke
- when someone takes a position on material they read or were given, \
note the stance -- the verdict outranks the summary
- if something restates what's already in the graph, skip it
- if a new statement kills or changes an old node, say so (update / supersede)
- when someone reasons from a supposition ("assume", "suppose", "say \
that", "for the sake of argument", "if we take X as given"), note the \
supposition as a claim with :status assumed, and hang what they conclude \
from it on it with (depends CONCLUSION SUPPOSITION); a plain "if/when X, \
Y" describing how something behaves is an ordinary claim, not a supposition
- when an assumption gets checked, flip it: (update ID :status live) if \
it held, :status retracted if it didn't; never add it again
- if the conditional itself gets used (it's someone's reason, it answers \
something, or they say it holds either way), note it too, as a claim \
(implies SUPPOSITION CONCLUSION) over the two nodes
- attribute everything: who said it (:by), which turn (:src)
- unsure? include it with low :conf rather than dropping it
- when something went wrong and someone treats it as a problem -- calls \
it a mistake, a bug or a misunderstanding, or says what it cost (work \
redone, a wrong turn, time lost) -- note a claim (fails WHAT KIND). WHAT \
is the note or term that went wrong, never a person: :by already says who \
spotted it. KIND is one of false-belief, miscommunication, \
instruction-violation, tool-failure, regression, omission, outdated-state. \
Why it happened, if anyone says, is its own claim (causes WHY FAILURE), \
:modal may when they're guessing. A fix links (answers fix failure); \
something put in place so it can't happen again links (motivates failure \
guard). A correction nobody calls a problem is just a correction.

Never note: greetings, filler, vibes, meta-chatter about the conversation \
itself.

The vocabulary (loose phrasing welcome, but stay inside it):
- node frames: claim, question, decision, constraint, def, action, artifact
- links, always exactly (type from to): supports, contradicts, \
supersedes (new old), refines (detail parent), answers (x \
question-or-failure), motivates (reason thing), depends (x y), about (x topic)
Eight link types, no others. A relationship that doesn't fit is content, \
not a link -- put it inside a node's proposition instead, e.g. \
(add (claim x3 (maps-to subthread original-messages) :by user :src t7)).

Emit ops as s-expressions, one per line, e.g.:
(term some-term :gloss "what it means, not just the name expanded" :canon "Wikipedia_Article_Title")
(add (claim x1 (relation subj obj) :by user :src t3))
(add (edge (supports x1 x2)))
(update q2 :status answered)
(add (claim x4 (fails c2 false-belief) :by user :src t6))
(add (claim x5 (causes dropped-workaround x4) :modal may :by assistant :src t6))
Use any placeholder ids you like; the normalizer assigns real ones.

If the new turns reference something that isn't on the digest -- an \
earlier decision, a term you don't see, "that thing from before" -- emit \
(reach the-reference) and the orchestrator will pull it from deeper \
storage or turn it into an open question. Never invent a referent."""

NORMALIZER_SYSTEM = """\
You are the winnow normalizer. Input: a candidate delta plus the current \
term registry. Output: the canonical ops, one s-expression per line, \
nothing else -- no commentary, no code fences.

Node frames (only these seven): claim, question, decision, constraint, \
def, action, artifact. A node is (FRAME ID PAYLOAD :anns...) and the \
payload proposition is mandatory: (RELATION ARG1 ARG2 ...), args being \
term ids, node ids, "literals", or numbers. Default statuses (omit them): \
claim/constraint/def/artifact live, question open, decision proposed, \
action todo.

Legal statuses per frame, nothing else: claim live/assumed/corrected/\
retracted/superseded; def live/deprecated/superseded; question open/answered/\
dropped/superseded; decision proposed/frozen/superseded/abandoned; \
constraint live/relaxed/retired/superseded; action todo/doing/done/\
blocked/dropped/superseded; artifact live/deprecated/superseded.

Edge types (only these eight), always exactly (TYPE FROM TO), no extra \
args: supports (evidence first), contradicts (challenger first), \
supersedes (new first), refines (detail first), answers (answer or fix \
first, question or failure second), motivates (reason first), depends \
(dependent first), about (node first, topic/node/term second -- about \
is the one edge whose target may be a term id instead of a node id). \
A candidate edge with any other type: \
map it to the nearest of the eight when meaning allows -- \
references/addresses/relates-to are usually about; because/rationale/\
mechanism are usually motivates; fulfills is usually answers or refines. \
If no mapping preserves the meaning, re-express the relationship as a \
proposition inside a node. Never output a non-canonical edge type. Extra \
edge annotations (:conf etc.) are dropped.

The rules:
R1 terms -> canonical registry ids: kebab-case; nearest registry match \
beats minting; minted terms get a (term ID :gloss "..." :canon "...") \
entry. The gloss must define the concept, not restate the label — \
"graph-db" glossed "graph database" adds nothing; write what a reader \
needs to understand the term without the transcript. \
:canon is a Wikipedia article title for the concept when one exists \
(e.g. :canon "Design_by_contract", :canon "Filesystem_in_Userspace"). \
Use the exact article title with underscores. Project-specific terms \
that have no Wikipedia article omit :canon.
R2 one proposition per node -- split conjunctions into multiple nodes.
R3 relation signatures: a relation whose registry entry has :sig takes \
exactly one argument per slot, in slot order, each arg of the sort the \
slot admits; a two-slot proposition that fits only reversed is swapped \
(R5). An untyped relation follows its prose direction gloss.
R4 tense, modality, polarity, supposition -> annotations (:time :modal \
:neg; a supposition is :status assumed, R14), never new relations or terms.
R5 passive voice -> active; swap args to canonical direction.
R6 verb phrases nominalize to registry relations -- nearest match beats \
invention.
R7 annotation keys in fixed order: :status :conf :status-conf :strength \
:by :src :time :modal :neg; omit defaults.
R8 keep the extractor's placeholder node ids -- serial ids are assigned \
after you.
R9 no synonym relations -- nearest registry relation, or a new (term ...) \
entry.
R10 unwrap rhetoric: humor, hypotheticals-as-emphasis, framing devices \
reduce to their payload proposition; phatic content reduces to nothing. \
A supposition someone reasons from is not rhetoric: it is :status assumed \
(R14), not a reduction to its payload.
R11 identical canonical payloads within the delta collapse to one node \
(graph-level dedup runs after you).
R12 numbers/units stay literal; prose quantities normalize ("seventy km" \
-> "70km").
R13 failures: something that went wrong is a claim (fails THING KIND), \
exactly two args. THING is the node id or term id that went wrong, never \
a speaker. KIND is the nearest of false-belief, miscommunication, \
instruction-violation, tool-failure, regression, omission, outdated-state; \
mint a new kind only when none fits. Failed/went-wrong/broke phrasing maps \
to fails; a standing limitation ("X doesn't work on Y") is not a failure \
and takes another relation. Why it happened is a claim (causes CAUSE \
FAILURE-ID) whose CAUSE is an action, node or term, never a speaker.
R14 suppositions: a claim someone reasons from without asserting it takes \
:status assumed. :status assumed on a decision becomes proposed; on any \
other frame, return (reject "assumed is a claim status") for that op. A \
restated assumption whose status changed is an update, not a new node. A \
conclusion drawn under a supposition gets (depends CONCLUSION \
SUPPOSITION). A conditional is a claim (implies A C) over two distinct \
existing node ids, neither of them the conditional's own; write one only \
when something attaches to the conditional itself or the speaker says it \
holds either way. If A is not already among C's grounds, add (depends C \
A); declare implies on first use.

A relation whose registry entry has :sig takes exactly one argument per \
slot, in slot order. A slot written ROLE:termid|id takes only those sorts \
(termid, id = node id, string, number); a bare ROLE takes anything. When \
you mint a relation and its argument roles are clear, you may give it \
:sig (ROLE ROLE ...), with roles in capitals and subject/source first. \
Leave :sig off when unsure: an untyped relation is always accepted.

Op syntax, exactly:
(term ID :gloss "..." :aka ("...") :canon "..." :sig (ROLE ROLE:sort))
(add (FRAME ID PAYLOAD :anns...))
(add (edge (TYPE FROM TO)))
(update ID :key val)
(supersede NEW OLD)

Every node keeps :by (speaker) and :src (tN). An op you cannot \
canonicalize becomes (reject "reason"). Output ops only."""

CHECKER_SYSTEM = """\
You are the winnow checker. Another model turned the newest conversation \
turns into a candidate delta of winnow ops; you check it against the \
turns before it is committed. Input: the note graph so far (a digest of \
what's live, not the whole graph), the term registry, any pull results, \
the new turns, and the candidate delta. Output: the delta that should be \
committed, one s-expression op per line, nothing else -- no commentary, \
no code fences.

Check every op against the new turns:
- drop an op the turns don't support: invented content, a stance the \
speaker didn't take, something the digest already holds
- fix an op that distorts what was said: wrong :by or :src, flipped \
polarity or modality, swapped arguments (per the relation's :sig where \
it has one), wrong frame, wrong status, wrong edge type or direction
- add what the candidate missed: a commitment, correction, requirement, \
decision or open thread in the new turns with no op
- drop a (fails ...) claim the turns don't treat as a problem; fix one \
that names a person where it should name what went wrong
- keep every right op exactly as it is, ids included
If the candidate is right, output it unchanged.

Stay inside the candidate's vocabulary. Node frames, only these seven: \
claim, question, decision, constraint, def, action, artifact. Edges, only \
these eight, always exactly (TYPE FROM TO): supports, contradicts, \
supersedes (new old), refines (detail parent), answers (answer-or-fix \
question-or-failure), motivates (reason thing), depends (dependent \
dependency), about (node topic). Op syntax, exactly:
(term ID :gloss "..." :canon "Wikipedia_Article_Title")
(add (FRAME ID PAYLOAD :anns...))
(add (edge (TYPE FROM TO)))
(update ID :key val)
(supersede NEW OLD)
Every node keeps :by (speaker) and :src (tN). New ids are placeholders; \
serial ids are assigned after you."""


# ------------------------------------------------------------ transcript

def parse_transcript(text):
    """Yield (turn_index, speaker, text) from `[tN speaker]` blocks."""
    turns = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\[t(\d+)\s+(\S+)\]\s*$", line)
        if m:
            cur = [int(m.group(1)), m.group(2), []]
            turns.append(cur)
        elif cur is not None:
            cur[2].append(line)
    return [(n, who, "\n".join(body).strip()) for n, who, body in turns]


# ------------------------------------------------------------ llm clients

# The Messages API requires max_tokens, so send each model's full output
# capacity: never a lower cap (thinking counts against it, and a cap
# truncates the answer). DeepSeek's from /models; Claude's from its docs.
MAX_OUTPUT_TOKENS = {"deepseek": 393216, "claude": 128000}


def anthropic_client(model, base_url=None, api_key_env=None, effort="max",
                     max_tokens=MAX_OUTPUT_TOKENS["claude"]):
    """Anthropic-SDK llm callable, adaptive thinking at `effort` (max by
    default), streaming with the model's full output capacity."""
    import anthropic, os
    kwargs = {}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key_env:
        kwargs["api_key"] = os.environ[api_key_env]
    client = anthropic.Anthropic(**kwargs)

    def call(system, user):
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            resp = stream.get_final_message()
        return "".join(b.text for b in resp.content if b.type == "text")

    return call


def deepseek_client(model="flash", ds_path=None, retries=3, re2=False,
                    think="max", call_timeout=1800):
    """ds-backed llm callable. Thinking runs at `think` effort (max by
    default: winnow runs below max lose extraction quality); RE2 replaces
    thinking, so with re2 no effort is sent. Prompts reach ds as files,
    never as arguments: an argument over 128 KiB fails the call, and argv
    shows in ps. stdin is closed, or ds would read the caller's."""
    import atexit, os, shutil, subprocess, tempfile, time
    if ds_path is None:
        ds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds")
    mode_args = ["--re2", "paper"] if re2 else ["--think", think]
    scratch = tempfile.mkdtemp(prefix="winnow-ds-")
    atexit.register(shutil.rmtree, scratch, True)
    system_path = os.path.join(scratch, "system.txt")
    task_path = os.path.join(scratch, "task.txt")

    def call(system, user):
        for path, text in ((system_path, system), (task_path, user)):
            with open(path, "w") as f:
                f.write(text)
        last_err = None
        for attempt in range(retries):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                result = subprocess.run(
                    [ds_path, "--persist", "no", "-m", model,
                     "--timeout", "300", "-q", *mode_args,
                     "--system-file", system_path, "--task-file", task_path],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    timeout=call_timeout,
                )
            except subprocess.TimeoutExpired as e:
                last_err = f"ds hit the {e.timeout}s wall-clock cap"
                print(f"  (retry {attempt + 1}/{retries}: {last_err})",
                      file=sys.stderr)
                continue
            if result.returncode == 0:
                return result.stdout.strip()
            last_err = (f"ds failed (exit {result.returncode}): "
                        f"{result.stderr.strip()}")
            print(f"  (retry {attempt + 1}/{retries}: {last_err})",
                  file=sys.stderr)
        raise RuntimeError(f"{last_err} [after {retries} attempts]")

    return call


def claude_code_client(model, effort="max", claude_path="claude", retries=3,
                       call_timeout=1800):
    """`claude -p` llm callable: a tool-less Claude Code subagent at `effort`
    (max by default), authenticated however the local claude is. Runs from
    an empty scratch directory with project settings only, no MCP servers
    and no skills, so no hooks, plugins or CLAUDE.md reach it (a recording
    hook would otherwise record the call and recurse); LITTLEWING_RAW/WNO
    =off backs that up. The system prompt goes in a file and the user
    content on stdin, so neither meets the argv size limit."""
    import atexit, os, shutil, subprocess, tempfile, time
    scratch = tempfile.mkdtemp(prefix="winnow-claude-")
    atexit.register(shutil.rmtree, scratch, True)
    cwd = os.path.join(scratch, "cwd")
    os.mkdir(cwd)
    system_path = os.path.join(scratch, "system.txt")
    env = dict(os.environ, LITTLEWING_RAW="off", LITTLEWING_WNO="off")

    def call(system, user):
        with open(system_path, "w") as f:
            f.write(system)
        argv = [claude_path, "-p", "--output-format", "text",
                "--setting-sources", "project", "--strict-mcp-config",
                "--disable-slash-commands", "--no-session-persistence",
                "--tools", "", "--model", model, "--effort", effort,
                "--system-prompt-file", system_path]
        last_err = None
        for attempt in range(retries):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                result = subprocess.run(argv, input=user, cwd=cwd, env=env,
                                        capture_output=True, text=True,
                                        timeout=call_timeout)
            except subprocess.TimeoutExpired as e:
                last_err = f"claude hit the {e.timeout}s wall-clock cap"
            else:
                if result.returncode == 0:
                    return result.stdout.strip()
                last_err = (f"claude failed (exit {result.returncode}): "
                            f"{(result.stderr or result.stdout).strip()}")
            print(f"  (retry {attempt + 1}/{retries}: {last_err})",
                  file=sys.stderr)
        raise RuntimeError(f"{last_err} [after {retries} attempts]")

    return call


# Claude model policy (Joe, 2026-10-13; simplified 2026-11-01): don't
# trust haiku to approve its own work.
def claude_family(model):
    """haiku / sonnet / opus from an alias or a full model id, else None."""
    for family in ("haiku", "sonnet", "opus"):
        if family in str(model).lower():
            return family
    return None


def claude_policy_error(model, checker=None):
    """Why this extractor/checker pairing breaks the Claude model policy,
    or None when it's allowed."""
    family = claude_family(model)
    if family is None:
        return (f"{model!r} isn't a haiku, sonnet or opus model; the "
                f"Claude backends' model policy covers only those")
    checked_by = claude_family(checker) if checker else None
    if checker and checked_by is None:
        return (f"{checker!r} isn't a haiku, sonnet or opus model; the "
                f"Claude backends' model policy covers only those")
    if family == "haiku":
        if checked_by is None:
            return ("a haiku extractor needs a non-haiku checker: add "
                    "--checker sonnet or --checker opus")
        if checked_by == "haiku":
            return ("a haiku extractor needs a non-haiku checker: use "
                    "--checker sonnet or --checker opus, not haiku")
    return None


def replay_client(path):
    """Canned responses split on lines containing only %%% -- consumed in
    call order. For tests and offline runs."""
    with open(path) as f:
        chunks = re.split(r"(?m)^%%%$", f.read())
    queue = [c.strip() for c in chunks if c.strip()]

    def call(system, user):
        if not queue:
            raise RuntimeError("replay fixture exhausted")
        return queue.pop(0)

    return call


# ------------------------------------------------------------ resolver

def kebab(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


# Cross-lineage vocabulary aliases: surface forms from the Kimi proposal
# docs mapped onto winnow's canonical vocabulary (kimi-salvage a5). A
# token on the left matches any registry term on the right.
KIMI_ALIASES = {
    "sniping": ("reach", "resolution-ladder"),
    "echo": ("promotion", "usage-mass"),
    "concept-space": ("term-registry",),
}

# Status classes for ranking: actionable/live first, settled second,
# dead last. Mass and recency break ties within a class.
_STATUS_CLASS = {
    "open": 0, "doing": 0, "blocked": 0, "live": 0, "proposed": 0,
    "todo": 0, "assumed": 0,
    "frozen": 1, "done": 1, "answered": 1, "accepted": 1, "resolved": 1,
    "superseded": 2, "rejected": 2, "retracted": 2,
}


class Resolver:
    """Pull interface + handshake verifier (spec 10.5). Walks the
    resolution ladder procedurally: rung 0/1 resident hits, rung 2 warm
    widening, rung 3 cold scan (the materialized-graph equivalent of
    fold-replay), rung 4 global KB (cross-conversation mega-fold graph),
    rung 5 honest miss. An optional llm callable is the cheap-inference
    escalation on lexical miss; the procedural floor runs first always."""

    def __init__(self, graph, llm=None, global_kb=None):
        self.g = graph
        self.llm = llm
        self.kb = global_kb        # cross-conversation graph for rung 4
        self.surface = {}          # surface form -> canonical term id
        self.constituents = {}     # hyphen-split part -> {term ids}
        self.senses = {}           # base word -> {sense-qualified tids}
        for tid, tail in graph.terms.items():
            self.surface[kebab(tid)] = tid
            tail_anns = anns(list(tail))
            for aka in tail_anns.get("aka", []) or []:
                self.surface[kebab(aka)] = tid
            canon = tail_anns.get("canon")
            if canon:
                self.surface[kebab(str(canon))] = tid
            for part in kebab(tid).split("-"):
                if part != kebab(tid):
                    self.constituents.setdefault(part, set()).add(tid)
            if "/" in tid:         # sense-qualified: tap/faucet, tap/strike
                base = kebab(tid.split("/", 1)[0])
                self.senses.setdefault(base, set()).add(tid)
        if global_kb:
            self.kb_surface = {}
            self.kb_constituents = {}
            self.kb_senses = {}
            for tid, tail in global_kb.terms.items():
                self.kb_surface[kebab(tid)] = tid
                tail_anns = anns(list(tail))
                for aka in tail_anns.get("aka", []) or []:
                    self.kb_surface[kebab(aka)] = tid
                canon = tail_anns.get("canon")
                if canon:
                    self.kb_surface[kebab(str(canon))] = tid
                for part in kebab(tid).split("-"):
                    if part != kebab(tid):
                        self.kb_constituents.setdefault(part, set()).add(tid)
                if "/" in tid:
                    base = kebab(tid.split("/", 1)[0])
                    self.kb_senses.setdefault(base, set()).add(tid)

    def _term_hits(self, toks):
        """Registry terms reached by tokens: exact surface, cross-lineage
        alias (KIMI_ALIASES), then constituent match (auth -> auth-system)."""
        expanded = set(toks)
        for t in toks:
            expanded.update(kebab(a) for a in KIMI_ALIASES.get(t, ()))
        terms = {self.surface[t] for t in expanded if t in self.surface}
        for t in expanded:
            terms |= self.constituents.get(t, set())
            # polysemy contract: a bare word reaches every parked sense;
            # senses never collapse, ranking orders them
            terms |= self.senses.get(t, set())
        return terms

    def _kb_term_hits(self, toks):
        """Like _term_hits but against the global KB's registry."""
        if not self.kb:
            return set()
        expanded = set(toks)
        for t in toks:
            expanded.update(kebab(a) for a in KIMI_ALIASES.get(t, ()))
        terms = {self.kb_surface[t] for t in expanded if t in self.kb_surface}
        for t in expanded:
            terms |= self.kb_constituents.get(t, set())
            terms |= self.kb_senses.get(t, set())
        return terms

    def _kb_matches(self, tokens):
        """Match tokens against the global KB's nodes."""
        if not self.kb:
            return []
        toks = {kebab(t) for t in tokens}
        terms = {kebab(t) for t in self._kb_term_hits(toks)}
        out = []
        for nid in self.kb.nodes:
            n = self.kb.nodes[nid]
            syms = {kebab(s) for s in _payload_syms(n["payload"])}
            if nid in toks or syms & toks or syms & terms:
                out.append(nid)
        return out

    def _kb_rank(self, hits):
        """Rank global KB hits by (status class, mass, recency)."""
        def key(nid):
            n = self.kb.nodes[nid]
            return (_STATUS_CLASS.get(n["status"], 1),
                    -self.kb.node_mass(nid),
                    -self.kb.last_touch.get(nid, 0))
        return sorted(hits, key=key)

    def _matches(self, tokens, ids):
        """Nodes among ids whose id or payload symbols hit any token."""
        toks = {kebab(t) for t in tokens}
        # payload symbols are compared kebabed, so term ids must be too
        # (sense-qualified ids like tap/faucet are not kebab-stable)
        terms = {kebab(t) for t in self._term_hits(toks)}
        out = []
        for nid in ids:
            n = self.g.nodes[nid]
            syms = {kebab(s) for s in _payload_syms(n["payload"])}
            if nid in toks or syms & toks or syms & terms:
                out.append(nid)
        return out

    def _rank(self, hits):
        """Order multi-hit resolutions by (status class, usage mass,
        recency). Mass orders retrieval only — never window residency."""
        def key(nid):
            n = self.g.nodes[nid]
            return (_STATUS_CLASS.get(n["status"], 1),
                    -self.g.node_mass(nid),
                    -self.g.last_touch.get(nid, 0))
        return sorted(hits, key=key)

    def resolve(self, tokens):
        """Return (rung, [node ids]) or (5, []) for an honest miss."""
        fire, hot, warm, cold = digest_view.tiers(self.g)
        resident = list(fire) + list(hot)
        hit = self._matches(tokens, resident)
        if hit:
            return (0 if set(hit) & fire else 1), self._rank(hit)
        hit = self._matches(tokens, warm)
        if hit:                                   # rung 2: widen around hits
            base = int(self.g.profile["widening-base"])
            adj = {}
            for t, a, b in self.g.edges:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
            widened = list(hit)
            for nid in hit:
                widened += [x for x in adj.get(nid, ()) if x in self.g.nodes]
            # ranked truncation: keep the best base^2 by (status class,
            # mass, recency) instead of arbitrary insertion order
            widened = self._rank(dict.fromkeys(widened))
            return 2, widened[:base ** 2]
        hit = self._matches(tokens, cold)
        if hit:
            return 3, self._rank(hit)
        if self.kb:                               # rung 4: global KB
            hit = self._kb_matches(tokens)
            if hit:
                return 4, self._kb_rank(hit)
        if self.llm:                              # lexical miss escalation
            guess = self.llm(
                "Map the query to canonical term ids from the registry, "
                "one per line; output nothing else. Registry:\n" +
                "\n".join(sorted(self.g.terms)),
                " ".join(str(t) for t in tokens))
            terms = [t.strip() for t in guess.splitlines()
                     if t.strip() in self.g.terms]
            if terms:
                hit = self._matches(terms, list(self.g.nodes))
                if hit:
                    return 3, self._rank(hit)
        return 5, []                              # honest miss


def _payload_syms(v):
    if isinstance(v, list):
        return [s for x in v for s in _payload_syms(x)]
    return [str(v)]


# ------------------------------------------------------------ normalizer

def extract_forms(text):
    """Pull balanced top-level s-expressions out of LLM prose."""
    forms, depth, start = [], 0, None
    in_str = False
    for i, ch in enumerate(text):
        if ch == '"':
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                forms.append(text[start:i + 1])
    parsed = []
    for f in forms:
        try:
            got = parse(tokenize(f))
            parsed.extend(x for x in got if isinstance(x, list) and x)
        except (IndexError, AssertionError):
            continue
    # unwrap any (delta :turn N op...) wrappers the model emitted
    flat = []
    for form in parsed:
        if form[0] == "delta":
            flat.extend(x for x in form[1:] if isinstance(x, list))
        else:
            flat.append(form)
    known = {"term", "add", "update", "supersede", "merge", "del"}
    return [f for f in flat if f[0] in known]


def extract_reaches(text):
    """(reach QUERY...) forms from extractor output — wire-level only,
    never persisted (spec section 7 wire note)."""
    forms, depth, start, in_str = [], 0, None, False
    for i, ch in enumerate(text):
        if ch == '"':
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                forms.append(text[start:i + 1])
    out = []
    for f in forms:
        try:
            for form in parse(tokenize(f)):
                if isinstance(form, list) and form and form[0] == "reach":
                    query = _without_anns(form[1:])
                    if query:
                        out.append(query)
        except (IndexError, AssertionError):
            continue
    return out


def _without_anns(tokens):
    """A reach query minus `:key value` pairs. Extractors tag reaches like
    any op (seen live 2026-10-13: (reach the-export :by user :src t1)), and
    the tags aren't search terms."""
    out, skip = [], False
    for t in tokens:
        if skip:
            skip = False
        elif isinstance(t, str) and not isinstance(t, Lit) and t.startswith(":"):
            skip = True
        else:
            out.append(t)
    return out


def _map_payload(v, idmap):
    """Placeholder node ids inside a payload -> assigned ids (R8)."""
    if isinstance(v, list):
        return [_map_payload(x, idmap) for x in v]
    if isinstance(v, str) and not isinstance(v, Lit):
        return idmap.get(v, v)
    return v


def _drop_key(tail, key):
    """A copy of a term tail with `:key value` pairs removed."""
    out, i = [], 0
    while i < len(tail):
        if tail[i] == key:
            i += 2
        else:
            out.append(tail[i])
            i += 1
    return out


def _tail_sig(tail):
    """(parsed_sig, error) for a term tail."""
    a = anns(list(tail))
    if "sig" not in a:
        return None, None
    try:
        return parse_sig(a["sig"]), None
    except ValueError as e:
        return None, e


def _assumed_status(frame, a):
    """R14: `assumed` is a claim status. A supposed decision is a proposed
    one (rewritten in `a`); on any other frame, the reject reason."""
    if a.get("status") != "assumed" or frame == "claim":
        return None
    if frame == "decision":
        a["status"] = "proposed"
        return None
    return "assumed is a claim status"


_PLACEHOLDER = re.compile(r"x[0-9]+\Z")


def _implies_term():
    return ["term", basis.COND, ":gloss",
            Lit("(implies ANTECEDENT CONSEQUENT): if the first node holds, "
                "so does the second")]


def _batch_view(g, out):
    """The graph plus this batch's adds: enough for basis's walks."""
    nodes, edges = dict(g.nodes), list(g.edges)
    for op in out:
        if op[0] != "add":
            continue
        item = op[1]
        if item[0] == "edge":
            edges.append(tuple(item[1]))
        else:
            cut = 4 if item[0] == "def" else 3
            nodes[item[1]] = dict(anns(item[cut:]), frame=item[0],
                                  payload=item[2] if cut == 3 else item[2:4])
    return types.SimpleNamespace(nodes=nodes, edges=edges)


def _dangling_key(form):
    """True if any list in `form` ends with a bare :keyword."""
    if not isinstance(form, list):
        return False
    if form and isinstance(form[-1], str) and not isinstance(form[-1], Lit) \
            and form[-1].startswith(":"):
        return True
    return any(_dangling_key(x) for x in form)


class Normalizer:
    """Procedural stage-B enforcement: serial ids (R8), dedup (R11),
    annotation order (R7), reference validation. Semantic normalization
    (R1-R6, R9-R14) is the upstream LLM pass's job; everything here holds
    even if that pass is skipped or misbehaves."""

    def __init__(self, graph):
        self.g = graph
        self.serial = {f: 0 for f in ID_PREFIX}
        for nid, n in graph.nodes.items():
            num = int(re.sub(r"\D", "", nid) or 0)
            f = n["frame"]
            if f in self.serial:
                self.serial[f] = max(self.serial[f], num)
        self.payload_index = {
            (n["frame"], sx(n["payload"])): nid
            for nid, n in graph.nodes.items()}
        self.coercions = []

    def _next_id(self, frame):
        self.serial[frame] += 1
        return f"{ID_PREFIX[frame]}{self.serial[frame]}"

    def _map(self, ref, idmap):
        if not isinstance(ref, str):
            return ref
        return idmap.get(ref, ref)

    def _node_form(self, frame, nid, payload, ann_dict):
        parts = [frame, nid]
        parts += payload if frame == "def" else [payload]
        for k in ANN_ORDER:
            if k in ann_dict:
                parts += [":" + k, ann_dict[k]]
        return parts

    def _sig(self, rel, new_terms):
        """Parsed slots for rel, preferring this batch then the graph."""
        tail = new_terms.get(rel)
        if tail is not None:
            slots, _ = _tail_sig(tail)
            if slots is not None:
                return slots
            if rel in SEED_SIGS:
                return parse_sig(list(SEED_SIGS[rel][1]))
            return None
        src = self.g.terms.get(rel)
        if src is not None:
            slots, _ = _tail_sig(src)
            if slots is not None:
                return slots
            if rel in SEED_SIGS:
                return parse_sig(list(SEED_SIGS[rel][1]))
            return None
        if rel in SEED_SIGS:
            return parse_sig(list(SEED_SIGS[rel][1]))
        return None

    def _seed_relation(self, head, new_terms, out):
        """Declare a seeded typed relation on first committed use, and
        add :sig to an existing registry entry that lacks one."""
        if head not in SEED_SIGS:
            return
        gloss, sig_tokens = SEED_SIGS[head]
        sig_val = list(sig_tokens)
        if head in new_terms:
            tail = list(new_terms[head])
            slots, _ = _tail_sig(tail)
            if slots is None:
                tail = _drop_key(tail, ":sig") + [":sig", sig_val]
                new_terms[head] = tail
                out.append(["term", head] + tail)
            return
        if head in self.g.terms:
            tail = list(self.g.terms[head])
            slots, _ = _tail_sig(tail)
            if slots is None:
                tail = _drop_key(tail, ":sig") + [":sig", sig_val]
                new_terms[head] = tail
                out.append(["term", head] + tail)
            return
        tail = [":gloss", Lit(gloss), ":sig", sig_val]
        new_terms[head] = tail
        out.append(["term", head] + tail)

    def _conditional(self, payload, a, xid, idmap, added):
        """R14: (is_conditional, reject reason). (implies A C) with a
        node-shaped arg is a conditional, and both args must then be
        distinct nodes -- existing, assigned this batch, or added later in
        it -- other than the conditional's own."""
        ac = basis.cond_args(dict(a, frame="claim", payload=payload))
        assigned = set(idmap.values())
        known = lambda r: r != xid and (r in self.g.nodes or r in assigned
                                        or r in added)
        if not ac or not any(known(r) or r == xid or basis.IDLIKE.match(r)
                             or _PLACEHOLDER.match(r) for r in ac):
            return False, None
        if ac[0] == ac[1] or not all(known(r) for r in ac):
            return True, (f"conditional {sx(payload)} needs two distinct "
                          f"existing nodes other than its own")
        return True, None

    def normalize(self, forms):
        """Return (canonical_ops, rejects). canonical_ops are parsed
        forms ready to serialize into one delta."""
        out, rejects, idmap = [], [], {}
        new_frames = {}   # nid assigned this batch -> frame (for update
                           # ops that target a node added earlier in it)
        new_terms = {}     # term id -> tail declared this batch
        new_payloads = {}  # nid assigned this batch -> payload (R13)
        batch_edges = set()
        speakers = trouble.speakers(self.g, forms)
        added = {op[1][1] for op in forms        # node placeholders (R14)
                 if isinstance(op, list) and len(op) > 1 and op[0] == "add"
                 and isinstance(op[1], list) and len(op[1]) > 1
                 and op[1][0] != "edge"}
        for op in forms:
            if _dangling_key(op):
                # e.g. `(add (claim x1 (has a b) :by))`: a model emitted a
                # key with nothing after it, which anns() can't pair
                rejects.append(f"annotation key without a value: {sx(op)[:80]}")
                continue
            head = op[0]
            if head == "term":
                tid = op[1]
                tail = list(op[2:])
                a = anns(tail)
                parsed_sig = None
                if "sig" in a:
                    try:
                        parsed_sig = parse_sig(a["sig"])
                    except ValueError as e:
                        rejects.append(f"malformed :sig on term {tid}: {e}")
                        tail = _drop_key(tail, ":sig")
                        a = anns(tail)
                if tid in SEED_SIGS and parsed_sig is not None \
                        and parsed_sig != parse_sig(list(SEED_SIGS[tid][1])):
                    rejects.append(
                        f"sig conflict for {tid}: seeded relation takes "
                        f"{sx(SEED_SIGS[tid][1])}, got {sx(a['sig'])}")
                    continue
                if tid not in self.g.terms and tid not in new_terms:
                    out.append(["term", tid] + tail)
                    new_terms[tid] = tail
                    continue
                known_tail = new_terms[tid] if tid in new_terms \
                    else self.g.terms[tid]
                known_a = anns(list(known_tail))
                if parsed_sig is not None:
                    known_sig = None
                    if "sig" in known_a:
                        try:
                            known_sig = parse_sig(known_a["sig"])
                        except ValueError:
                            known_sig = None
                    if known_sig is None:
                        merged = _drop_key(list(known_tail), ":sig") \
                            + [":sig", a["sig"]]
                        out.append(["term", tid] + merged)
                        new_terms[tid] = merged
                    elif known_sig != parsed_sig:
                        rejects.append(
                            f"sig conflict for {tid}: registry has "
                            f"{sx(known_a['sig'])}, got {sx(a['sig'])}")
                continue
            if head == "add":
                item = op[1]
                if item[0] == "edge":
                    # canonical: (edge (TYPE A B)); also accept the flat
                    # surface form (edge TYPE A B)
                    if len(item) >= 2 and isinstance(item[1], list):
                        edge_args = item[1]
                    else:
                        edge_args = item[1:]
                    if len(edge_args) > 3 and \
                       isinstance(edge_args[3], str) and \
                       edge_args[3].startswith(":"):
                        edge_args = edge_args[:3]   # drop edge annotations
                    if len(edge_args) != 3:
                        rejects.append(f"malformed edge (expected 3 args, "
                                       f"got {len(edge_args)}): "
                                       f"{sx(edge_args) if isinstance(edge_args, list) else edge_args}")
                        continue
                    et, a, b = edge_args
                    a, b = self._map(a, idmap), self._map(b, idmap)
                    if not isinstance(et, str) or not isinstance(a, str) \
                       or not isinstance(b, str):
                        rejects.append(f"malformed edge (non-string ref)")
                        continue
                    if et not in ETYPES:
                        rejects.append(f"unknown edge type {et}")
                        continue
                    assigned = set(idmap.values())
                    a_ok = a in self.g.nodes or a in assigned
                    b_ok = b in self.g.nodes or b in assigned
                    if et == "about" and not b_ok:
                        b_ok = b in self.g.terms or b in new_terms
                    if not a_ok or not b_ok:
                        rejects.append(f"dangling edge ({et} {a} {b})")
                        continue
                    if et == "motivates" and trouble.is_failure_payload(
                            self.g.nodes[b]["payload"] if b in self.g.nodes
                            else new_payloads.get(b)):
                        rejects.append(f"(motivates {a} {b}): a reason for a "
                                       f"failure is a diagnosis claim "
                                       f"(causes {a} {b})")
                        continue
                    if (et, a, b) in batch_edges or \
                            (et, a, b) in set(self.g.edges):
                        continue  # R11 for edges
                    batch_edges.add((et, a, b))
                    out.append(["add", ["edge", [et, a, b]]])
                    continue
                frame, xid = item[0], item[1]
                if frame not in FRAMES:
                    rejects.append(f"unknown frame {frame}")
                    continue
                need = 4 if frame == "def" else 3
                if len(item) < need or any(
                        isinstance(x, str) and x.startswith(":")
                        for x in item[2:need]):
                    rejects.append(f"node missing payload ({frame} {xid})")
                    continue
                if frame == "def":
                    payload, tail = [item[2], item[3]], item[4:]
                else:
                    payload, tail = _map_payload(item[2], idmap), item[3:]
                if frame == "claim":                # R13 failures
                    is_fail = lambda r: trouble.is_failure_payload(
                        self.g.nodes[r]["payload"] if r in self.g.nodes
                        else new_payloads.get(r))
                    payload, why = trouble.canonical_failure(
                        payload, speakers, is_fail)
                    if why:
                        rejects.append(why)
                        continue
                if frame not in ("def", "artifact") \
                        and isinstance(payload, list) and payload \
                        and isinstance(payload[0], str) \
                        and not isinstance(payload[0], Lit):
                    slots = self._sig(payload[0], new_terms)
                    if slots is not None:
                        why = sig_misfit(payload[0], payload[1:], slots,
                                         provisional=True)
                        if why and len(slots) == 2 and len(payload) == 3:
                            sw = [payload[0], payload[2], payload[1]]
                            if frame == "claim":
                                sw, sw_why = trouble.canonical_failure(
                                    sw, speakers, is_fail)
                                if sw_why is not None:
                                    rejects.append(
                                        f"sig mismatch {sx(payload)}: {why}")
                                    continue
                            if not sig_misfit(payload[0], sw[1:], slots,
                                              provisional=True):
                                self.coercions.append(
                                    f"swapped to sig order: "
                                    f"{sx(payload)} -> {sx(sw)}")
                                payload = sw
                            else:
                                rejects.append(
                                    f"sig mismatch {sx(payload)}: {why}")
                                continue
                        elif why:
                            rejects.append(
                                f"sig mismatch {sx(payload)}: {why}")
                            continue
                a = anns(tail)
                why = _assumed_status(frame, a)
                if why:
                    rejects.append(why)
                    continue
                if "status" in a and a["status"] not in \
                   STATUSES.get(frame, set()):
                    rejects.append(
                        f"off-spec status {a['status']} for {frame}")
                    continue
                if frame == "claim":                # R14 conditionals
                    _, why = self._conditional(payload, a, xid,
                                               idmap, added)
                    if why:
                        rejects.append(why)
                        continue
                key = (frame, sx(payload))
                if key in self.payload_index:      # R11
                    existing = self.payload_index[key]
                    idmap[xid] = existing
                    if existing in self.g.nodes:
                        old_status = self.g.nodes[existing]["status"]
                        if "status" in a and a["status"] != old_status:
                            out.append(["update", existing,
                                        ":status", a["status"]])
                    continue
                nid = self._next_id(frame)
                idmap[xid] = nid
                self.payload_index[key] = nid
                new_frames[nid] = frame
                new_payloads[nid] = payload
                if frame not in ("def", "artifact") \
                        and isinstance(payload, list) and payload \
                        and isinstance(payload[0], str) \
                        and not isinstance(payload[0], Lit):
                    self._seed_relation(payload[0], new_terms, out)
                if frame == "claim" and isinstance(payload, list) and payload:
                    kind = trouble.seeded_kind(payload)
                    if kind and kind not in self.g.terms \
                            and kind not in new_terms:
                        out.append(trouble.kind_term(kind))
                        new_terms[kind] = trouble.kind_term(kind)[2:]
                    if payload[0] == basis.COND \
                            and basis.COND not in self.g.terms \
                            and basis.COND not in new_terms:
                        it = _implies_term()
                        out.append(it)
                        new_terms[basis.COND] = it[2:]
                out.append(["add", self._node_form(frame, nid, payload, a)])
                continue
            if head in ("update", "supersede", "merge", "del"):
                mapped = [head] + [self._map(x, idmap) if isinstance(x, str)
                                   else x for x in op[1:]]
                refs = [x for x in mapped[1:2 if head in ("update", "del")
                                          else 3]
                        if isinstance(x, str) and not x.startswith(":")]
                if head == "del" and isinstance(op[1], list):
                    out.append(op)
                    continue
                bad = [r for r in refs if r not in self.g.nodes
                       and r not in set(idmap.values())]
                if bad:
                    rejects.append(f"{head} of unknown id {' '.join(bad)}")
                    continue
                if head == "update":
                    a = anns(mapped[2:])
                    if "status" in a:
                        frame = self.g.nodes.get(mapped[1], {}).get("frame") \
                            or new_frames.get(mapped[1])
                        why = _assumed_status(frame, a)
                        if why:
                            rejects.append(why)
                            continue
                        if a["status"] not in STATUSES.get(frame, set()):
                            rejects.append(
                                f"off-spec status {a['status']} for {frame}")
                            continue
                    mapped = ["update", mapped[1]]
                    for k in ANN_ORDER:
                        if k in a:
                            mapped += [":" + k, a[k]]
                out.append(mapped)
                continue
            rejects.append(f"unknown op {head}")
        # forward references: a payload naming a node added later in the
        # batch gets its final id now (R8)
        for op in out:
            if op[0] == "add" and op[1][0] not in ("edge", "def"):
                op[1][2] = _map_payload(op[1][2], idmap)
                if op[1][1] in new_payloads:
                    new_payloads[op[1][1]] = op[1][2]
        # R13: a diagnosis holds only while its failure and cause hold
        assigned = set(idmap.values())
        known = lambda r: r in self.g.nodes or r in assigned
        payload_of = lambda r: (self.g.nodes[r]["payload"] if r in self.g.nodes
                                else new_payloads.get(r))
        for nid, pl in list(new_payloads.items()):
            for dst in trouble.diagnosis_grounds(pl, payload_of, known):
                if dst == nid:
                    continue
                e = ("depends", nid, dst)
                if e not in batch_edges and e not in set(self.g.edges):
                    batch_edges.add(e)
                    out.append(["add", ["edge", list(e)]])
        # R14: no vacuous discharge -- a new conditional's consequent
        # rests on its antecedent
        view = _batch_view(self.g, out)
        for nid in new_payloads:
            cond = basis.conditional(view, nid)
            if cond and cond[0] not in basis.grounds_closure(view, cond[1]):
                e = ("depends", cond[1], cond[0])
                view.edges.append(e)
                out.append(["add", ["edge", list(e)]])
        return out, rejects


# ------------------------------------------------------------ orchestrator

def render_delta(turn, ops):
    lines = [f"(delta :turn {turn}"]
    for op in ops:
        lines.append("  " + sx(op) + ("" if op is not ops[-1] else ")"))
    if len(ops) == 0:
        return None
    return "\n".join(lines)


def run(transcript_path, out_path, llm, llm_normalize=True,
        per_turn=False, verbose=True, seed=None, global_kb=None,
        checker=None):
    """Extract the transcript into the log at out_path. `checker`, an
    optional second llm callable, reviews each delta before the procedural
    normalizer commits it."""
    turns = parse_transcript(open(transcript_path).read())
    if not turns:
        sys.exit("no [tN speaker] turns found in transcript")
    g = Graph()
    log_parts = ['(meta :winnow-version "0.2" :semantic-rep "registry-v0.1")']
    if seed:            # continue from a prior log (text of a .wno file)
        for form in parse(tokenize(seed)):
            if form and form[0] == "meta":
                g.set_meta(form)
            elif form:
                g.apply(form)
                log_parts.append(sx(form))

    reach_telemetry = []

    # group turns into triggers
    batches, cur = [], []
    for t in turns:
        cur.append(t)
        if per_turn or t[1] != "user":
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)

    for batch in batches:
        turn_no = batch[-1][0]
        new_text = "\n\n".join(f"[t{n} {who}]\n{txt}"
                               for n, who, txt in batch)
        digest = digest_view.render(g) if g.nodes else "; graph is empty"
        registry = "\n".join(sx(["term", tid] + list(tail))
                             for tid, tail in sorted(g.terms.items())) \
                   or "; registry is empty"

        loose = llm(EXTRACTOR_SYSTEM,
                    f"NOTE GRAPH SO FAR (digest):\n{digest}\n\n"
                    f"NEW TURNS:\n{new_text}")

        # reach handling: pull interface + ladder (spec 10.5). Resolved
        # material triggers one extractor re-pass with the pull results;
        # honest misses become open questions addressed to the human.
        misses, pulls = [], []
        reaches = extract_reaches(loose)
        if reaches:
            resolver = Resolver(g, global_kb=global_kb)
            for q in reaches:
                rung, hits = resolver.resolve(q)
                reach_telemetry.append({
                    "turn": turn_no,
                    "query": [str(t) for t in q],
                    "rung": rung,
                    "hits": list(hits),
                })
                if hits:
                    source = resolver.kb if rung == 4 else resolver.g
                    if rung != 4:
                        for nid in hits:
                            digest_view.promote(g, nid)   # P3, with TTL
                    pulls.append(f"; reach {' '.join(map(str, q))} "
                                 f"-> rung {rung}")
                    pulls += [source._full_line(nid) for nid in hits]
                else:
                    misses.append(q)
            if pulls:
                loose = llm(EXTRACTOR_SYSTEM,
                            f"NOTE GRAPH SO FAR (digest):\n{digest}\n\n"
                            f"PULL RESULTS (your reach queries, resolved):\n"
                            + "\n".join(pulls) +
                            f"\n\nNEW TURNS:\n{new_text}")

        if llm_normalize:
            loose = llm(NORMALIZER_SYSTEM,
                        f"TERM REGISTRY:\n{registry}\n\n"
                        f"CANDIDATE DELTA:\n{loose}")

        if checker:
            pulled = ("PULL RESULTS:\n" + "\n".join(pulls) + "\n\n"
                      if pulls else "")
            loose = checker(CHECKER_SYSTEM,
                            f"NOTE GRAPH SO FAR (digest):\n{digest}\n\n"
                            f"TERM REGISTRY:\n{registry}\n\n"
                            f"{pulled}NEW TURNS:\n{new_text}\n\n"
                            f"CANDIDATE DELTA:\n{loose}")

        forms = extract_forms(loose)
        for i, q in enumerate(misses):            # rung 5: honest miss
            toks = [kebab(t) for t in q if kebab(t)]
            forms.append(["add", ["question", f"xmiss{i}",
                                  ["locate"] + toks,
                                  ":status", "open",
                                  ":by", "orchestrator",
                                  ":src", f"t{turn_no}"]])
        norm = Normalizer(g)
        ops, rejects = norm.normalize(forms)
        for r in rejects:
            print(f"  (reject \"{r}\")", file=sys.stderr)
        for c in norm.coercions:
            print(f"  (coercion \"{c}\")", file=sys.stderr)
        if not ops:
            if verbose:
                print(f"turn {turn_no}: no signal", file=sys.stderr)
            continue
        delta_text = render_delta(turn_no, ops)
        g.apply(parse(tokenize(delta_text))[0])
        log_parts.append(delta_text)
        # write after every batch: an interrupted run strands nothing,
        # the log on disk is always a valid foldable prefix
        with open(out_path, "w") as f:
            f.write("\n\n".join(log_parts) + "\n")
        if verbose:
            print(f"turn {turn_no}: {len(ops)} ops "
                  f"({len(g.nodes)} nodes, {len(g.edges)} edges)",
                  file=sys.stderr)

    with open(out_path, "w") as f:
        f.write("\n\n".join(log_parts) + "\n")
    if reach_telemetry:
        reach_path = re.sub(r"\.wno$", "", out_path) + ".reach"
        with open(reach_path, "w") as f:
            json.dump(reach_telemetry, f, indent=2)
            f.write("\n")
        if verbose:
            past_r1 = sum(1 for r in reach_telemetry if r["rung"] > 1)
            print(f"wrote {reach_path}: {len(reach_telemetry)} reach events "
                  f"({past_r1} past rung 1)", file=sys.stderr)
    errs = g.validate()
    if verbose:
        print(f"wrote {out_path}: {len(g.nodes)} nodes, "
              f"{len(g.edges)} edges, {len(g.terms)} terms; "
              f"validation {'OK' if not errs else errs}", file=sys.stderr)
    return g


BACKEND_DEFAULT_MODELS = {"anthropic": DEFAULT_MODEL, "claude-code": "opus",
                          "deepseek": "flash", "deepseek-anthropic": "flash"}


def backend_client(backend, model, think="max", re2=False):
    """The llm callable for one backend and model, thinking at `think`."""
    if backend == "deepseek":
        return deepseek_client({"pro": "pro"}.get(model, "flash"),
                               re2=re2, think=think)
    if backend == "deepseek-anthropic":
        ds_api_models = {"pro": "deepseek-v4-pro", "flash": "deepseek-flash"}
        return anthropic_client(
            ds_api_models.get(model, model),
            base_url="https://api.deepseek.com/v1",
            api_key_env="DEEPSEEK_API_KEY", effort=think,
            max_tokens=MAX_OUTPUT_TOKENS["deepseek"])
    if backend == "claude-code":
        return claude_code_client(model, effort=think)
    return anthropic_client(model, effort=think)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript")
    ap.add_argument("--out", required=True, help="output .wno log path")
    ap.add_argument("--model",
                    help="extractor model (default per backend: anthropic "
                         f"{DEFAULT_MODEL}, claude-code opus, deepseek "
                         "and deepseek-anthropic flash)")
    ap.add_argument("--backend",
                    choices=["anthropic", "claude-code", "deepseek",
                             "deepseek-anthropic"],
                    default="anthropic",
                    help="LLM backend: anthropic (native SDK), claude-code "
                         "(a `claude -p` subagent, using the local claude's "
                         "login), deepseek (openai-compat), deepseek-anthropic "
                         "(anthropic-compat via DeepSeek)")
    ap.add_argument("--checker", metavar="MODEL",
                    help="a second model on the same backend that checks "
                         "each delta before it's committed; on the Claude "
                         "backends a haiku extractor needs a non-haiku "
                         "checker (sonnet or opus)")
    ap.add_argument("--replay", help="canned-response fixture (offline)")
    ap.add_argument("--per-turn", action="store_true",
                    help="one delta per turn instead of per exchange")
    ap.add_argument("--no-llm-normalizer", action="store_true",
                    help="skip stage-B LLM; procedural enforcement only")
    ap.add_argument("--seed", help="prior .wno log to continue from")
    ap.add_argument("--global-kb",
                    help="mega-fold .wno for rung 4 cross-conversation resolution")
    ap.add_argument("--think", default="max",
                    choices=["off", "low", "high", "max"],
                    help="thinking effort for every backend (default max; "
                         "anything less costs extraction quality)")
    ap.add_argument("--re2", action="store_true",
                    help="deepseek backend: RE2 re-reading, implies "
                         "thinking off (fast non-thinking mode)")
    args = ap.parse_args()

    model = args.model or BACKEND_DEFAULT_MODELS[args.backend]
    if args.replay:
        llm, checker = replay_client(args.replay), None
    else:
        if args.think == "off" and args.backend != "deepseek":
            sys.exit("--think off is for the deepseek backend; the other "
                     "backends always think (use --think low for the least)")
        if args.backend in ("anthropic", "claude-code"):
            err = claude_policy_error(model, args.checker)
            if err:
                sys.exit(f"winnow: {err}")
        llm = backend_client(args.backend, model, args.think, args.re2)
        checker = (backend_client(args.backend, args.checker, args.think,
                                  args.re2) if args.checker else None)
    kb = None
    if args.global_kb:
        kb = Graph()
        for form in parse(tokenize(open(args.global_kb).read())):
            if form and form[0] == "meta":
                kb.set_meta(form)
            elif form:
                kb.apply(form)
        print(f"global KB: {len(kb.nodes)} nodes, {len(kb.terms)} terms",
              file=sys.stderr)
    run(args.transcript, args.out, llm,
        llm_normalize=not args.no_llm_normalizer,
        per_turn=args.per_turn,
        seed=open(args.seed).read() if args.seed else None,
        global_kb=kb, checker=checker)


if __name__ == "__main__":
    main()
