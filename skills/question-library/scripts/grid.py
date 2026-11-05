"""Write axes.html: tab 1 has the six pair tables, colored by Jev's worth score; tab 2 has the full grid, with sortable
columns, colors per axis value, and each combination's weakest pair. Library entries Jev placed are shown in both."""
from __future__ import annotations

import collections
import itertools
import json
import math
import pathlib

from axes import AXES, grid, render

HERE = pathlib.Path(__file__).resolve().parent
from paths import latest, output  # noqa: E402
NAMES = list(AXES)
tags = json.loads(latest("tags.json").read_text())
pairs = json.loads(latest("pairs.json").read_text())

occupants = collections.defaultdict(list)
for entry_id, tag in tags.items():
    occupants[tuple(tag[axis] for axis in NAMES)].append(f"{entry_id}: {tag['question']}")
    for axis_a, axis_b in itertools.combinations(NAMES, 2):
        occupants[(axis_a, axis_b, tag[axis_a], tag[axis_b])].append(entry_id)

for pair, table in pairs.items():
    axis_a, axis_b = pair.split("|")
    for values, cell in table.items():
        cell["entries"] = occupants.get((axis_a, axis_b, *values.split("|")), [])


def weakest_pair(cell: dict) -> float:
    return min(pairs[f"{a}|{b}"][f"{cell[a]}|{cell[b]}"]["worth"] for a, b in itertools.combinations(NAMES, 2))


rows = [[*cell.values(), render(**cell), weakest_pair(cell), occupants.get(tuple(cell.values()), [])] for cell in grid()]
assert len(rows) == math.prod(len(values) for values in AXES.values())
axes = {axis: {value: meaning for value, (meaning, _) in values.items()} for axis, values in AXES.items()}
data = json.dumps({"axes": axes, "pairs": pairs, "rows": rows}, ensure_ascii=False)
output("axes.html").write_text((HERE / "axes_page.html").read_text().replace("__DATA__", data))
print(len(rows), "combinations,", sum(1 for row in rows if row[-1]), "filled")
