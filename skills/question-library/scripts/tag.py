"""Place every library entry on the axes: one Choice per axis per entry, all packed by jevbatch (no state sent twice).
Writes tags.json and collisions.json next to this file."""
from __future__ import annotations

import collections
import json
import random

from paths import DATA, output, use_jev  # noqa: E402

use_jev()
import jevbatch  # noqa: E402
import scout  # noqa: E402
from axes import AXES  # noqa: E402

PROMPTS = {
    "target": "What does `entry.question` point the answerer's attention at?",
    "move": "What operation does `entry.question` ask the answerer to perform on what it points at?",
    "stance": "What presumption does `entry.question` make about the answerer's current work?",
    "perspective": "From whose viewpoint does `entry.question` ask the answerer to respond?",
}


def choice(instructions: str, values: dict, seed: str) -> dict:
    order = sorted(values)
    random.Random(seed).shuffle(order)  # Jev leans toward the first option
    return {"type": "choice", "instructions": instructions, "criteria": {value: values[value][0] for value in order}}


def main() -> None:
    entries = json.loads((DATA / "questions.json").read_text())
    entries = entries["entries"] if isinstance(entries, dict) else entries
    calls = [({"entry": {"question": entry["question"], "phrasings": entry["phrasings"]}},
              {axis: choice(PROMPTS[axis], AXES[axis], entry["id"] + axis) for axis in AXES}) for entry in entries]
    answers = jevbatch.batch_ask(calls)
    tags = {}
    for entry, answer in zip(entries, answers):
        tags[entry["id"]] = {"question": entry["question"],
                             **{axis: answer[axis]["choice"] for axis in AXES},
                             "confidence": {axis: answer[axis].get("probabilities", {}).get(answer[axis]["choice"]) for axis in AXES}}
    groups = collections.defaultdict(list)
    for entry_id, tag in tags.items():
        groups[tuple(tag[axis] for axis in AXES)].append(entry_id)
    collisions = [{"coordinates": dict(zip(AXES, key)), "entries": {i: tags[i]["question"] for i in ids}}
                  for key, ids in groups.items() if len(ids) > 1]
    output("tags.json").write_text(json.dumps(tags, indent=1, ensure_ascii=False))
    output("collisions.json").write_text(json.dumps(collisions, indent=1, ensure_ascii=False))
    print(len(tags), "entries,", len(groups), "distinct coordinates,", len(collisions), "collision groups;", scout.meter_summary())
    print(json.dumps(answers[0], ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
