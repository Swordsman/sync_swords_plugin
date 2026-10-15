#!/usr/bin/env python3
"""winnow digest: the tiered window a model sees (spec section 10).

A view of the graph fold.py builds, graded by how accessible each node
needs to be right now:

    fire   what the last delta touched, plus `:fire-hops` of projection,
           plus reach promotions still live      -> rendered in full
    hot    the frontier (frontier.py) plus the recent tail: the last
           `:tail` live claims/defs              -> payload lines
    warm   dormant nodes held by an edge to fire/hot -> stubs
    cold   everything else                       -> a count

Tier state is a pure function of (log, profile) plus transient P3
promotions; it is never logged. winnow.py hands this rendering to the
extractor.

Usage:
    python3 digest.py LOG.wno [--upto N]
"""
import sys

import frontier
from fold import ETYPES, load, flag_value


def tail_ids(g):
    """The recent tail: the last `:tail` live claims and defs."""
    claims = [nid for nid, n in g.nodes.items()
              if n["frame"] in ("claim", "def") and n["status"] == "live"]
    return claims[-int(g.profile["tail"]):]


def promote(g, nid):
    """P3: a reach query resolved to nid -> fire until `:promotion-ttl`
    more deltas land (spec 10.3). Called by the orchestrator."""
    if nid in g.nodes:
        g.promotions = {k: until for k, until in g.promotions.items()
                        if until > g.deltas}
        g.promotions[nid] = g.deltas + int(g.profile["promotion-ttl"])


def promoted(g):
    return {nid for nid, until in g.promotions.items()
            if until > g.deltas and nid in g.nodes}


def tiers(g):
    """(fire, hot, warm, cold) per spec section 10."""
    protect = g.profile["protect"]
    adj = {}
    for t, a, b in g.edges:
        if t in protect:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    fire = {i for i in g.touched | promoted(g) if i in g.nodes}
    for _ in range(int(g.profile["fire-hops"])):
        fire |= {nb for i in fire for nb in adj.get(i, ())
                 if nb in g.nodes}
    hot = [i for i in dict.fromkeys(frontier.frontier_ids(g) + tail_ids(g))
           if i not in fire]
    resident = fire | set(hot)
    warm = [nid for nid in g.nodes if nid not in resident
            and any(nb in resident for nb in adj.get(nid, ()))]
    cold = [nid for nid in g.nodes
            if nid not in resident and nid not in warm]
    return fire, hot, warm, cold


def _holding_edge(g, nid, resident):
    for t, a, b in g.edges:
        if a == nid and b in resident or b == nid and a in resident:
            return t, a, b
    return None


def render(g):
    """The push side of the window: side-effect state, fire in full, hot
    as payloads, warm as stubs, cold as a count. Pull results belong to
    the orchestrator."""
    fire, hot, warm, cold = tiers(g)
    p = g.profile
    prot = ("all" if p["protect"] == ETYPES
            else ",".join(sorted(p["protect"])))
    lines = [
        f"; digest @ turn {g.turn} -- derived, ephemeral, never logged",
        f"; profile: tail={p['tail']} fire-hops={p['fire-hops']} "
        f"promotion-ttl={p['promotion-ttl']} "
        f"widening-base={p['widening-base']} protect={prot}",
        f"; side-effect state: {len(g.terms)} terms (registry travels "
        f"with log); live hard constraints render hot",
        "; --- fire: last exchange + projection ---",
    ]
    lines += [g._full_line(i) for i in sorted(fire, key=g._node_key)]
    lines.append("; --- hot: frontier + recent tail ---")
    lines += [g._payload_line(i) for i in sorted(hot, key=g._node_key)]
    lines.append("; --- warm: dormant, edge-held by residents ---")
    resident = fire | set(hot)
    for nid in sorted(warm, key=g._node_key):
        n = g.nodes[nid]
        held = _holding_edge(g, nid, resident)
        via = f" held-by ({held[0]} {held[1]} {held[2]})" if held else ""
        lines.append(f"; {g._payload_line(nid)} "
                     f":status {n['status']}{via}")
    lines.append(f"; --- cold: {len(cold)} nodes, log-resident; "
                 f"(reach QUERY) to promote ---")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        sys.exit(1)
    upto = flag_value(argv, "--upto")
    print(render(load(argv[0], int(upto) if upto is not None else None)))


if __name__ == "__main__":
    main()
