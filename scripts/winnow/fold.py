#!/usr/bin/env python3
"""winnow fold: replay a delta log (.wno) into the full semantic graph.

Fold means exactly this, and nothing else (spec section 7): the graph is
fold(empty, log). Every node stays in it, resolved and superseded ones
included. Reduced renderings of the folded graph are views, each in its
own script:

    frontier.py   what's still open (spec section 9)
    digest.py     the tiered window a model sees: fire/hot/warm/cold (10)
    basis.py      what each conclusion rests on, and whether that holds
    query.py      query, concepts, stale, hashes

`wno.py` is the front door to all of them.

Usage:
    python3 fold.py LOG.wno              # stats + validation
    python3 fold.py LOG.wno --snapshot   # also print the canonical snapshot
    python3 fold.py LOG.wno --upto N     # fold only the first N deltas
    python3 fold.py LOG.wno --yield-curve  # per-delta metrics (TSV)

The old view flags (--frontier, --digest, --query, --hashes, --concepts,
--stale) still work for one release; they forward to the view scripts.
"""
import hashlib
import sys
import re
from collections import Counter

# The reader lives in sexpr.py; re-exported so `from fold import parse`
# keeps working for every caller.
from sexpr import Lit, tokenize, parse, sx, _symbols, anns  # noqa: F401


FRAME_ORDER = ["constraint", "decision", "question", "def",
               "claim", "action", "artifact"]
DEFAULT_STATUS = {
    "claim": "live", "question": "open", "decision": "proposed",
    "constraint": "live", "action": "todo", "def": "live",
    "artifact": "live",
}
FRAMES = set(DEFAULT_STATUS)
ETYPES = {"supports", "contradicts", "supersedes", "refines",
          "answers", "motivates", "depends", "about"}

# Closed status vocabulary per frame (spec section 2). Off-spec values
# are grandfathered in existing logs: fold WARNS, never errors -- see
# Graph.warnings / Graph._check_status.
STATUSES = {
    "claim": {"live", "corrected", "retracted", "superseded"},
    "def": {"live", "deprecated", "superseded"},
    "question": {"open", "answered", "dropped", "superseded"},
    "decision": {"proposed", "frozen", "superseded", "abandoned"},
    "constraint": {"live", "relaxed", "retired", "superseded"},
    "action": {"todo", "doing", "done", "blocked", "dropped", "superseded"},
    "artifact": {"live", "deprecated", "superseded"},
}
ANN_ORDER = ["status", "conf", "status-conf", "strength", "by",
             "src", "time", "modal", "neg"]

# Cooling-profile defaults = the human default profile (spec 10.4).
# The fold only records them from the meta header; digest.py and the
# orchestrator act on them.
PROFILE_DEFAULTS = {
    "tail": 6,            # recent live claims/defs the digest keeps hot
    "fire-hops": 1,       # forward-projection radius from touched nodes
    "protect": ETYPES,    # edge types the demotion invariant counts
    "promotion-ttl": 2,   # deltas a reach-promotion survives untouched
    "widening-base": 3,   # rung-2 widening: base, base^2, base^3
}

# Usage mass is derived and map-side (like tier state): never logged,
# excluded from equivalence, orders retrieval only — never window
# residency. References from these statuses don't count toward mass.
MASS_GATE = {"superseded", "rejected", "retracted"}


# ---------------------------------------------------------------- graph

