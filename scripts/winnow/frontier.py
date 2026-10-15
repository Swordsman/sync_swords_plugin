#!/usr/bin/env python3
"""winnow frontier: what's still open in a folded graph (spec section 9).

A view of the graph fold.py builds. It lists every node that is
unsettled or still in force, and nothing else:

    constraint  live                 still binding
    decision    proposed             not yet made
    question    open                 not yet answered
    action      todo, doing, blocked not yet done

Claims, defs and artifacts are statements, not open items, so they never
appear here, however recent; the digest (digest.py) is where recency
lives. One count line closes the view.

Usage:
    python3 frontier.py LOG.wno [--upto N]
"""
import sys

from fold import load, flag_value

OPEN = {
    "constraint": {"live"},
    "decision": {"proposed"},
    "question": {"open"},
    "action": {"todo", "doing", "blocked"},
}


def frontier_ids(g):
    """Ids of the open nodes, in the order they entered the graph."""
    return [nid for nid, n in g.nodes.items()
            if n["status"] in OPEN.get(n["frame"], ())]


def render(g):
    ids = frontier_ids(g)
    lines = [g._payload_line(i) for i in ids]
    lines.append(f"; +{len(g.nodes) - len(ids)} nodes not open (claims, defs, "
                 f"artifacts, settled items); digest.py or fold.py --snapshot "
                 f"for those")
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
