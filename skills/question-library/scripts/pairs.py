"""Score every pair of axis values (Ritchey's cross-consistency step): one Jev pass over all 563 pair cells.
Writes pairs.json: {"axisA|axisB": {"valueA|valueB": {"question", "coherent", "redundant"}}}."""
from __future__ import annotations

import itertools
import json

from paths import output, use_jev  # noqa: E402

use_jev()
import jevbatch  # noqa: E402
import scout  # noqa: E402
from axes import AXES, render  # noqa: E402

COHERENT = scout.noul("Do the parts named in `cell.combines` fit together into one question, `cell.question`, "
                      "that could sensibly be asked and answered about some real task?",
                      "the parts fit together into an answerable question",
                      "the parts conflict or make no sense together")
WORTH = {"type": "score", "instructions": "A diagnostic question built from `cell.combines` would point a model at one thing "
         "and ask it to do one thing, with no hint of the answer. How worthwhile would such a question be?",
         "criteria": ["incoherent: the parts conflict, so no sensible question combines them",
                      "pointless: a question can be formed, but asking it would rarely tell anyone anything",
                      "occasionally useful: it fits a narrow set of situations",
                      "useful: it would often surface something a model missed",
                      "essential: a question any careful thinker asks routinely"]}
REDUNDANT = scout.noul("In `cell.combines`, does one part already imply the other, so that combining them adds nothing?",
                       "one part already implies the other", "each part adds something the other does not")


def pair_cells():
    for axis_a, axis_b in itertools.combinations(AXES, 2):
        for value_a, value_b in itertools.product(AXES[axis_a], AXES[axis_b]):
            combines = f"{axis_a} = {value_a} ({AXES[axis_a][value_a][0]}); {axis_b} = {value_b} ({AXES[axis_b][value_b][0]})"
            yield f"{axis_a}|{axis_b}", f"{value_a}|{value_b}", render(**{axis_a: value_a, axis_b: value_b}), combines


def main() -> None:
    cells = list(pair_cells())
    answers = jevbatch.batch_ask([({"cell": {"question": question, "combines": combines}},
                                   {"coherent": COHERENT, "worth": WORTH, "redundant": REDUNDANT}) for _, _, question, combines in cells])
    pairs: dict[str, dict] = {}
    for (pair, values, question, _), answer in zip(cells, answers):
        pairs.setdefault(pair, {})[values] = {"question": question, "coherent": round(answer["coherent"]["noul"], 2),
                                              "worth": round(answer["worth"]["score"], 2),
                                              "redundant": round(answer["redundant"]["noul"], 2)}
    output("pairs.json").write_text(json.dumps(pairs, indent=1, ensure_ascii=False))
    scores = [cell["worth"] for table in pairs.values() for cell in table.values()]
    print(len(scores), "cells;", sum(score < 1.5 for score in scores), "worth below 1.5 (pointless or incoherent);", scout.meter_summary())


if __name__ == "__main__":
    main()