class Graph:
    def __init__(self):
        self.nodes = {}     # id -> dict
        self.edges = []     # (etype, src, dst)
        self.terms = {}     # termid -> tail
        self.errors = []
        self.warnings = []  # advisory: off-spec statuses (never fail fold)
        self.deltas = 0
        self.turn = 0
        self.meta = {}
        self.profile = dict(PROFILE_DEFAULTS)
        self.touched = set()   # node ids touched by the most recent delta
        self.last_touch = {}   # nid -> delta index of most recent touch
        self.delta_turns = []  # the :turn each applied delta carried, in order
        # P3 reach promotions, nid -> delta index they expire at. Written by
        # digest.promote, read by digest.tiers; the fold never touches them.
        self.promotions = {}

    # -- header ------------------------------------------------------
    def set_meta(self, form):
        self.meta = anns(form[1:])
        prof = self.meta.get("profile")
        if isinstance(prof, list):
            for k, v in anns(prof).items():
                if k == "protect":
                    self.profile[k] = set(v) if isinstance(v, list) else {v}
                else:
                    self.profile[k] = int(v)

    # -- ops ---------------------------------------------------------
    def apply(self, delta):
        assert delta[0] == "delta", "top-level form must be (delta ...)"
        self.deltas += 1
        head_anns = anns(delta[1:3])
        if "turn" in head_anns:
            self.turn = head_anns["turn"]
        self.delta_turns.append(self.turn)
        self.touched = set()
        for op in (x for x in delta[1:] if isinstance(x, list)):
            head = op[0]
            if head == "term":
                self.terms[op[1]] = op[2:]
            elif head == "add":
                self._add(op[1])
            elif head == "update":
                nid = op[1]
                if nid not in self.nodes:
                    self.errors.append(f"update of unknown id {nid}")
                    continue
                updates = anns(op[2:])
                self.nodes[nid].update(updates)
                self.touched.add(nid)
                if "status" in updates:
                    self._check_status(self.nodes[nid]["frame"], nid,
                                       updates["status"])
            elif head == "supersede":            # (supersede NEW OLD ...)
                new, old = op[1], op[2]
                a = anns(op[3:])
                if old not in self.nodes:
                    self.errors.append(f"supersede of unknown id {old}")
                    continue
                self.nodes[old]["status"] = "superseded"
                self._check_status(self.nodes[old]["frame"], old, "superseded")
                if "conf" in a:
                    self.nodes[old]["status-conf"] = a["conf"]
                self._edge("supersedes", new, old)
            elif head == "merge":                # (merge LOSER WINNER)
                loser, winner = op[1], op[2]
                self.edges = [
                    (t,
                     winner if s == loser else s,
                     winner if d == loser else d)
                    for t, s, d in self.edges]
                self.nodes.pop(loser, None)
                self.touched.discard(loser)
                self.touched.add(winner)
            elif head == "del":
                tgt = op[1]
                if isinstance(tgt, list):        # (del (edge (t a b)))
                    t, a, b = tgt[1]
                    try:
                        self.edges.remove((t, a, b))
                    except ValueError:
                        self.errors.append(f"del of missing edge {sx(tgt)}")
                else:
                    self.nodes.pop(tgt, None)
                    self.edges = [e for e in self.edges
                                  if tgt not in (e[1], e[2])]
                    self.touched.discard(tgt)
            else:
                self.errors.append(f"unknown op {head}")
        for nid in self.touched:
            self.last_touch[nid] = self.deltas

    def _add(self, item):
        if item[0] == "edge":
            et, a, b = item[1]
            self._edge(et, a, b)
            return
        frame, nid = item[0], item[1]
        if frame not in FRAMES:
            self.errors.append(f"unknown frame {frame}")
        if nid in self.nodes:
            self.errors.append(f"duplicate add {nid}")
        if frame == "def":                       # (def id termid "gloss" ...)
            payload = [item[2], item[3]]
            tail = item[4:]
        else:
            payload = item[2]
            tail = item[3:]
        node = {"frame": frame, "payload": payload,
                "status": DEFAULT_STATUS.get(frame, "live")}
        node.update(anns(tail))
        self.nodes[nid] = node
        self.touched.add(nid)
        self._check_status(frame, nid, node["status"])

    def _check_status(self, frame, nid, status):
        """Off-spec status (spec §2) is advisory, not fatal: warn and
        keep going. Grandfathers existing runs/sessions logs."""
        legal = STATUSES.get(frame)
        if legal and status not in legal:
            self.warnings.append(
                f"off-spec status '{status}' for {frame} {nid}")

    def _edge(self, et, a, b):
        if et not in ETYPES:
            self.errors.append(f"unknown edge type {et}")
        self.edges.append((et, a, b))
        self.touched.update((a, b))              # promotion trigger P2

    # -- checks ------------------------------------------------------
    def validate(self):
        for t, a, b in self.edges:
            for x in (a, b):
                if x not in self.nodes:
                    if t == "about" and x == b and x in self.terms:
                        continue
                    self.errors.append(f"dangling ref {x} in ({t} {a} {b})")
        return self.errors

    def touched_at_turn(self, nid):
        """The turn of the delta that last touched nid, or None."""
        i = self.last_touch.get(nid)
        return self.delta_turns[i - 1] if i else None

    def undeclared_terms(self):
        """Terms referenced structurally but never declared.
        Checks: about-edge targets that are term-like (not node ids),
        and def-frame payloads whose term id isn't registered."""
        undeclared = set()
        for t, a, b in self.edges:
            if t == "about" and b not in self.nodes and b not in self.terms:
                undeclared.add(b)
        for nid, n in self.nodes.items():
            if n["frame"] == "def":
                tid = n["payload"][0] if isinstance(n["payload"], list) else None
                if tid and tid not in self.terms:
                    undeclared.add(tid)
        return sorted(undeclared)

    # -- shared rendering (used by every view) -------------------------
    def _node_key(self, nid):
        f = self.nodes[nid]["frame"]
        num = int(re.sub(r"\D", "", nid) or 0)
        return (FRAME_ORDER.index(f) if f in FRAME_ORDER else 99, num)

    def _payload_line(self, nid):
        n = self.nodes[nid]
        parts = ([n["frame"], nid] + list(n["payload"])
                 if n["frame"] == "def" else [n["frame"], nid, n["payload"]])
        return sx(parts)

    def _full_line(self, nid):
        n = self.nodes[nid]
        parts = [n["frame"], nid]
        pl = n["payload"]
        parts += pl if n["frame"] == "def" else [pl]
        for k in ANN_ORDER:
            if k in n:
                parts += [":" + k, n[k]]
        return sx(parts)

    # -- the graph itself, serialized ----------------------------------
    def snapshot(self):
        """The whole folded graph as canonical s-exprs (spec §7
        compaction: the log rewritten as pure adds)."""
        lines = []
        for tid in sorted(self.terms):
            lines.append(sx(["term", tid] + list(self.terms[tid])))
        for nid in sorted(self.nodes, key=self._node_key):
            lines.append(self._full_line(nid))
        for e in sorted(self.edges):
            lines.append(sx(["edge", list(e)]))
        return "\n".join(lines)

    # -- usage mass (derived, map-side; spec: retrieval ordering only) --
    def term_usage(self):
        """termid -> [node ids whose payload references the term]."""
        usage = {tid: [] for tid in self.terms}
        for nid in sorted(self.nodes, key=self._node_key):
            for s in set(_symbols(self.nodes[nid]["payload"])):
                if s in usage:
                    usage[s].append(nid)
        return usage

    def term_mass(self):
        """termid -> status-gated reference count. Never logged, never
        drives residency; orders retrieval (Resolver ranking, concepts)."""
        return {tid: sum(1 for nid in nids
                         if self.nodes[nid]["status"] not in MASS_GATE)
                for tid, nids in self.term_usage().items()}

    def node_mass(self, nid):
        """Node analog of usage mass: status-gated incident edge count."""
        m = 0
        for _, a, b in self.edges:
            other = b if a == nid else a if b == nid else None
            if other is not None and other in self.nodes and \
                    self.nodes[other]["status"] not in MASS_GATE:
                m += 1
        return m

    # -- identity --------------------------------------------------------
    def hash_id(self, nid, _stack=frozenset()):
        """Content-hash id prototype (docs/hash-ids.md): sha256 over
        (frame, canonical payload) with node-id args resolved to their
        own hashes recursively; cycles collapse to a marker."""
        if nid in _stack:
            return "cycle"
        n = self.nodes[nid]

        def rs(v):
            if isinstance(v, list):
                return "(" + " ".join(rs(x) for x in v) + ")"
            if isinstance(v, Lit):
                return '"' + str(v) + '"'
            s = str(v)
            if s in self.nodes and s != nid:
                return "#" + self.hash_id(s, _stack | {nid})
            return s

        canon = n["frame"] + " " + rs(n["payload"])
        return hashlib.sha256(canon.encode()).hexdigest()[:12]

    # -- stats -----------------------------------------------------------
    def stats_dict(self):
        """Structured metrics for yield-curve collection."""
        by_frame = Counter(n["frame"] for n in self.nodes.values())
        by_et = Counter(t for t, _, _ in self.edges)
        snap_len = len(self.snapshot())
        return {
            "deltas": self.deltas,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "terms": len(self.terms),
            "edges_per_node": (len(self.edges) / len(self.nodes)
                               if self.nodes else 0),
            "frames": dict(by_frame),
            "edge_types": dict(by_et),
            "edge_types_used": len(by_et),
            "snapshot_chars": snap_len,
            "snapshot_tokens_approx": snap_len // 4,
        }

    def stats(self):
        out = []
        log_id = self.meta.get("log-id")
        if log_id:
            out.append(f"log-id         : {log_id}")
        receives = self.meta.get("receives")
        if receives:
            if isinstance(receives, list):
                out.append(f"receives       : {len(receives)} ancestor(s)")
                for r in receives:
                    out.append(f"  - {r}")
            else:
                out.append(f"receives       : {receives}")
        out += [f"deltas applied : {self.deltas}",
                f"nodes          : {len(self.nodes)}",
                f"edges          : {len(self.edges)}",
                f"terms          : {len(self.terms)}"]
        by_frame = Counter(n["frame"] for n in self.nodes.values())
        for f in FRAME_ORDER:
            if by_frame[f]:
                st = Counter(n["status"] for n in self.nodes.values()
                             if n["frame"] == f)
                st_txt = " ".join(f"{k}={v}" for k, v in sorted(st.items()))
                out.append(f"  {f:<10} {by_frame[f]:>3}   ({st_txt})")
        by_et = Counter(t for t, _, _ in self.edges)
        out.append("  edge types     " +
                   " ".join(f"{k}={v}" for k, v in sorted(by_et.items())))
        snap = self.snapshot()
        out.append(f"snapshot size  : {len(snap)} chars "
                   f"(~{len(snap) // 4} tokens)")
        undecl = self.undeclared_terms()
        dangles = [e for e in self.errors if "dangling" in e]
        if undecl or dangles:
            out.append(f"gaps           : {len(undecl)} undeclared term(s), "
                       f"{len(dangles)} dangling ref(s)")
            if undecl:
                out.append(f"  terms  : {', '.join(undecl)}")
            if dangles:
                for d in dangles:
                    out.append(f"  ref    : {d}")
            if receives:
                out.append("  (likely inherited from declared ancestors)")
        return "\n".join(out)


