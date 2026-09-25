"""Process identity beyond the PID — detects PID reuse.

A PID alone is not a stable identity: after a process dies the kernel
will eventually hand its PID to an unrelated process. The pair
(pid, starttime-in-jiffies from /proc/<pid>/stat) is unique for the
lifetime of a boot, so recording it at spawn time and re-checking it
before trusting a stored PID detects reuse.
"""

from __future__ import annotations


def proc_start_jiffies(pid: int) -> int | None:
    """The process's start time (jiffies since boot), or None if gone.

    Field 22 of /proc/<pid>/stat. The comm field (2) may contain spaces
    and parentheses, so parse from the last ')'.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read().decode("ascii", "replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    try:
        rest = data.rsplit(")", 1)[1].split()
        # rest[0] is field 3 (state); starttime is field 22 → rest[19].
        # A zombie has exited — it is not a live process, only an unreaped
        # exit record — so callers must not treat it as running.
        if rest[0] == "Z":
            return None
        return int(rest[19])
    except (IndexError, ValueError):
        return None


def same_process(pid: int, recorded_start: int | None) -> bool:
    """True iff *pid* is alive and is the same process that was recorded.

    A None *recorded_start* degrades to a plain liveness check (identity
    unknown — the caller recorded no start time).
    """
    current = proc_start_jiffies(pid)
    if current is None:
        return False
    if recorded_start is None:
        return True
    return current == recorded_start
