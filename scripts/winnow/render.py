#!/usr/bin/env python3
"""winnow render: deterministic plain-English sentences for a log or frontier.

The counterpart of winnow.py extraction: English -> winnow is the
extractor's job; winnow -> English lives here.  It costs no model call.

Usage:
    python3 render.py LOG.wno [--upto N] [--last K]
                              [--view deltas|frontier] [--speak]

--view deltas (the default) prints each selected delta under a `Turn N`
heading, one English sentence per delta op.  --view frontier prints what
frontier.py selects as sentences grouped under four plain headings.

--speak drops node ids, parentheses and brackets, but keeps normal
sentence punctuation: text-meant-for-speech.
"""
import sys

from fold import DEFAULT_STATUS, flag_value, fold
from sexpr import Lit, anns, parse, sx, tokenize

import frontier


FRAME_WORD = {
    "claim": "claim",
    "def": "definition",
    "question": "question",
    "decision": "decision",
    "constraint": "constraint",
    "action": "action",
    "artifact": "artifact",
}

_FRAME_BY_PREFIX = {
    "c": "claim",
    "d": "decision",
    "q": "question",
    "k": "constraint",
    "f": "def",
    "a": "action",
    "r": "artifact",
}

EDGE_PHRASES = {
    "supports": "supports",
    "contradicts": "contradicts",
    "supersedes": "supersedes",
    "refines": "refines",
    "answers": "answers",
    "motivates": "motivates",
    "depends": "depends on",
    "about": "is about",
}


def _end(speak):
    return "."


def _speak_clean(text):
    """Keep words, sentence punctuation, and numeric signs (-, .)
    while removing parentheses and brackets for TTS."""
    text = str(text)
    cleaned = []
    for i, ch in enumerate(text):
        if ch.isalnum() or ch.isspace():
            cleaned.append(ch)
        elif ch in ",.?:":  # sentence punctuation and decimal points
            cleaned.append(ch)
        elif ch == "-" and ((i > 0 and text[i - 1].isdigit()) or
                            (i + 1 < len(text) and text[i + 1].isdigit())):
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


def _txt(value, speak=False):
    text = str(value)
    return _speak_clean(text) if speak else text


def _words(text):
    stripped = str(text).strip()
    return stripped.split() if stripped else []


def _conf_is_low(conf):
    try:
        return float(str(conf)) < 0.6
    except (TypeError, ValueError):
        return False


def _ann_value(value, speak=False):
    if isinstance(value, list):
        return " ".join(_ann_value(v, speak) for v in value)
    return _txt(value, speak)


def _annotation_clause(ann, speak=False, include_by=True):
    """Render :by, :modal, :neg and low :conf into a sentence fragment."""
    parts = []
    if include_by and ann.get("by") is not None:
        parts.append("by " + _ann_value(ann["by"], speak))
    if ann.get("modal") is not None:
        parts.append("modality " + _ann_value(ann["modal"], speak))
    if ann.get("neg") is not None and str(ann["neg"]).lower() in ("true", "1"):
        parts.append("negated")
    if _conf_is_low(ann.get("conf")):
        parts.append("unsure")
    if not parts:
        return ""
    return " " + ", ".join(parts)


def _short_quote(g, nid, speak=False, max_words=8, _stack=None, ghosts=None):
    """First few payload words for nid, resolving inner node ids."""
    stack = _stack or set()
    if nid in stack:
        return "itself"
    node = g.nodes.get(nid)
    if node is None and ghosts is not None:
        node = ghosts.get(nid)
    if node is None:
        return "missing item" if speak else f"missing {_txt(nid, False)}"
    words = _payload_words(g, node, nid, speak, stack | {nid}, ghosts)
    if len(words) > max_words:
        words = words[:max_words]
    text = " ".join(words)
    return _txt(text, speak)


def _payload_words(g, node, current_nid, speak, stack, ghosts):
    pl = node.get("payload")
    if not isinstance(pl, list):
        return _words(str(pl))
    parts = []
    for item in pl:
        if isinstance(item, str) and not isinstance(item, Lit):
            if item == current_nid:
                parts.append("itself")
            elif item in g.nodes or (ghosts is not None and item in ghosts):
                parts.append(_short_quote(g, item, speak, max_words=4,
                                          _stack=stack, ghosts=ghosts))
            else:
                parts.append(item)
        else:
            parts.append(str(item))
    return _words(" ".join(parts))


def _frame_from_id(nid):
    return _FRAME_BY_PREFIX.get(str(nid)[:1], "node")


def _looks_like_node_id(ref):
    s = str(ref)
    return len(s) > 1 and s[0] in _FRAME_BY_PREFIX and s[1:].isdigit()


