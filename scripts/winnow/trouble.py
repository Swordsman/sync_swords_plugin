#!/usr/bin/env python3
"""winnow trouble: what went wrong, when, and why (spec section 4, Failures).

A view over the folded graph, read through the basis view (basis.py):

    failures   claims whose payload is (fails THING KIND), oldest first,
               each with three facets labeled holds / pending / undermined:
                 diagnosis  claims (causes CAUSE F): why it happened
                 repair     (answers FIX F), or THING's own replacement
                 guard      (motivates F GUARD) or (motivates DIAGNOSIS GUARD)
    symptoms   what any log already holds that often marks a failure:
               corrected or retracted claims, abandoned decisions, blocked
               or dropped actions, live disputes, honest misses, merge
               conflicts, failure-like relations not in (fails THING KIND)

Nothing here is logged. The normalizer (winnow.py, R13) imports the
failure vocabulary from this module.

Usage:
    python3 trouble.py LOG.wno [--upto N] [--unrepaired] [--kind KIND]
"""
import re
import sys

import basis
from fold import load, flag_value, sx
from sexpr import Lit

FAILS = "fails"        # (fails THING KIND), spec section 4
# Seeded failure kinds: id -> (gloss, registry aliases). Declared into a
# log on first use (winnow.py R13), like any term.
FAILURE_KINDS = {
    "false-belief": (
        "acting or advising on something believed true that was not",
        ("wrong assumption", "false assumption", "mistaken belief")),
    "miscommunication": (
        "the same words meant different things to speaker and listener, "
        "or a message did not carry what was meant",
        ("misunderstanding", "crossed wires")),
    "instruction-violation": (
        "an instruction, rule or constraint in force was not followed",
        ("ignored instruction", "rule violation")),
    "tool-failure": (
        "a program, service or tool errored, crashed, hung or returned "
        "wrong output",
        ("tool error", "program crash", "api error")),
    "regression": (
        "something that worked stopped working after a change",
        ("broke after a change",)),
    "omission": (
        "something required or already known was left out: a step "
        "skipped, a fact dropped, a case missed",
        ("left out", "missed step")),
    "outdated-state": (
        "acting on information that had since changed: an old file, a "
        "finished task, a replaced decision",
        ("stale state", "out of date")),
}
SPEAKERS = {"user", "assistant", "orchestrator", "merge-tool"}
# Surface heads the normalizer rewrites to `fails` when the second
# argument is a failure kind; the trouble view lists them as symptoms
# in logs written before R13.
FAILURE_LIKE = {"failed", "fail", "failure", "went-wrong",
                "goes-wrong", "broke", "breaks"}