# ---------------------------------------------------------------- fold

def fold(text, upto=None):
    """fold(empty, log): the graph a log's text describes.

    Meta forms set the header; the first `upto` deltas are applied (all
    when None). Call validate() on the result for reference checks.
    """
    g = Graph()
    applied = 0
    for form in parse(tokenize(text)):
        if form and form[0] == "meta":
            g.set_meta(form)
            continue
        if upto is not None and applied >= upto:
            break
        g.apply(form)
        applied += 1
    return g


def load(path, upto=None):
    """fold() over a file."""
    with open(path) as f:
        return fold(f.read(), upto)


def flag_value(argv, flag, default=None):
    """The word after `flag` in argv, or `default`."""
    if flag in argv and argv.index(flag) + 1 < len(argv):
        return argv[argv.index(flag) + 1]
    return default


# ---------------------------------------------------------------- main

# Old view flags, kept one release: flag -> (module, how to call it)
_FORWARDED = {
    "--frontier": "frontier.py",
    "--digest": "digest.py",
    "--query": "query.py",
    "--hashes": "query.py --hashes",
    "--concepts": "query.py --concepts",
    "--stale": "query.py --stale",
}


def _forward(argv, g):
    """Serve a deprecated view flag; True if one was handled."""
    flag = next((f for f in _FORWARDED if f in argv), None)
    if not flag:
        return False
    target = _FORWARDED[flag]
    print(f"fold.py {flag} is deprecated and goes away next release: "
          f"use {target} (or wno.py {target.replace('.py', '')})",
          file=sys.stderr)
    import frontier
    import digest
    import query
    if flag == "--frontier":
        print(frontier.render(g))
    elif flag == "--digest":
        print(digest.render(g))
    elif flag == "--query":
        print(query.query(g, flag_value(argv, "--query", "")))
    elif flag == "--hashes":
        print(query.hashes(g))
    elif flag == "--concepts":
        print(query.concepts(g))
    elif flag == "--stale":
        n = flag_value(argv, "--stale")
        print(query.stale(g, int(n) if n and n.isdigit() else 3))
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        sys.exit(1)
    upto = flag_value(argv, "--upto")
    with open(argv[0]) as f:
        text = f.read()
    g = fold(text, int(upto) if upto is not None else None)
    errs = g.validate()
    if _forward(argv, g):
        return
    if "--yield-curve" in argv:
        print("delta\tnodes\tedges\tterms\tedges/node\tet_used\tsnap_chars")
        gc = Graph()
        for form in parse(tokenize(text)):
            if form and form[0] == "meta":
                gc.set_meta(form)
                continue
            gc.apply(form)
            d = gc.stats_dict()
            print(f"{d['deltas']}\t{d['nodes']}\t{d['edges']}\t"
                  f"{d['terms']}\t{d['edges_per_node']:.2f}\t"
                  f"{d['edge_types_used']}\t{d['snapshot_chars']}")
        return
    print(g.stats())
    print("validation     :",
          "OK" if not errs else f"{len(errs)} problem(s)")
    for e in errs:
        print("  !", e)
    if g.warnings:
        print(f"status warnings : {len(g.warnings)}")
        for w in g.warnings:
            print("  !", w)
    if "--snapshot" in argv:
        print("\n; --- canonical snapshot ---")
        print(g.snapshot())


if __name__ == "__main__":
    main()