def _node_phrase(g, ref, speak=False, ghosts=None):
    """A readable stand-in for a node or term reference."""
    node = g.nodes.get(ref)
    if node is None and ghosts is not None:
        node = ghosts.get(ref)

    if node is not None:
        frame = node.get("frame", _frame_from_id(ref))
        fw = FRAME_WORD.get(frame, frame)
        quote = _short_quote(g, ref, speak=speak, max_words=8,
                             ghosts=ghosts).strip()
        text = f"the {fw} {quote}" if quote else f"the {fw}"
        if not speak:
            text += f" [{ref}]"
        return text.strip()

    if ref in g.terms:
        return f"the term {_txt(ref, speak)}"

    if _looks_like_node_id(ref):
        fw = FRAME_WORD.get(_frame_from_id(ref), "item")
        return f"the {fw} item" if speak else f"the {fw} item {ref}"
    return f"the term {_txt(ref, speak)}"


def _full_payload_text(g, node, current_nid, speak, ghosts):
    """Full payload text for the node itself, not quoted/truncated."""
    pl = node.get("payload")
    if pl is None:
        return ""
    if not isinstance(pl, list):
        return _txt(str(pl), speak)
    words = _payload_words(g, node, current_nid, speak, set(), ghosts)
    return _txt(" ".join(words), speak)


def _node_phrase_full(g, ref, speak=False, ghosts=None):
    """A full-payload stand-in for the node itself (update/supersede-new)."""
    node = g.nodes.get(ref)
    if node is None and ghosts is not None:
        node = ghosts.get(ref)

    if node is None:
        return _node_phrase(g, ref, speak, ghosts)

    frame = node.get("frame", _frame_from_id(ref))
    fw = FRAME_WORD.get(frame, frame)
    quote = _full_payload_text(g, node, str(ref), speak=speak,
                               ghosts=ghosts).strip()
    text = f"the {fw} {quote}" if quote else f"the {fw}"
    if not speak:
        text += f" [{ref}]"
    return text.strip()


def _cap(text):
    if not text:
        return text
    return text[0].upper() + text[1:]


def _add_payload_text(g, nid, item, speak, ghosts):
    nid_s = str(nid)
    node = g.nodes.get(nid_s)
    if node is None and ghosts is not None:
        node = ghosts.get(nid_s)
    if node is None:
        frame = item[0]
        if frame == "def":
            payload = [item[2], item[3]]
        elif len(item) > 2:
            payload = item[2]
        else:
            payload = ""
        node = {"frame": frame, "payload": payload}
    return _full_payload_text(g, node, nid_s, speak, ghosts)


def _add_sentence(frame, status, speaker, payload, nid, speak, ann):
    """Render an add op according to the current plain-English templates."""
    tail = _annotation_clause(ann, speak=speak, include_by=False)
    final = "."
    display_payload = payload
    if frame == "question":
        if payload.rstrip().endswith("?"):
            display_payload = payload.rstrip()[:-1].rstrip()
            final = "?"

    if frame == "claim":
        if status == "live":
            core = f"{speaker} states: {display_payload}"
        else:
            if speak:
                core = f"{speaker}, {status}: {display_payload}"
            else:
                core = f"{speaker} ({status}): {display_payload}"
    elif frame == "def":
        core = f"Definition from {speaker}: {display_payload}"
    elif frame == "question":
        if status == "open":
            core = f"Open question from {speaker}: {display_payload}"
        else:
            if speak:
                core = f"Question from {speaker}, {status}: {display_payload}"
            else:
                core = f"Question from {speaker} ({status}): {display_payload}"
    elif frame == "decision":
        if status == "proposed":
            core = f"{speaker} proposes: {display_payload}"
        elif status == "frozen":
            core = f"Decided by {speaker}: {display_payload}"
        else:
            if speak:
                core = f"Decision by {speaker}, {status}: {display_payload}"
            else:
                core = f"Decision by {speaker} ({status}): {display_payload}"
    elif frame == "constraint":
        if status == "live":
            core = f"Requirement from {speaker}: {display_payload}"
        else:
            if speak:
                core = f"Requirement from {speaker}, {status}: {display_payload}"
            else:
                core = f"Requirement from {speaker} ({status}): {display_payload}"
    elif frame == "action":
        if status == "todo":
            who = f"To do, {speaker}" if speak else f"To do ({speaker})"
        elif status == "doing":
            who = f"In progress, {speaker}" if speak else f"In progress ({speaker})"
        elif status == "done":
            who = f"Done, {speaker}" if speak else f"Done ({speaker})"
        elif status == "blocked":
            who = f"Blocked, {speaker}" if speak else f"Blocked ({speaker})"
        else:
            who = f"Action, {speaker}, {status}" if speak else f"Action ({speaker}, {status})"
        core = f"{who}: {display_payload}"
    elif frame == "artifact":
        core = f"Artifact: {display_payload}"
    else:
        raise ValueError

    core += tail
    if not speak:
        core += f" [{nid}]"
    return core + final