def _kebab(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


# Kind-slot aliases (normalizer only; applied to the KIND of a fails
# payload and nowhere else): every registry alias, plus bare words too
# common to put in a registry.
KIND_ALIASES = {k: k for k in FAILURE_KINDS}
for _k, (_gloss, _aka) in FAILURE_KINDS.items():
    KIND_ALIASES.update({_kebab(a): _k for a in _aka})
KIND_ALIASES.update({"bug": "tool-failure", "crash": "tool-failure"})


def kind_id(sym):
    """The seeded kind a surface symbol names, or the symbol unchanged."""
    if isinstance(sym, Lit) or not isinstance(sym, str):
        return sym
    return KIND_ALIASES.get(_kebab(sym), sym)


# ---------------------------------------------------------- normalizer side

def is_failure_payload(p):
    return isinstance(p, list) and len(p) == 3 and p[0] == FAILS


def speakers(g, forms=()):
    """Every name that can sit in :by: the fixed ones, every :by in the
    graph, and every :by in the incoming forms."""
    out = set(SPEAKERS)
    out |= {str(n["by"]) for n in g.nodes.values() if "by" in n}

    def walk(v):
        if isinstance(v, list):
            for i, x in enumerate(v):
                if x == ":by" and i + 1 < len(v) and isinstance(v[i + 1], str):
                    out.add(str(v[i + 1]))
                walk(x)
    walk(list(forms))
    return out


def canonical_failure(payload, who, is_fail):
    """R13 on one claim payload -> (payload, reject reason or None).
    `who` is the speaker set; is_fail(id) says whether id is a failure."""
    if not isinstance(payload, list) or not payload:
        return payload, None
    head = payload[0]
    if head in FAILURE_LIKE and len(payload) == 3 \
            and kind_id(payload[2]) in FAILURE_KINDS:
        head, payload = FAILS, [FAILS] + payload[1:]
    if head == FAILS:
        if len(payload) != 3:
            return payload, (f"fails takes exactly THING and KIND: "
                             f"{sx(payload)}"[:120])
        _, thing, kind = payload
        if str(thing) in who:
            return payload, (f"fails names what went wrong, not who: "
                             f"{thing} (:by already says who spotted it)")
        return [FAILS, thing, kind_id(kind)], None
    if head == "causes" and len(payload) == 3 and is_fail(payload[2]) \
            and str(payload[1]) in who:
        return payload, (f"a diagnosis names the action, node or term that "
                         f"caused {payload[2]}, not a speaker: {payload[1]}")
    return payload, None


def seeded_kind(payload):
    """The seeded kind a canonical failure payload uses, else None."""
    if is_failure_payload(payload) and payload[2] in FAILURE_KINDS:
        return payload[2]
    return None


def kind_term(kind):
    gloss, aka = FAILURE_KINDS[kind]
    return ["term", kind, ":gloss", Lit(gloss), ":aka", [Lit(a) for a in aka]]


def diagnosis_grounds(payload, payload_of, known):
    """Nodes a diagnosis (causes CAUSE F) rests on: F, and CAUSE when it
    is a node. Empty unless F is a failure."""
    if not (isinstance(payload, list) and len(payload) == 3
            and payload[0] == "causes"):
        return []
    _, cause, effect = payload
    if not (known(effect) and is_failure_payload(payload_of(effect))):
        return []
    return [effect] + ([cause] if isinstance(cause, str) and known(cause)
                       and cause != effect else [])


# ---------------------------------------------------------------- the view

def is_failure(g, nid):
    n = g.nodes.get(nid)
    return bool(n and n["frame"] == "claim"
                and is_failure_payload(n["payload"]))


def failure_ids(g):
    return [nid for nid in g.nodes if is_failure(g, nid)]


def diagnoses(g, fid):
    """Claims (causes CAUSE fid)."""
    return [nid for nid, n in g.nodes.items()
            if n["frame"] == "claim" and isinstance(n["payload"], list)
            and len(n["payload"]) == 3 and n["payload"][0] == "causes"
            and n["payload"][2] == fid]


def repairs(g, fid):
    """(answers FIX fid), plus whatever replaced THING when THING is a node
    that no longer stands."""
    out = [a for t, a, b in g.edges if t == "answers" and b == fid
           and a in g.nodes]
    thing = g.nodes[fid]["payload"][1]
    if thing in g.nodes and g.nodes[thing]["status"] in basis.REJECTED:
        out += [a for t, a, b in g.edges
                if t in ("supersedes", "contradicts") and b == thing
                and a in g.nodes]
    return list(dict.fromkeys(out))


def guards(g, fid):
    """What the failure, or one of its diagnoses, motivates. A question
    motivated by it is a follow-up, not a guard."""
    src = {fid} | set(diagnoses(g, fid))
    return list(dict.fromkeys(
        b for t, a, b in g.edges
        if t == "motivates" and a in src and b in g.nodes
        and g.nodes[b]["frame"] != "question"))


def first_turn(src):
    vals = src if isinstance(src, list) else [src]
    nums = [int(str(v)[1:]) for v in vals
            if re.fullmatch(r"t\d+", str(v))]
    return min(nums) if nums else 0


def _best(ids, labels):
    return min((labels[i].label for i in ids), key=basis.RANK.__getitem__,
               default="none")


def facets(g, fid, labels):
    """facet -> (best label among its nodes or 'none', node ids)."""
    out = {}
    for name, ids in (("diagnosis", diagnoses(g, fid)),
                      ("repair", repairs(g, fid)),
                      ("guard", guards(g, fid))):
        out[name] = (_best(ids, labels), ids)
    return out


def unrepaired(g, fid, labels):
    """A standing report with no repair that holds."""
    return (g.nodes[fid]["status"] not in basis.REJECTED
            and facets(g, fid, labels)["repair"][0] != "holds")


def symptoms(g):
    """(turn, nid, text) for each symptom, oldest first."""
    recorded = {}
    for fid in failure_ids(g):
        recorded.setdefault(g.nodes[fid]["payload"][1], []).append(fid)
    out = []

    def add(nid, what):
        n = g.nodes[nid]
        t = g.touched_at_turn(nid)
        line = f"{g._payload_line(nid)} {what}"
        if t is not None:
            line += f" (last changed t{t})"
        if nid in recorded:
            line += f"; recorded as failure {', '.join(recorded[nid])}"
        out.append((first_turn(n.get("src")), nid, line))

    for nid, n in g.nodes.items():
        f, st, p = n["frame"], n["status"], n["payload"]
        head = p[0] if isinstance(p, list) and p else None
        if f == "claim" and is_failure_payload(p):
            continue                       # listed under failures
        if f == "claim" and st in ("corrected", "retracted"):
            by = [a for t, a, b in g.edges
                  if t in ("contradicts", "supersedes") and b == nid]
            add(nid, st + (f", challenged by {', '.join(by)}" if by else ""))
        elif f == "decision" and st == "abandoned":
            add(nid, "abandoned")
        elif f == "action" and st in ("blocked", "dropped"):
            add(nid, st)
        elif f == "question" and head == "locate" \
                and n.get("by") == "orchestrator":
            add(nid, f"honest miss, {st}")
        elif f == "question" and head == "reconcile-status":
            add(nid, f"merge conflict, {st}")
        elif f == "claim" and head in FAILURE_LIKE | {FAILS}:
            add(nid, "failure-like relation, not (fails THING KIND)")
    for t, a, b in g.edges:
        if t == "contradicts" and a in g.nodes and b in g.nodes \
                and g.nodes[a]["status"] not in basis.REJECTED \
                and g.nodes[b]["status"] not in basis.REJECTED:
            add(b, f"disputed by {a}")
    return sorted(out, key=lambda x: (x[0], g._node_key(x[1])))


def render(g, only_unrepaired=False, kind=None):
    labels = basis.analyze(g)
    fids = sorted(failure_ids(g), key=lambda f: (
        first_turn(g.nodes[f].get("src")), g._node_key(f)))
    if kind:
        fids = [f for f in fids if g.nodes[f]["payload"][2] == kind]
    if only_unrepaired:
        fids = [f for f in fids if unrepaired(g, f, labels)]
    syms = symptoms(g)
    lines = [f"; trouble @ turn {g.turn} -- derived, never logged; "
             f"{len(fids)} failures, {len(syms)} symptoms",
             "; --- failures ---"]
    if not fids:
        lines.append("; none recorded")
    for fid in fids:
        n = g.nodes[fid]
        _, thing, k = n["payload"]
        state = (n["status"] if n["status"] in basis.REJECTED
                 else labels[fid].label)
        lines.append(f"{g._payload_line(fid)}  {state}")
        when = f"  ; reported {n.get('src')} by {n.get('by')}"
        if thing in g.nodes:
            when += (f"; {thing} from {g.nodes[thing].get('src')} "
                     f"by {g.nodes[thing].get('by')}")
        lines.append(when)
        if k not in FAILURE_KINDS:
            lines.append(f"  ; kind {k} is not seeded (spec 4): review")
        for name, (lab, ids) in facets(g, fid, labels).items():
            lines.append(f"  ; {name}: {lab}"
                         + (f" ({', '.join(ids)})" if ids else ""))
    lines.append("; --- symptoms ---")
    lines += [text for _, _, text in syms] or ["; none"]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        sys.exit(1)
    upto = flag_value(argv, "--upto")
    g = load(argv[0], int(upto) if upto is not None else None)
    print(render(g, "--unrepaired" in argv, flag_value(argv, "--kind")))


if __name__ == "__main__":
    main()
