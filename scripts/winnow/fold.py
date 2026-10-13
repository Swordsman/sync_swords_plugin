#!/usr/bin/env python3
"""winnow v0.2 reference implementation.

Parse an s-expression delta log (.wno), fold it into a materialized
semantic graph, validate references, print stats, and render views:
the canonical snapshot, the v0.1 frontier digest, or the v0.2 tiered
immediate context window (spec section 10).

Usage:
    python3 fold.py LOG.wno            # stats + validation
    python3 fold.py LOG.wno --snapshot # also print canonical snapshot
    python3 fold.py LOG.wno --frontier # v0.1 frontier digest
    python3 fold.py LOG.wno --digest   # v0.2 tiered window
    python3 fold.py LOG.wno --upto N   # fold only the first N deltas
    python3 fold.py LOG.wno --query "frame=claim status=live by=user"
    python3 fold.py LOG.wno --hashes   # content-hash id table (docs/hash-ids.md)
    python3 fold.py LOG.wno --concepts # terms by status-gated usage mass
    python3 fold.py LOG.wno --stale N  # open/proposed/doing untouched N deltas
    python3 fold.py LOG.wno --yield-curve  # per-delta metrics (TSV)
"""
import hashlib
import sys
import re
from collections import Counter


class Lit(str):
    """Quoted string literal (as opposed to a bare symbol)."""


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
# promotion-ttl and widening-base are declared knobs consumed by an
# orchestrator; the static fold records but does not act on them.
PROFILE_DEFAULTS = {
    "tail": 6,            # recent live claims/defs kept hot
    "fire-hops": 1,       # forward-projection radius from touched nodes
    "protect": ETYPES,    # edge types the demotion invariant counts
    "promotion-ttl": 2,   # deltas a reach-promotion survives untouched
    "widening-base": 3,   # rung-2 widening: base, base^2, base^3
}

# Usage mass is derived and map-side (like tier state): never logged,
# excluded from equivalence, orders retrieval only — never window
# residency. References from these statuses don't count toward mass.
MASS_GATE = {"superseded", "rejected", "retracted"}


# ---------------------------------------------------------------- parsing

def tokenize(src):
    toks, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == ";":                            # comment to end of line
            while i < n and src[i] != "\n":
                i += 1
        elif c.isspace():
            i += 1
        elif c in "()":
            toks.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 1
            toks.append(Lit(src[i + 1:j]))
            i = j + 1
        else:
            j = i
            while j < n and not src[j].isspace() and src[j] not in '()"':
                j += 1
            toks.append(src[i:j])
            i = j
    return toks


def parse(toks):
    pos = 0

    def rd():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            out = []
            while toks[pos] != ")":
                out.append(rd())
            pos += 1
            return out
        return t

    forms = []
    while pos < len(toks):
        forms.append(rd())
    return forms


def sx(v):
    """Serialize a parsed value back to canonical s-expr text."""
    if isinstance(v, list):
        return "(" + " ".join(sx(x) for x in v) + ")"
    if isinstance(v, Lit):
        return '"' + str(v) + '"'
    return str(v)


def _symbols(v):
    """Flatten a payload to its bare symbols (for term queries)."""
    if isinstance(v, list):
        return [s for x in v for s in _symbols(x)]
    return [] if isinstance(v, Lit) else [str(v)]