def _add_tail(item):
    if not isinstance(item, list) or len(item) < 2:
        return {}
    if item[0] == "def":
        return anns(item[4:]) if len(item) > 4 else {}
    return anns(item[3:]) if len(item) > 3 else {}


def _ghost_nodes(delta_forms):
    """Payloads for nodes later removed by merge/del, from their add ops."""
    ghosts = {}
    for form in delta_forms:
        if not (isinstance(form, list) and form and form[0] == "delta"):
            continue
        for op in form[1:]:
            if not (isinstance(op, list) and op and op[0] == "add"):
                continue
            if len(op) < 2 or not isinstance(op[1], list):
                continue
            item = op[1]
            if len(item) < 2 or item[0] == "edge":
                continue
            frame, nid = item[0], item[1]
            try:
                if frame == "def":
                    payload = [item[2], item[3]]
                else:
                    payload = item[2]
                ghosts[str(nid)] = {"frame": frame, "payload": payload}
            except Exception:
                continue
    return ghosts


def _render_term(form, g, speak, ghosts):
    if len(form) < 2:
        raise ValueError
    tid = form[1]
    a = anns(form[2:])
    clause = _annotation_clause(a, speak)
    gloss = a.get("gloss")
    if gloss is not None and str(gloss).strip():
        text = " ".join(_words(str(gloss))[:8])
        verb = f"is defined as {_txt(text, speak)}"
    else:
        verb = "is declared"
    return _cap(f"The term {_txt(tid, speak)} {verb}{clause}{_end(speak)}")


def _render_edge(item, g, speak, ghosts):
    if len(item) < 2 or not isinstance(item[1], list) or len(item[1]) != 3:
        raise ValueError
    et, src, dst = item[1]
    if et not in EDGE_PHRASES:
        raise ValueError
    return _cap(f"{_node_phrase(g, src, speak, ghosts)} "
                f"{EDGE_PHRASES[et]} "
                f"{_node_phrase(g, dst, speak, ghosts)}{_end(speak)}")


def _render_add(form, g, speak, ghosts):
    if len(form) < 2 or not isinstance(form[1], list):
        raise ValueError
    item = form[1]
    if len(item) < 2:
        raise ValueError
    if item[0] == "edge":
        return _render_edge(item, g, speak, ghosts)

    frame, nid = item[0], item[1]
    if frame not in FRAME_WORD:
        raise ValueError
    a = _add_tail(item)
    status = _txt(a.get("status") or DEFAULT_STATUS.get(frame, "live"), speak)
    by = _ann_value(a.get("by"), speak) if a.get("by") is not None else "assistant"
    speaker = _cap(by)
    payload = _add_payload_text(g, nid, item, speak, ghosts)
    return _add_sentence(frame, status, speaker, payload, nid, speak, a)


def _render_update(form, g, speak, ghosts):
    if len(form) < 2:
        raise ValueError
    nid = form[1]
    updates = anns(form[2:])
    phrase = _node_phrase_full(g, nid, speak=speak, ghosts=ghosts)
    status = updates.get("status")
    verb = f"is now {_txt(status, speak)}" if status is not None \
        else "is updated"
    clause = _annotation_clause(updates, speak)
    return _cap(f"{phrase} {verb}{clause}{_end(speak)}")


def _render_supersede(form, g, speak, ghosts):
    if len(form) < 3:
        raise ValueError
    new, old = form[1], form[2]
    clause = _annotation_clause(anns(form[3:]), speak)
    return _cap(f"{_node_phrase_full(g, new, speak, ghosts)} supersedes "
                f"{_node_phrase(g, old, speak, ghosts)}"
                f"{clause}{_end(speak)}")


def _render_merge(form, g, speak, ghosts):
    if len(form) < 3:
        raise ValueError
    loser, winner = form[1], form[2]
    return _cap(f"{_node_phrase(g, loser, speak, ghosts)} is merged into "
                f"{_node_phrase(g, winner, speak, ghosts)}{_end(speak)}")


def _render_del(form, g, speak, ghosts):
    if len(form) < 2:
        raise ValueError
    target = form[1]
    if isinstance(target, list):
        if (len(target) < 2 or target[0] != "edge"
                or not isinstance(target[1], list) or len(target[1]) != 3):
            raise ValueError
        et, src, dst = target[1]
        if et not in EDGE_PHRASES:
            raise ValueError
        return _cap(f"The {et} edge from {_node_phrase(g, src, speak, ghosts)} "
                    f"to {_node_phrase(g, dst, speak, ghosts)} "
                    f"is removed{_end(speak)}")
    return _cap(f"{_node_phrase(g, target, speak, ghosts)} "
                f"is deleted{_end(speak)}")


