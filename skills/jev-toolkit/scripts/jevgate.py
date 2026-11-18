"""Gate Choices and probe doubt with Jev."""
from __future__ import annotations

import hashlib
import json
import random

import jevbatch

GATE = {
    "listed": "one of the listed options is a good answer",
    "unlisted": "a good answer exists but is not listed",
    "unknown": "not enough information to know",
    "irrelevant": "the question does not apply",
}
ROUTES = {
    "listed": "read the choice",
    "unlisted": "grow the answer set",
    "unknown": "fetch context",
    "irrelevant": "drop the question",
}

SCALE = ("yes", "probably", "maybe", "probably not", "no")
SCALE_VALUES = {
    "yes": 1.0,
    "probably": 0.75,
    "maybe": 0.5,
    "probably not": 0.25,
    "no": 0.0,
}
SCALE_MEANINGS = {
    "yes": "clearly true",
    "probably": "likely true",
    "maybe": "not sure",
    "probably not": "likely false",
    "no": "clearly false",
}


def _seed(*parts):
    try:
        payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=repr)
    except TypeError:
        payload = repr(parts)
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _option_keys(options):
    keys = []
    used = set()
    for index, option in enumerate(options):
        key = option if isinstance(option, str) else str(option)
        if key in used:
            key = f"{key} [{index}]"
            while key in used:
                key = key + " "
        used.add(key)
        keys.append(key)
    return keys


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _reorder_probs(answer, keys, targets):
    raw = answer.get("probabilities") if isinstance(answer, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    result = {}
    for target, key in zip(targets, keys):
        result[target] = _number(raw.get(key, 0.0))
    if not any(result.values()):
        chosen = answer.get("choice") if isinstance(answer, dict) else None
        for target, key in zip(targets, keys):
            if chosen == key or chosen == target:
                result[target] = 1.0
                break
    return result


def _argmax(mapping):
    if not mapping:
        return None
    return max(mapping, key=lambda key: mapping[key])


def _selected(answer, allowed):
    chosen = answer.get("choice") if isinstance(answer, dict) else None
    return chosen if chosen in allowed else None


def _selected_scale(answer):
    chosen = answer.get("choice") if isinstance(answer, dict) else None
    if chosen in ("probably_not", "probably-not"):
        chosen = "probably not"
    return chosen if chosen in SCALE else None


def _scale_probs(answer):
    raw = answer.get("probabilities") if isinstance(answer, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    result = {}
    for label in SCALE:
        value = 0.0
        for key in (label, label.replace(" ", "_")):
            if key in raw:
                value = _number(raw[key])
                break
        result[label] = value
    if not any(result.values()):
        chosen = _selected_scale(answer)
        if chosen is not None:
            result[chosen] = 1.0
    return result


def _side(value):
    if value > 0.5:
        return 1
    if value < 0.5:
        return -1
    return 0


def _doubt_flag(noul, scale, scale_value):
    scale_side = _side(scale_value)
    if scale != "maybe" and scale_side and 0.4 <= noul <= 0.6:
        return "reword"
    if scale == "maybe":
        return "uncertain"
    noul_side = _side(noul)
    if noul_side and scale_side and noul_side != scale_side:
        return "conflict"
    return "ok"


def gated_choices(calls, ask=None):
    """Ask a four-way gate and a shuffled pick for every (state, question, options) call."""
    calls = list(calls)
    if not calls:
        return []
    batch = []
    plans = []
    for state, question, options in calls:
        options = list(options)
        option_keys = _option_keys(options)
        rng = random.Random(_seed("gated_choices", state, question, options))
        labels = list(GATE)
        rng.shuffle(labels)
        shuffled_keys = option_keys[:]
        rng.shuffle(shuffled_keys)
        gate_question = {
            "type": "choice",
            "instructions": "Classify the answer to this question: " + str(question),
            "criteria": {label: GATE[label] for label in labels},
        }
        pick_question = {
            "type": "choice",
            "instructions": "Which listed option is a good answer to this question: " + str(question),
            "criteria": {key: "a listed option" for key in shuffled_keys},
        }
        batch.append((state, {"gate": gate_question, "pick": pick_question}))
        plans.append((options, option_keys))
    answers = jevbatch.batch_ask(batch, ask=ask)
    results = []
    for answer, (options, option_keys) in zip(answers, plans):
        gate_answer = answer.get("gate", {})
        gate_probs = _reorder_probs(gate_answer, list(GATE), list(GATE))
        kind = _selected(gate_answer, GATE)
        if kind is None:
            kind = _argmax(gate_probs)
        pick_answer = answer.get("pick", {})
        choice_probs = _reorder_probs(pick_answer, option_keys, options)
        choice = None
        index = None
        if kind == "listed" and options:
            picked_key = _selected(pick_answer, option_keys)
            if picked_key is not None:
                index = option_keys.index(picked_key)
            else:
                picked_option = _argmax(choice_probs)
                if picked_option in options:
                    index = options.index(picked_option)
            if index is not None:
                choice = options[index]
        results.append({
            "kind": kind,
            "gate_probs": gate_probs,
            "choice": choice,
            "index": index,
            "choice_probs": choice_probs,
        })
    return results


def gated_choice(state, question, options, ask=None):
    """Single-call form of gated_choices."""
    return gated_choices([(state, question, options)], ask=ask)[0]


def doubt_probes(calls, ask=None):
    """Ask a Noul and a shuffled five-way scale for every (state, question) call."""
    calls = list(calls)
    if not calls:
        return []
    batch = []
    for state, question in calls:
        rng = random.Random(_seed("doubt_probes", state, question))
        labels = list(SCALE)
        rng.shuffle(labels)
        noul_question = {"type": "noul", "instructions": str(question), "criteria": {"true": "Yes.", "false": "No."}}
        scale_question = {
            "type": "choice",
            "instructions": str(question) + " Choose the most appropriate answer. Choose exactly one label.",
            "criteria": {label: SCALE_MEANINGS[label] for label in labels},
        }
        batch.append((state, {"noul": noul_question, "scale": scale_question}))
    answers = jevbatch.batch_ask(batch, ask=ask)
    results = []
    for answer in answers:
        noul_answer = answer.get("noul", {})
        noul = _number(noul_answer.get("noul", noul_answer.get("probability", 0.0))) if isinstance(noul_answer, dict) else 0.0
        scale_answer = answer.get("scale", {})
        scale_probs = _scale_probs(scale_answer)
        scale = _selected_scale(scale_answer)
        if scale is None:
            scale = _argmax(scale_probs)
        scale_value = SCALE_VALUES.get(scale, 0.5)
        results.append({
            "noul": noul,
            "scale": scale,
            "scale_probs": scale_probs,
            "scale_value": scale_value,
            "flag": _doubt_flag(noul, scale, scale_value),
        })
    return results


def doubt_probe(state, question, ask=None):
    """Single-call form of doubt_probes."""
    return doubt_probes([(state, question)], ask=ask)[0]