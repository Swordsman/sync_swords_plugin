#!/usr/bin/env python3
"""Arcs from the turn maps, then reconcile the merged winnow against what the skills and notes actually say.

usage: stage2.py arcs | reconcile
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import dsx
from pipeline import FOLD, OUT

HOME = pathlib.Path("/home/claude")
DOCS = sorted({*HOME.glob("skills/*/SKILL.md"), *HOME.glob("skills/*/design/*.md"),
               *HOME.glob("skills/*/references/*.md"), HOME / "design/drone-harness.md", HOME / "offload.md"})

ARCS_TASK = ("The three turn lists above cover one long working session, split at two context compactions (segments 1, "
             "2, 3, in order). Group the whole session into arcs: the distinct threads of work or discussion, each with "
             "its segment and turn range (an arc may pause and resume; list every range), a one-line intent, and how it "
             "ended (done, parked, superseded, still open). Then list the dependencies between arcs. Output markdown only.")
RECONCILE_TASK = (
    "Above are: the session's arcs; the canonical snapshot of a winnow graph extracted from the whole session (node ids, "
    "statuses, :src turn references, with segment prefixes s1/s2/s3 where present); and every skill and design document "
    "written during that session. Find every place where the documents fail the session: decisions, constraints, "
    "corrections, ideas, rejected ideas, open questions and todo actions that the documents never recorded, recorded "
    "wrongly, or recorded as settled when they are open (or the reverse). Ignore phatic and trivial items. For each gap "
    "give: the target document path; what is missing or wrong; the evidence (node ids and turns); and the exact text to "
    "add or replace, written in the target document's own style. Group by target document, most important first. "
    "Then list items that belong in no existing document, with a suggested new file. Output markdown only.")


def snapshot(log: pathlib.Path) -> str:
    return subprocess.run([sys.executable, str(FOLD), str(log), "--snapshot"], capture_output=True, text=True).stdout


def arcs() -> None:
    lists = "".join(f"<segment {n}>\n{(OUT / f's{n}.turns.pro.md').read_text()}\n</segment {n}>\n\n" for n in (1, 2, 3))
    dsx.call(lists + ARCS_TASK, OUT / "arcs.md", model="pro", thinking="max",
             accept_miss="turn lists sat mid-prompt in the winnow calls; ~4k tokens uncached (~$0.003) beats prefixing spec+segment")


def reconcile() -> None:
    documents = "".join(f'<document path="{path}">\n{path.read_text()}\n</document>\n\n' for path in DOCS)
    prompt = ("<arcs>\n" + (OUT / "arcs.md").read_text() + "\n</arcs>\n\n<winnow-snapshot>\n"
              + snapshot(OUT / "session.wno") + "\n</winnow-snapshot>\n\n" + documents + RECONCILE_TASK)
    dsx.call(prompt, OUT / "reconcile.md", model="pro", thinking="max")


if __name__ == "__main__":
    {"arcs": arcs, "reconcile": reconcile}[sys.argv[1]]()
