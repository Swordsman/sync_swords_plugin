#!/usr/bin/env python3
"""winnow v0.2 streaming extraction orchestrator (spec section 9).

Drives the core loop over a turn-tagged transcript:

    turns -> extractor (loose, LLM) -> normalizer (strict) -> delta -> log

The extractor sees only the tiered digest (fold.py, spec section 10) plus
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

from fold import Graph, parse, tokenize, sx, anns, ETYPES, FRAMES, STATUSES

ID_PREFIX = {"claim": "c", "decision": "d", "question": "q",
             "constraint": "k", "def": "f", "action": "a", "artifact": "r"}
ANN_ORDER = ["status", "conf", "status-conf", "strength", "by",
             "src", "time", "modal", "neg"]
DEFAULT_MODEL = "claude-opus-4-8"

EXTRACTOR_SYSTEM = """\
You're taking working notes on a live conversation, for a future reader \
with zero patience for transcript archaeology -- probably us, later. You \
get two things: the note graph so far (just the live frontier), and the \
newest turns.

Jot what changed, as winnow delta ops -- new claims, decisions, \
constraints, questions, definitions, actions, and links between them. \
Loose syntax is fine; a normalizer cleans up after you. What matters:

- capture every commitment, correction, requirement, and open thread
- when someone's joking, keep the payload, drop the joke
- when someone takes a position on material they read or were given, \
note the stance -- the verdict outranks the summary
- if something restates what's already in the graph, skip it
- if a new statement kills or changes an old node, say so (update / supersede)
- attribute everything: who said it (:by), which turn (:src)
- unsure? include it with low :conf rather than dropping it

Never note: greetings, filler, vibes, meta-chatter about the conversation \
itself.

The vocabulary (loose phrasing welcome, but stay inside it):
- node frames: claim, question, decision, constraint, def, action, artifact
- links, always exactly (type from to): supports, contradicts, \
supersedes (new old), refines (detail parent), answers (x question), \
motivates (reason thing), depends (x y), about (x topic)
Eight link types, no others. A relationship that doesn't fit is content, \
not a link -- put it inside a node's proposition instead, e.g. \
(add (claim x3 (maps-to subthread original-messages) :by user :src t7)).

Emit ops as s-expressions, one per line, e.g.:
(term some-term :gloss "what it means, not just the name expanded" :canon "Wikipedia_Article_Title")
(add (claim x1 (relation subj obj) :by user :src t3))
(add (edge (supports x1 x2)))
(update q2 :status answered)
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

Legal statuses per frame, nothing else: claim live/corrected/retracted/\
superseded; def live/deprecated/superseded; question open/answered/\
dropped/superseded; decision proposed/frozen/superseded/abandoned; \
constraint live/relaxed/retired/superseded; action todo/doing/done/\
blocked/dropped/superseded; artifact live/deprecated/superseded.

Edge types (only these eight), always exactly (TYPE FROM TO), no extra \
args: supports (evidence first), contradicts (challenger first), \
supersedes (new first), refines (detail first), answers (answer first, \
question second), motivates (reason first), depends (dependent first), \
about (node first, topic/node/term second -- about is the one edge \
whose target may be a term id instead of a node id). \
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
R3 slot order fixed: agent/subject/source first, patient/object/target \
second.
R4 tense, modality, polarity -> annotations (:time :modal :neg), never \
new relations or terms.
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
reduce to their payload proposition; phatic content reduces to nothing.
R11 identical canonical payloads within the delta collapse to one node \
(graph-level dedup runs after you).
R12 numbers/units stay literal; prose quantities normalize ("seventy km" \
-> "70km").

Op syntax, exactly:
(term ID :gloss "..." :canon "Wikipedia_Article_Title")
(add (FRAME ID PAYLOAD :anns...))
(add (edge (TYPE FROM TO)))
(update ID :key val)
(supersede NEW OLD)