def _render_op(form, g, speak, ghosts):
    if not isinstance(form, list) or not form or not isinstance(form[0], str):
        raise ValueError
    head = form[0]
    if head == "term":
        return _render_term(form, g, speak, ghosts)
    if head == "add":
        return _render_add(form, g, speak, ghosts)
    if head == "update":
        return _render_update(form, g, speak, ghosts)
    if head == "supersede":
        return _render_supersede(form, g, speak, ghosts)
    if head == "merge":
        return _render_merge(form, g, speak, ghosts)
    if head == "del":
        return _render_del(form, g, speak, ghosts)
    raise ValueError


def _unreadable(form, speak):
    text = sx(form)
    if speak:
        text = _speak_clean(text)
    return f"Unreadable op: {text}"


def _render_ops(delta_forms, g, speak, ghosts):
    out = []
    for form in delta_forms:
        if not (isinstance(form, list) and form and form[0] == "delta"):
            out.append(_unreadable(form, speak))
            continue
        for op in form[1:]:
            if not isinstance(op, list):
                continue
            try:
                out.append(_render_op(op, g, speak, ghosts))
            except Exception:
                out.append(_unreadable(op, speak))
    return out


def render_ops(delta_forms, graph, speak=False):
    """One plain-English sentence per op in each supplied delta."""
    ghosts = _ghost_nodes(delta_forms)
    return _render_ops(delta_forms, graph, speak, ghosts)


def render_deltas(delta_forms, graph, last=None, speak=False):
    """Render selected deltas, each headed `Turn N`."""
    ghosts = _ghost_nodes(delta_forms)
    selected = delta_forms
    if last is not None:
        last = int(last) if not isinstance(last, int) else last
        selected = [] if last <= 0 else delta_forms[-last:]
    lines = []
    for form in selected:
        if not (isinstance(form, list) and form and form[0] == "delta"):
            continue
        head_anns = anns(form[1:3]) if len(form) > 1 else {}
        turn = head_anns.get("turn", "?")
        lines.append(f"Turn {_txt(turn, speak)}")
        lines.extend(_render_ops([form], graph, speak, ghosts))
    return "\n".join(lines)


def _frontier_state_sentence(g, nid, speak):
    node = g.nodes[nid]
    frame = node.get("frame")
    status = _txt(node.get("status", ""), speak)
    by = _ann_value(node.get("by"), speak) if node.get("by") is not None else "assistant"
    speaker = _cap(by)
    payload = _full_payload_text(g, node, str(nid), speak, None)
    return _add_sentence(frame, status, speaker, payload, nid, speak, node)


def render_frontier_text(g, speak=False):
    """Frontier view as sentences under plain headings."""
    groups = {
        "Open questions": [],
        "Proposed decisions": [],
        "Live constraints": [],
        "Actions": [],
    }
    assumptions = []

    for nid in frontier.frontier_ids(g):
        n = g.nodes[nid]
        frame = n["frame"]
        if frame == "question":
            groups["Open questions"].append(nid)
        elif frame == "decision":
            groups["Proposed decisions"].append(nid)
        elif frame == "constraint":
            groups["Live constraints"].append(nid)
        elif frame == "action":
            groups["Actions"].append(nid)
        elif frame == "claim":
            assumptions.append(nid)

    lines = []
    for heading, ids in groups.items():
        lines.append(heading)
        if not ids:
            lines.append("None")
            continue
        for nid in ids:
            lines.append(_frontier_state_sentence(g, nid, speak))

    if assumptions:
        lines.append("Assumptions")
        for nid in assumptions:
            lines.append(_frontier_state_sentence(g, nid, speak))
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if argv else 1

    path = argv[0]
    view = flag_value(argv, "--view", "deltas")
    if view not in ("deltas", "frontier"):
        print(f"render.py: unknown --view {view!r}; use deltas or frontier",
              file=sys.stderr)
        return 2

    speak = "--speak" in argv
    upto_s = flag_value(argv, "--upto")
    last_s = flag_value(argv, "--last")
    upto = int(upto_s) if upto_s is not None else None
    last = int(last_s) if last_s is not None else None

    with open(path) as f:
        text = f.read()

    g = fold(text, upto)
    forms = parse(tokenize(text))
    deltas = [f for f in forms if isinstance(f, list) and f and f[0] == "delta"]
    if upto is not None:
        deltas = deltas[:upto]

    if view == "frontier":
        print(render_frontier_text(g, speak=speak))
    else:
        out = render_deltas(deltas, g, last=last, speak=speak)
        if out:
            print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())