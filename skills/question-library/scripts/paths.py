"""Where this skill's data lives, where runs write output, and how scripts find the jev-toolkit skill."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("QUESTION_LIBRARY_DATA", SKILL_ROOT / "data"))  # installed skills may be read-only: copy data out to edit it
OUT = Path(os.environ.get("QUESTION_LIBRARY_OUT", Path.cwd() / "ql_out"))


def output(name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT / name


def latest(name: str) -> Path:
    """A run's fresh output if there is one, else the shipped copy in data/facets."""
    fresh = OUT / name
    return fresh if fresh.exists() else DATA / "facets" / name


def use_jev() -> None:
    """Put jev-toolkit's scripts on sys.path: JEV_HOME, then a sibling jev-toolkit skill, then ~/jev."""
    candidates = [os.environ.get("JEV_HOME"), SKILL_ROOT.parent / "jev-toolkit" / "scripts", Path.home() / "jev"]
    for candidate in filter(None, candidates):
        if (Path(candidate) / "scout.py").is_file():
            sys.path.insert(0, str(candidate))
            return
    raise SystemExit("This step needs the jev-toolkit skill (install it beside this one, or set JEV_HOME). "
                     "Without Jev, use the no-tool procedures in references/capabilities.md.")
