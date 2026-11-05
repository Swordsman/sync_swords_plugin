"""Rulesets for a dsx graph, as data the viewer hands to the engine (see skills/intent-map/engine). Cards read left to right
by depth, so a fork is a column that splits; nodes is a force layout where a call's request and response sit close, forks
are emphasised and only forks and folded branches get a label."""
from __future__ import annotations

CARD = {
    "head": [["icon", "{icon}"], ["id", "{kind}"]], "chip": "{style}", "body": "{text}",
    "meta": ["{tokens|k} tokens · {cost|usd}", "{hitrate|pct} cached · {model}", "{think|k} thinking tokens", "{spent|usd} in this branch · {calls} calls"],
    "tip": "{kind} {style}: {text}"}
LABEL = [["", "{text}"]]


def presets(depths: int) -> dict:
    order = list(range(depths))
    return {
        "cards": {"live": False, "settle": 40, "top": 28, "fit": "width", "sweep": {"key": "depth", "order": order}, "rules": [
            {"id": "look", "on": {}, "do": [["shape", {"as": "card"}], ["template", CARD]]},
            {"id": "forks", "on": {"fork": True}, "do": [["style", {"class": "emph"}],
                                                          ["template", {"meta": CARD["meta"][:-1] + ["forks into {branches} · {spent|usd} below · {calls} calls"]}]]},
            {"id": "columns", "on": {}, "do": [["column", {"key": "depth", "order": order, "heads": False}],
                                               ["stack", {"axis": "y", "gap": 12, "per": "depth", "start": 28}]]},
        ]},
        "nodes": {"live": True, "fit": "all", "seed": True, "settle": 120, "rules": [
            {"id": "look", "on": {}, "do": [["shape", {"as": "dot"}], ["template", {"label": LABEL, "max": 28, "tip": CARD["tip"]}]]},
            {"id": "weight", "on": {}, "do": [["size", {"r": {"scale": "priority", "from": [0, 5], "to": [4, 12]}}]]},
            {"id": "quiet", "on": {}, "do": [["template", {"label": []}]]},
            {"id": "forks", "on": {"fork": True}, "do": [["style", {"class": "emph"}], ["template", {"label": LABEL}]]},
            {"id": "folds", "on": {"kind": "rollup"}, "do": [["template", {"label": LABEL}]]},
            {"id": "physics", "on": {}, "do": [["repel", {"strength": 500}], ["gravity", {"k": 0.008}]]},
            {"id": "extends", "on": {}, "edges": {"kind": ["extends", "rollup"]}, "do": [["spring", {"length": 46, "k": 0.3, "share": True}]]},
            {"id": "calls", "on": {}, "edges": {"kind": "call"}, "do": [["spring", {"length": 26, "k": 0.6, "share": True}]]},
        ]},
    }
