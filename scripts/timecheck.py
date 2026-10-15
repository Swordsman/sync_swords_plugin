#!/usr/bin/env python3
"""timecheck: a PreToolUse hook that stops a tool call writing a "now"
that isn't now.

Agents type the current time from their own sense of how much time has
passed, and it drifts: in one session four stamps were typed 3 to 16
minutes off, three of them ahead of the clock, after a written rule
against it. A time in a tool's input more than a minute ahead of the
clock is almost always that mistake, so this hook blocks the call and
tells the agent the real time. Past times are left alone (they're
usually data read from somewhere), as are tools whose job is a future
time (scheduling). A call that really means a future time passes with
the marker `timecheck:ok` anywhere in its input.

Hook contract: reads the PreToolUse JSON on stdin; exit 0 allows, exit 2
blocks with the message on stderr.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

STAMP = re.compile(r"\b(20\d\d-[01]\d-[0-3]\d)[T ]([0-2]\d:[0-5]\d)(?::([0-5]\d))?(?:\.\d+)?(Z|\+00:00| ?UTC)")
AHEAD_S = 60          # tolerance for clock skew and slow calls
WINDOW_S = 6 * 3600   # only look at times near now: older or much later ones are data
SCHEDULERS = ("send_later", "create_trigger", "update_trigger", "ScheduleWakeup", "CronCreate")


def problems(text: str, now: dt.datetime) -> list[str]:
    found = []
    for m in STAMP.finditer(text):
        day, hm, sec = m.group(1), m.group(2), m.group(3) or "00"
        try:
            t = dt.datetime.fromisoformat(f"{day}T{hm}:{sec}+00:00")
        except ValueError:
            continue
        ahead = (t - now).total_seconds()
        if AHEAD_S < ahead <= WINDOW_S:
            found.append(f"{m.group(0).strip()} is {round(ahead / 60)} min ahead of the clock")
    return found


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool = str(event.get("tool_name", ""))
    if any(s in tool for s in SCHEDULERS):
        return 0
    text = json.dumps(event.get("tool_input", {}), ensure_ascii=False)
    if "timecheck:ok" in text:
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    found = problems(text, now)
    if not found:
        return 0
    print(f"timecheck: blocked {tool}: " + "; ".join(found) +
          f". The clock reads {now.strftime('%Y-%m-%dT%H:%M:%SZ')}. A typed 'now' drifts: take the time "
          "from `date -u` (or the data it came from) and retry. If this future time is intended, add "
          "`timecheck:ok` anywhere in the input.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
