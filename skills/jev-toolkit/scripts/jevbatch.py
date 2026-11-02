"""Batch Jev calls. Callers write one (state, questions) pair per item, the obvious loop; batch_ask sends each shared
state once. State keys identical across all calls are sent once; keys that differ are keyed by item, and every
backticked path in the questions is rewritten to point at its item. Requests split only at the context limit."""
from __future__ import annotations

import json
import re

import scout

REQUEST_TOKENS = 56_000  # margin under Jev's 64k per-request limit
CHARS_PER_TOKEN = 3.5  # conservative estimate for English JSON


def estimate_tokens(value) -> float:
    return len(json.dumps(value, ensure_ascii=False)) / CHARS_PER_TOKEN


def rewrite_paths(value, key: str, item: str):
    """`key`, `key.x`, `key[0]` -> `key.item`, `key.item.x`, `key.item[0]` in every string inside value."""
    if isinstance(value, str):
        return re.sub(rf"`{re.escape(key)}(?=[.`\[])", f"`{key}.{item}", value)
    if isinstance(value, list):
        return [rewrite_paths(element, key, item) for element in value]
    if isinstance(value, dict):
        return {name: rewrite_paths(element, key, item) for name, element in value.items()}
    return value


def batch_ask(calls: list[tuple[dict, dict]], ask=None, budget: float = REQUEST_TOKENS) -> list[dict]:
    """Answer every (state, questions) call; returns one answers dict per call, in order, keyed by the caller's names."""
    ask = ask or scout.ask_jev
    if not calls:
        return []
    states = [state for state, _ in calls]
    if not all(isinstance(state, dict) for state in states):
        raise TypeError("batch_ask needs object states so shared and per-item parts can be separated")
    keys = sorted(set().union(*states))
    shared = {key: states[0][key] for key in keys if all(key in state and state[key] == states[0][key] for state in states)}
    varying = [key for key in keys if key not in shared]
    items = []
    for index, (state, questions) in enumerate(calls):
        item = f"i{index:04d}"
        rewritten = {}
        for name, question in questions.items():
            for key in varying:
                question = rewrite_paths(question, key, item)
            rewritten[f"{item}__{name}"] = question
        items.append((item, {key: state[key] for key in varying if key in state}, rewritten))

    results: dict[str, dict] = {}
    base = estimate_tokens(shared)
    batch, size = [], base
    sent: set[str] = set()

    def send(group: list) -> None:
        state = dict(shared)
        for key in varying:
            values = {item: part[key] for item, part, _ in group if key in part}
            if values:
                state[key] = values
        fingerprint = json.dumps(state, sort_keys=True, ensure_ascii=False)
        repeat = fingerprint in sent  # same state again only because its questions exceed one request
        sent.add(fingerprint)
        questions = {name: question for _, _, item_questions in group for name, question in item_questions.items()}
        try:
            answers = (ask(state, questions, followup=True) if repeat else ask(state, questions))["answers"]
        except scout.ContextOverflow:  # the size estimate was low: halve and retry rather than trust a guess
            if len(group) == 1:
                raise
            send(group[:len(group) // 2])
            send(group[len(group) // 2:])
            return
        for item, _, item_questions in group:
            results[item] = {name.split("__", 1)[1]: answers[name] for name in item_questions}

    for entry in items:
        cost = estimate_tokens(entry[1]) + estimate_tokens(entry[2])
        if batch and size + cost > budget:
            send(batch)
            batch, size = [], base
        batch.append(entry)
        size += cost
    if batch:
        send(batch)
    return [results[item] for item, _, _ in items]