Every node keeps :by (speaker) and :src (tN). An op you cannot \
canonicalize becomes (reject "reason"). Output ops only."""


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

def anthropic_client(model, base_url=None, api_key_env=None):
    import anthropic, os
    kwargs = {}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key_env:
        kwargs["api_key"] = os.environ[api_key_env]
    client = anthropic.Anthropic(**kwargs)

    def call(system, user):
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    return call


def deepseek_client(model="flash", ds_path=None, retries=3, re2=False):
    import subprocess, os, time
    if ds_path is None:
        ds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds")
    re2_args = ["--re2", "paper"] if re2 else []

    def call(system, user):
        last_err = None
        for attempt in range(retries):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                result = subprocess.run(
                    [ds_path, "--persist", "no", "-m", model,
                     "--timeout", "120", "-q", *re2_args,
                     "--system", system, user],
                    capture_output=True, text=True, timeout=600,
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
    "todo": 0,
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
        fire, hot, warm, cold = self.g.tiers()
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
                    out.append(form[1:])
        except (IndexError, AssertionError):
            continue
    return out


class Normalizer:
    """Procedural stage-B enforcement: serial ids (R8), dedup (R11),
    annotation order (R7), reference validation. Semantic normalization
    (R1-R6, R9-R12) is the upstream LLM pass's job; everything here holds
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

    def normalize(self, forms):
        """Return (canonical_ops, rejects). canonical_ops are parsed
        forms ready to serialize into one delta."""
        out, rejects, idmap = [], [], {}
        new_frames = {}   # nid assigned this batch -> frame (for update
                           # ops that target a node added earlier in it)
        new_terms = set()  # term ids declared this batch
        for op in forms:
            head = op[0]
            if head == "term":
                if op[1] not in self.g.terms:
                    out.append(op)
                    new_terms.add(op[1])
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
                    if ("edge", et, a, b) in {("edge", t, s, d)
                                              for t, s, d in self.g.edges}:
                        continue  # R11 for edges
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
                    payload, tail = item[2], item[3:]
                a = anns(tail)
                if "status" in a and a["status"] not in \
                   STATUSES.get(frame, set()):
                    rejects.append(
                        f"off-spec status {a['status']} for {frame}")
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
        per_turn=False, verbose=True, seed=None, global_kb=None):
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
        digest = g.digest() if g.nodes else "; graph is empty"
        registry = "\n".join(sx(["term", tid] + list(tail))
                             for tid, tail in sorted(g.terms.items())) \
                   or "; registry is empty"

        loose = llm(EXTRACTOR_SYSTEM,
                    f"NOTE GRAPH SO FAR (digest):\n{digest}\n\n"
                    f"NEW TURNS:\n{new_text}")

        # reach handling: pull interface + ladder (spec 10.5). Resolved
        # material triggers one extractor re-pass with the pull results;
        # honest misses become open questions addressed to the human.
        misses = []
        reaches = extract_reaches(loose)
        if reaches:
            resolver = Resolver(g, global_kb=global_kb)
            pulls = []
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
                            g.promote(nid)         # P3, with TTL
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript")
    ap.add_argument("--out", required=True, help="output .wno log path")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--backend",
                    choices=["anthropic", "deepseek", "deepseek-anthropic"],
                    default="anthropic",
                    help="LLM backend: anthropic (native), deepseek (openai-compat), "
                         "deepseek-anthropic (anthropic-compat via DeepSeek)")
    ap.add_argument("--replay", help="canned-response fixture (offline)")
    ap.add_argument("--per-turn", action="store_true",
                    help="one delta per turn instead of per exchange")
    ap.add_argument("--no-llm-normalizer", action="store_true",
                    help="skip stage-B LLM; procedural enforcement only")
    ap.add_argument("--seed", help="prior .wno log to continue from")
    ap.add_argument("--global-kb",
                    help="mega-fold .wno for rung 4 cross-conversation resolution")
    ap.add_argument("--re2", action="store_true",
                    help="deepseek backend: RE2 re-reading, implies "
                         "thinking off (fast non-thinking mode)")
    args = ap.parse_args()

    DS_MODELS = {"pro": "pro", "flash": "flash"}
    if args.replay:
        llm = replay_client(args.replay)
    elif args.backend == "deepseek":
        llm = deepseek_client(DS_MODELS.get(args.model, "flash"),
                              re2=args.re2)
    elif args.backend == "deepseek-anthropic":
        ds_api_models = {"pro": "deepseek-v4-pro", "flash": "deepseek-v4-flash"}
        llm = anthropic_client(
            ds_api_models.get(args.model, args.model),
            base_url="https://api.deepseek.com/v1",
            api_key_env="DEEPSEEK_API_KEY")
    else:
        llm = anthropic_client(args.model)
    kb = None
    if args.global_kb:
        kb = Graph()
        for form in parse(tokenize(open(args.global_kb).read())):
            if form and form[0] == "meta":
                kb.set_meta(form)
            elif form:
                kb.apply(form)
        if verbose:
            print(f"global KB: {len(kb.nodes)} nodes, {len(kb.terms)} terms",
                  file=sys.stderr)
    run(args.transcript, args.out, llm,
        llm_normalize=not args.no_llm_normalizer,
        per_turn=args.per_turn,
        seed=open(args.seed).read() if args.seed else None,
        global_kb=kb)


if __name__ == "__main__":
    main()