def anns(rest):
    """Collect :key value pairs from a tail; ignore anything else."""
    d, i = {}, 0
    while i < len(rest):
        k = rest[i]
        if isinstance(k, str) and not isinstance(k, Lit) and k.startswith(":"):
            d[k[1:]] = rest[i + 1]
            i += 2
        else:
            i += 1
    return d


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
        self.promotions = {}   # nid -> deltas remaining (P3 reach promotion)
        self.last_touch = {}   # nid -> delta index of most recent touch

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
        self.touched = set()
        self.promotions = {nid: left - 1 for nid, left
                           in self.promotions.items() if left > 1}
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

    # -- shared rendering --------------------------------------------
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

    # -- views -------------------------------------------------------
    def snapshot(self):
        lines = []
        for tid in sorted(self.terms):
            lines.append(sx(["term", tid] + list(self.terms[tid])))
        for nid in sorted(self.nodes, key=self._node_key):
            lines.append(self._full_line(nid))
        for e in sorted(self.edges):
            lines.append(sx(["edge", list(e)]))
        return "\n".join(lines)

    def _frontier_ids(self):
        keep_status = {"constraint": {"live"}, "decision": {"proposed"},
                       "question": {"open"}, "action": {"todo", "doing",
                                                        "blocked"}}
        ids = [nid for nid, n in self.nodes.items()
               if n["status"] in keep_status.get(n["frame"], set())]
        claims = [nid for nid, n in self.nodes.items()
                  if n["frame"] in ("claim", "def") and n["status"] == "live"]
        ids += claims[-int(self.profile["tail"]):]
        return list(dict.fromkeys(ids))

    def frontier(self):
        """The v0.1 digest: everything actionable + recent tail."""
        ids = self._frontier_ids()
        dormant = len(self.nodes) - len(ids)
        lines = [self._payload_line(i) for i in ids]
        lines.append(f"; +{dormant} dormant nodes (resolved/superseded), "
                     f"full graph on request")
        return "\n".join(lines)

    def promote(self, nid):
        """P3: a reach query resolved to nid -> fire with transient TTL
        (spec 10.3). Called by the orchestrator, never by the fold."""
        if nid in self.nodes:
            self.promotions[nid] = int(self.profile["promotion-ttl"])

    def tiers(self):
        """fire/hot/warm/cold per spec section 10; pure function of
        (log, profile) plus transient P3 promotions. Never logged,
        excluded from equivalence."""
        protect = self.profile["protect"]
        adj = {}
        for t, a, b in self.edges:
            if t in protect:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
        fire = {i for i in self.touched | set(self.promotions)
                if i in self.nodes}
        for _ in range(int(self.profile["fire-hops"])):
            fire |= {nb for i in fire for nb in adj.get(i, ())
                     if nb in self.nodes}
        hot = [i for i in self._frontier_ids() if i not in fire]
        resident = fire | set(hot)
        warm = [nid for nid in self.nodes if nid not in resident
                and any(nb in resident for nb in adj.get(nid, ()))]
        cold = [nid for nid in self.nodes
                if nid not in resident and nid not in warm]
        return fire, hot, warm, cold

    def _holding_edge(self, nid, resident):
        for t, a, b in self.edges:
            if a == nid and b in resident or b == nid and a in resident:
                return t, a, b
        return None

    def digest(self):
        """The v0.2 immediate context window (push side): side-effect
        state, fire in full, hot as payloads, warm as stubs, cold count.
        Pull results and promotion TTLs belong to an orchestrator."""
        fire, hot, warm, cold = self.tiers()
        p = self.profile
        prot = ("all" if p["protect"] == ETYPES
                else ",".join(sorted(p["protect"])))
        lines = [
            f"; digest @ turn {self.turn} -- derived, ephemeral, never logged",
            f"; profile: tail={p['tail']} fire-hops={p['fire-hops']} "
            f"promotion-ttl={p['promotion-ttl']} "
            f"widening-base={p['widening-base']} protect={prot}",
            f"; side-effect state: {len(self.terms)} terms (registry travels "
            f"with log); live hard constraints render hot",
            "; --- fire: last exchange + projection ---",
        ]
        lines += [self._full_line(i) for i in sorted(fire, key=self._node_key)]
        lines.append("; --- hot: frontier ---")
        lines += [self._payload_line(i) for i in sorted(hot,
                                                        key=self._node_key)]
        lines.append("; --- warm: dormant, edge-held by residents ---")
        resident = fire | set(hot)
        for nid in sorted(warm, key=self._node_key):
            n = self.nodes[nid]
            held = self._holding_edge(nid, resident)
            via = f" held-by ({held[0]} {held[1]} {held[2]})" if held else ""
            lines.append(f"; {self._payload_line(nid)} "
                         f":status {n['status']}{via}")
        lines.append(f"; --- cold: {len(cold)} nodes, log-resident; "
                     f"(reach QUERY) to promote ---")
        return "\n".join(lines)

    def query_ids(self, expr):
        """Trivial query layer (spec 12): space-separated key=value pairs
        over (frame, status, term, by, src). term matches any symbol
        appearing in the payload. Returns matching node ids."""
        crit = dict(p.split("=", 1) for p in expr.split())
        out = []
        for nid in sorted(self.nodes, key=self._node_key):
            n = self.nodes[nid]
            ok = True
            for k, v in crit.items():
                if k == "term":
                    ok = v in _symbols(n["payload"])
                elif k == "src":
                    val = n.get("src")
                    ok = (v == val or
                          (isinstance(val, list) and v in val))
                else:
                    ok = str(n.get(k)) == v
                if not ok:
                    break
            if ok:
                out.append(nid)
        return out

    def query(self, expr):
        return "\n".join(self._full_line(i) for i in self.query_ids(expr))

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
        drives residency; orders retrieval (Resolver ranking, --concepts)."""
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

    def concepts(self):
        """--concepts: registry sorted by usage mass (desc), then id."""
        usage, mass = self.term_usage(), self.term_mass()
        lines = []
        for tid in sorted(self.terms, key=lambda t: (-mass[t], t)):
            refs = usage[tid]
            gloss = anns(list(self.terms[tid])).get("gloss", "")
            g = str(gloss)
            lines.append(f"{tid:<24} mass={mass[tid]:<3} "
                         f"refs={len(refs):<3} "
                         f"{g[:60]}{'...' if len(g) > 60 else ''}")
        return "\n".join(lines)

    def stale(self, min_age=3):
        """--stale: open questions, proposed decisions, doing actions
        untouched for at least min_age deltas. Maintenance surface, not
        residency input."""
        want = {("question", "open"), ("decision", "proposed"),
                ("action", "doing")}
        lines = []
        for nid in sorted(self.nodes, key=self._node_key):
            n = self.nodes[nid]
            if (n["frame"], n["status"]) not in want:
                continue
            age = self.deltas - self.last_touch.get(nid, 0)
            if age >= min_age:
                lines.append(f"; stale {age:>3} deltas: "
                             f"{self._payload_line(nid)} :status {n['status']}")
        return "\n".join(lines) if lines else "; no stale nodes"

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

    def hashes(self):
        lines = []
        for nid in sorted(self.nodes, key=self._node_key):
            lines.append(f"{nid:<4} {self.hash_id(nid)}  "
                         f"{self._payload_line(nid)}")
        return "\n".join(lines)

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


# ---------------------------------------------------------------- main

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        forms = parse(tokenize(f.read()))
    upto = (int(sys.argv[sys.argv.index("--upto") + 1])
            if "--upto" in sys.argv else None)
    g = Graph()
    applied = 0
    for form in forms:
        if form and form[0] == "meta":
            g.set_meta(form)
            continue
        if upto is not None and applied >= upto:
            break
        g.apply(form)
        applied += 1
    errs = g.validate()
    if "--frontier" in sys.argv:
        print(g.frontier())
        return
    if "--digest" in sys.argv:
        print(g.digest())
        return
    if "--query" in sys.argv:
        print(g.query(sys.argv[sys.argv.index("--query") + 1]))
        return
    if "--hashes" in sys.argv:
        print(g.hashes())
        return
    if "--concepts" in sys.argv:
        print(g.concepts())
        return
    if "--stale" in sys.argv:
        i = sys.argv.index("--stale")
        n = (int(sys.argv[i + 1])
             if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else 3)
        print(g.stale(n))
        return
    if "--yield-curve" in sys.argv:
        print("delta\tnodes\tedges\tterms\tedges/node\tet_used\tsnap_chars")
        gc = Graph()
        for form in forms:
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
    if "--snapshot" in sys.argv:
        print("\n; --- canonical snapshot ---")
        print(g.snapshot())


if __name__ == "__main__":
    main()
