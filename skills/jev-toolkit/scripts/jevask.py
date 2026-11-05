"""Hand Jev a state and a list of things you need to know; get answers back.
Jev plans: which question type fits each need, and which needs depend on others' answers. Code builds the calls.
Text handed over is numbered by line; a need can cite lines as [44], and choice-type needs pick a line."""
from __future__ import annotations

import re

import scout

TYPES = {
    "noul": "asks whether something is true, or states something to check",
    "choice": "asks which line of `lines` is the one that fits a description",
    "score": "asks how much, how strongly, or to what degree",
}
SCALE = ["not at all", "slightly", "moderately", "mostly", "completely"]
CHOICE_LIMIT, BLOCK = 255, 10
DOUBT = (0.4, 0.6)
REFERENCE = re.compile(r"\[(\d+)\]")


def number_lines(text: str) -> dict[str, str]:
    return {f"L{number}": line for number, line in enumerate(text.splitlines(), 1) if line.strip()}


def expand(need: str, lines: dict[str, str]) -> str:
    """[44] -> the quoted text of line 44, so Jev never has to look references up."""
    def substitute(match: re.Match) -> str:
        line = lines.get(f"L{match[1]}")
        return match[0] if line is None else f'"{line}" (line {match[1]})'  # unknown references stay as written

    return REFERENCE.sub(substitute, need)


def plan(needs: dict[str, str], has_lines: bool) -> tuple[dict[str, str], dict[str, set[str]]]:
    """One call: a question type per need, and which other needs each one depends on."""
    types = TYPES if has_lines else {name: meaning for name, meaning in TYPES.items() if name != "choice"}
    questions = {f"type_{key}": {"type": "choice", "instructions": f"What kind of question is `needs.{key}`?", "criteria": types}
                 for key in needs}
    questions |= {f"dep_{key}_{other}": scout.noul(f"Does answering `needs.{key}` require first knowing the answer to `needs.{other}`?")
                  for key in needs for other in needs if other != key}
    answers = scout.ask_jev({"needs": needs}, questions)["answers"]
    kinds = {key: answers[f"type_{key}"]["choice"] for key in needs}
    depends = {key: {other for other in needs if other != key and answers[f"dep_{key}_{other}"]["noul"] >= 0.5} for key in needs}
    return kinds, depends


def rounds(depends: dict[str, set[str]]) -> list[list[str]]:
    done: set[str] = set()
    order = []
    while len(done) < len(depends):
        ready = [key for key, needed in depends.items() if key not in done and needed <= done]
        if not ready:  # a cycle: Jev saw mutual dependence; ask the rest together
            ready = [key for key in depends if key not in done]
        order.append(ready)
        done |= set(ready)
    return order


def question_for(kind: str, need: str, options: dict[str, str] | None) -> dict:
    if kind == "noul":
        return scout.noul(f"`need` asks: {need} Is the answer yes, or is the statement true, given `state`?")
    if kind == "score":
        return {"type": "score", "instructions": f"Given `state`: {need}", "criteria": SCALE}
    return {"type": "choice", "instructions": f"Which of these fits best: {need}", "criteria": options}


def blocks(lines: dict[str, str]) -> dict[str, str]:
    keys = list(lines)
    return {f"B{index // BLOCK + 1}": f"lines {keys[index][1:]}-{keys[min(index + BLOCK, len(keys)) - 1][1:]}"
            for index in range(0, len(keys), BLOCK)}


def render(kind: str, answer: dict, lines: dict[str, str]) -> str:
    if kind == "noul":
        return f"{'yes' if answer['noul'] >= 0.5 else 'no'} (p={answer['noul']:.2f})"
    if kind == "score":
        return f"{SCALE[round(answer['score'])]} ({answer['score']:.1f} of {len(SCALE) - 1})"
    return f"line {answer['choice'][1:]}: {lines.get(answer['choice'], answer['choice'])}"


def doubtful(kind: str, answer: dict) -> bool:
    if kind == "noul":
        return DOUBT[0] <= answer["noul"] <= DOUBT[1]
    return answer["confidence"] < 0.5


def ask(needs: list[str], state: dict | None = None, text: str | None = None) -> dict[str, dict]:
    """needs: plain-language questions or statements, in order. Returns {need: {kind, answer, value, doubtful, round}}."""
    state = dict(state or {})
    lines = number_lines(text) if text else {}
    if lines:
        state["lines"] = lines
    named = {f"N{index}": expand(need, lines) for index, need in enumerate(needs, 1)}
    kinds, depends = plan(named, bool(lines))
    results: dict[str, dict] = {}
    pending = rounds(depends)
    round_number = 0
    while pending:
        group = pending.pop(0)
        round_number += 1
        earlier = {named[key]: results[key]["answer"] for key in results}
        round_state = {**state, **({"earlier_answers": earlier} if earlier else {})}
        questions, narrowing = {}, []
        for key in group:
            need = named[key]
            if kinds[key] == "choice" and len(lines) > CHOICE_LIMIT:  # narrow to a block of lines first
                narrowing.append(key)
                questions[key] = {"type": "choice", "instructions": f"Which block of `lines` contains the line that fits: {need}",
                                  "criteria": blocks(lines)}
            else:
                questions[key] = question_for(kinds[key], need, lines)
        for key in group:
            questions[key]["instructions"] = questions[key]["instructions"].replace("`need`", f"`needs.{key}`")
        answers = scout.ask_jev({**round_state, "needs": {key: named[key] for key in group}}, questions)["answers"]
        refine = []
        for key in group:
            if key in narrowing:
                first, last = map(int, blocks(lines)[answers[key]["choice"]].removeprefix("lines ").split("-"))
                refine.append((key, {f"L{n}": lines[f"L{n}"] for n in range(first, last + 1) if f"L{n}" in lines}))
                continue
            results[key] = {"need": needs[int(key[1:]) - 1], "kind": kinds[key], "answer": render(kinds[key], answers[key], lines),
                            "value": answers[key], "doubtful": doubtful(kinds[key], answers[key]), "round": round_number}
        if refine:  # the within-block choice depends on the block answer: one more call, same state, marked as such
            questions = {key: question_for("choice", named[key], options) for key, options in refine}
            answers = scout.ask_jev({**round_state, "needs": {key: named[key] for key, _ in refine}}, questions, followup=True)["answers"]
            for key, _ in refine:
                results[key] = {"need": needs[int(key[1:]) - 1], "kind": "choice", "answer": render("choice", answers[key], lines),
                                "value": answers[key], "doubtful": doubtful("choice", answers[key]), "round": round_number}
    return {results[key]["need"]: results[key] for key in sorted(results, key=lambda key: int(key[1:]))}
