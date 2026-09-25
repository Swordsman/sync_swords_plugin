#!/usr/bin/env python3
"""Batch read and batch write across many files, in one call each.

The read emits block-addressed text: every file is cut into fixed-size blocks
carrying an `idx:subidx` label. The write addresses a block and locates its span
by string markers inside it.

Why blocks rather than line numbers or whole-file string matches:

- A string match scoped to one block does not have to be unique in the whole
  file. Quoting a neighbourhood purely to disambiguate is the failure mode of
  every whole-file replace, and the block removes it.
- `idx:subidx` survives intra-batch drift. Insert into block 3 and every line
  number below it moves, but block 7 still holds what block 7 held.
- Marker pairs replace a span without transcribing it. Replacing forty lines
  otherwise means reproducing all forty exactly.

The read side markers sit at column 0, so the sentinel that delimits them only
has to begin no line — it may occur mid-line freely. See
`shortest_absent_line_prefix`; the stricter substring form is
`shortest_absent_token`.

Nothing is written until every edit in the batch has resolved. A batch that
cannot locate one marker writes none of them, so a failure leaves the tree
untouched rather than half-changed.

CLI:

    python3 multiedit.py read  [--granularity N] FILE [FILE...]
    python3 multiedit.py edit  [--granularity N] FILE [FILE...]  < edits.json
    python3 multiedit.py mv    SRC DST
    python3 multiedit.py cp    SRC DST
    python3 multiedit.py rm    PATH [PATH...]
    python3 multiedit.py mkdir [-p] PATH [PATH...]
    python3 multiedit.py grep  PATTERN [PATH...] [-C N]
    python3 multiedit.py hash  PATH [PATH...]
    python3 multiedit.py wc    PATH [PATH...]

Python API:

    from multiedit import MultiEdit
    m = MultiEdit(granularity=10)
    print(m.read("a.md", "b.md"))
    m.edit(0, 3, start="def foo", end="return None", text="...")
    m.apply()
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import string
import sys
import tempfile
from typing import NamedTuple

DEFAULT_GRANULARITY = 10

# Printable ASCII minus whitespace. Whitespace is excluded because a sentinel
# has to survive being read back on a line of its own.
SENTINEL_CHARSET = string.ascii_letters + string.digits + string.punctuation

# Past this length the repeat-sentinel has stopped being cheap and the input is
# either adversarial or pathological; fall back to a random token.
SENTINEL_LENGTH_CEILING = 8


def longest_run(text: str, char: str) -> int:
    """Length of the longest consecutive run of `char` in `text`."""
    best = run = 0
    for c in text:
        if c == char:
            run += 1
            if run > best:
                best = run
        else:
            run = 0
    return best


def shortest_absent_token(text: str, charset: str = SENTINEL_CHARSET) -> str:
    """Shortest string over `charset` that does not occur in `text`.

    Type 0 algorithm, one-pass form. For a character whose longest run in the
    file is `r`, the string `char * (r + 1)` is absent by construction. The
    minimum over all characters is the shortest repeat-token — no search, one
    pass per character.

    An absent single character wins outright when one exists, which is the
    common case for any file not using the whole printable range.
    """
    present = set(text)
    for c in charset:
        if c not in present:
            return c

    best = None
    for c in charset:
        candidate_len = longest_run(text, c) + 1
        if best is None or candidate_len < len(best):
            best = c * candidate_len

    if best is None or len(best) > SENTINEL_LENGTH_CEILING:
        return _random_token(lambda tok: tok not in text, charset)
    return best


def shortest_absent_line_prefix(text: str, charset: str = SENTINEL_CHARSET) -> str:
    """Shortest string over `charset` that begins no line of `text`.

    Type 0 refinement. Every marker sits at column 0 of its own line, so a
    sentinel only has to be unique *as a line prefix* — a `G` in the middle of
    a sentence can never be mistaken for a marker.
    """
    lines = text.split("\n")

    starts = {line[0] for line in lines if line}

    for c in charset:
        if c not in starts:
            return c

    runs: dict[str, int] = {}
    for line in lines:
        if not line:
            continue
        c = line[0]
        n = len(line) - len(line.lstrip(c))
        if n > runs.get(c, 0):
            runs[c] = n

    best = None
    for c in charset:
        candidate_len = runs.get(c, 0) + 1
        if best is None or candidate_len < len(best):
            best = c * candidate_len

    if best is None or len(best) > SENTINEL_LENGTH_CEILING:
        return _random_token(
            lambda tok: begins_no_line(text, tok), charset
        )
    return best


def begins_no_line(text: str, token: str) -> bool:
    """True when no line of `text` starts with `token`."""
    return not any(line.startswith(token) for line in text.split("\n"))


def _random_token(is_acceptable, charset: str) -> str:
    rng = random.SystemRandom()
    while True:
        token = "".join(rng.choice(charset) for _ in range(SENTINEL_LENGTH_CEILING))
        if is_acceptable(token):
            return token


class _Block(NamedTuple):
    idx: int
    subidx: int
    path: str
    start_line: int          # 1-based, inclusive
    end_line: int            # 1-based, inclusive
    char_start: int          # offset into the file text
    char_end: int            # exclusive


class _PendingEdit(NamedTuple):
    path: str
    char_start: int
    char_end: int
    text: str
    label: str               # for error messages


class MultiEditError(Exception):
    pass


class MultiEdit:
    def __init__(self, granularity: int = DEFAULT_GRANULARITY):
        self.granularity = granularity
        self.files: dict[str, str] = {}
        self.order: list[str] = []
        self.blocks: dict[tuple[int, int], _Block] = {}
        self.pending: list[_PendingEdit] = []
        self.sentinel: str = "--"

    # ---------------------------------------------------------------- read

    def read(self, *paths: str) -> str:
        if self.granularity < 1:
            raise MultiEditError("granularity must be >= 1")
        self.files.clear()
        self.order.clear()
        self.blocks.clear()

        for p in paths:
            with open(p, "r", encoding="utf-8") as fh:
                self.files[p] = fh.read()
            self.order.append(p)

        corpus = "\n".join(self.files.values())
        self.sentinel = shortest_absent_line_prefix(corpus)

        s = self.sentinel
        out = [f"{s}|multiread|sentinel-is-the-token-on-this-line|files:{len(paths)}|{s}"]

        for idx, path in enumerate(self.order):
            text = self.files[path]
            lines = text.splitlines(keepends=True)
            directory, filename = os.path.split(path)
            out.append("")
            out.append(
                f"{s}|multiread|idx:{idx} of {len(self.order)}|path:{directory or '.'}"
                f"|file:{filename}|start:1|count:{len(lines)}|end:{len(lines)}|{s}"
            )

            offset = 0
            if not lines:
                self.blocks[(idx, 0)] = _Block(
                    idx=idx, subidx=0, path=path,
                    start_line=1, end_line=0,
                    char_start=0, char_end=0,
                )
                out.append(f"{s}|idx:{idx}|subidx:0|lines:1-->0|{s}")
                out.append("")
            for subidx, first in enumerate(range(0, len(lines), self.granularity)):
                chunk = lines[first:first + self.granularity]
                char_start = offset
                offset += sum(len(l) for l in chunk)
                self.blocks[(idx, subidx)] = _Block(
                    idx=idx, subidx=subidx, path=path,
                    start_line=first + 1, end_line=first + len(chunk),
                    char_start=char_start, char_end=offset,
                )
                out.append(
                    f"{s}|idx:{idx}|subidx:{subidx}"
                    f"|lines:{first + 1}-->{first + len(chunk)}|{s}"
                )
                out.append("".join(chunk).rstrip("\n"))

        out.append("")
        out.append(f"{s}|multiread|done|{s}")
        return "\n".join(out)

    # --------------------------------------------------------------- write

    def edit(self, idx: int, subidx: int, start: str, end: str | None = None,
             text: str = "", mode: str = "consume",
             end_subidx: int | None = None) -> None:
        """Stage one replacement. Nothing touches disk until apply().

        `start` locates the beginning, inside block (idx, subidx). `end`, when
        given, locates the finish — searched forward from `start`, so it may sit
        in a later block; pass `end_subidx` to require a specific one.

        mode="consume"  — the replacement takes the markers' place.
        mode="preserve" — the markers stay; only what lies between them changes.
        """
        if mode not in ("consume", "preserve"):
            raise MultiEditError(f"mode must be 'consume' or 'preserve', got {mode!r}")
        block = self.blocks.get((idx, subidx))
        if block is None:
            raise MultiEditError(
                f"no block idx:{idx} subidx:{subidx} — read() it first"
            )

        body = self.files[block.path]
        window = body[block.char_start:block.char_end]
        label = f"idx:{idx} subidx:{subidx}"

        hits = window.count(start)
        if hits == 0:
            raise MultiEditError(f"{label}: start marker {start!r} not in block")
        if hits > 1:
            raise MultiEditError(
                f"{label}: start marker {start!r} occurs {hits} times in block; "
                f"lengthen it until it is unique"
            )
        s_at = block.char_start + window.index(start)

        if end is None:
            e_from, e_to = s_at, s_at + len(start)
        else:
            if end_subidx is None:
                search_from, search_to = s_at + len(start), len(body)
                scope = "after the start marker"
            else:
                eb = self.blocks.get((idx, end_subidx))
                if eb is None:
                    raise MultiEditError(
                        f"{label}: no end block idx:{idx} subidx:{end_subidx}"
                    )
                search_from, search_to = max(eb.char_start, s_at + len(start)), eb.char_end
                scope = f"in block subidx:{end_subidx}"
            region = body[search_from:search_to]
            hits = region.count(end)
            if hits == 0:
                raise MultiEditError(f"{label}: end marker {end!r} not found {scope}")
            if hits > 1:
                raise MultiEditError(
                    f"{label}: end marker {end!r} occurs {hits} times {scope}; "
                    f"lengthen it until it is unique"
                )
            e_at = search_from + region.index(end)
            e_from, e_to = s_at, e_at + len(end)

        if mode == "consume":
            lo, hi = e_from, e_to
        else:
            lo, hi = s_at + len(start), (e_to - len(end) if end is not None else s_at + len(start))

        self.pending.append(_PendingEdit(block.path, lo, hi, text, label))

    def apply(self) -> dict[str, int]:
        """Write every staged edit. Overlaps are refused before anything writes."""
        by_path: dict[str, list[_PendingEdit]] = {}
        for e in self.pending:
            by_path.setdefault(e.path, []).append(e)

        for path, edits in by_path.items():
            edits.sort(key=lambda e: e.char_start)
            for a, b in zip(edits, edits[1:]):
                if a.char_end > b.char_start:
                    raise MultiEditError(
                        f"{path}: {a.label} and {b.label} overlap; nothing written"
                    )

        results = {}
        for path, edits in by_path.items():
            body = self.files[path]
            for e in sorted(edits, key=lambda e: e.char_start, reverse=True):
                body = body[:e.char_start] + e.text + body[e.char_end:]
            _atomic_write(path, body)
            self.files[path] = body
            results[path] = len(edits)

        self.pending.clear()
        return results


def _atomic_write(path: str, body: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    try:
        orig_mode = os.stat(path).st_mode
    except OSError:
        orig_mode = None
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".multiedit")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        if orig_mode is not None:
            os.chmod(tmp, orig_mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ----------------------------------------------------------------- CLI handlers

def _cmd_read(args) -> int:
    m = MultiEdit(granularity=args.granularity)
    try:
        print(m.read(*args.paths))
    except (OSError, MultiEditError) as exc:
        print(f"multiedit: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_edit(args) -> int:
    """Read files, apply edits from JSON on stdin, write atomically."""
    spec_text = sys.stdin.read()
    try:
        edits = json.loads(spec_text)
    except json.JSONDecodeError as exc:
        print(f"multiedit edit: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1

    if not isinstance(edits, list):
        print("multiedit edit: stdin must be a JSON array of edit objects", file=sys.stderr)
        return 1

    m = MultiEdit(granularity=args.granularity)
    for p in args.paths:
        if not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("")
            print(f"multiedit edit: created {p}")
    try:
        m.read(*args.paths)
    except (OSError, MultiEditError) as exc:
        print(f"multiedit edit: {exc}", file=sys.stderr)
        return 1

    applied = 0
    skipped = 0
    for i, spec in enumerate(edits):
        if not isinstance(spec, dict):
            print(f"multiedit edit: entry {i} is not an object", file=sys.stderr)
            return 1

        file_idx = spec.get("file", 0)
        block_idx = spec.get("block")
        if block_idx is None:
            print(f"multiedit edit: entry {i} missing 'block'", file=sys.stderr)
            return 1

        start = spec.get("start")
        if start is None:
            print(f"multiedit edit: entry {i} missing 'start'", file=sys.stderr)
            return 1

        if_contains = spec.get("if_contains")
        if_not_contains = spec.get("if_not_contains")
        if if_contains is not None or if_not_contains is not None:
            block = m.blocks.get((file_idx, block_idx))
            if block is None:
                print(f"multiedit edit: entry {i}: no block idx:{file_idx} subidx:{block_idx}",
                      file=sys.stderr)
                return 1
            window = m.files[block.path][block.char_start:block.char_end]
            if if_contains is not None and if_contains not in window:
                skipped += 1
                print(f"multiedit edit: entry {i} skipped (if_contains not matched)",
                      file=sys.stderr)
                continue
            if if_not_contains is not None and if_not_contains in window:
                skipped += 1
                print(f"multiedit edit: entry {i} skipped (if_not_contains matched)",
                      file=sys.stderr)
                continue

        try:
            m.edit(
                idx=file_idx,
                subidx=block_idx,
                start=start,
                end=spec.get("end"),
                text=spec.get("text", ""),
                mode=spec.get("mode", "consume"),
                end_subidx=spec.get("end_block"),
            )
            applied += 1
        except MultiEditError as exc:
            print(f"multiedit edit: entry {i}: {exc}", file=sys.stderr)
            return 1

    if applied == 0 and skipped > 0:
        print(f"multiedit edit: all {skipped} edit(s) skipped by conditions; nothing written")
        return 0

    if applied == 0:
        print("multiedit edit: no edits to apply")
        return 0

    try:
        results = m.apply()
        total = sum(results.values())
        files = len(results)
        msg = f"multiedit edit: {total} edit(s) applied across {files} file(s)"
        if skipped:
            msg += f", {skipped} skipped by conditions"
        print(msg)
    except MultiEditError as exc:
        print(f"multiedit edit: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_mv(args) -> int:
    try:
        shutil.move(args.src, args.dst)
    except OSError as exc:
        print(f"multiedit mv: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_cp(args) -> int:
    try:
        if os.path.isdir(args.src):
            shutil.copytree(args.src, args.dst)
        else:
            shutil.copy2(args.src, args.dst)
    except OSError as exc:
        print(f"multiedit cp: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_rm(args) -> int:
    for p in args.paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except OSError as exc:
            print(f"multiedit rm: {exc}", file=sys.stderr)
            return 1
    return 0


def _cmd_mkdir(args) -> int:
    for p in args.paths:
        try:
            os.makedirs(p, exist_ok=True)
        except OSError as exc:
            print(f"multiedit mkdir: {exc}", file=sys.stderr)
            return 1
    return 0


def _cmd_grep(args) -> int:
    try:
        pattern = re.compile(args.pattern)
    except re.error as exc:
        print(f"multiedit grep: bad pattern: {exc}", file=sys.stderr)
        return 1

    paths = args.paths
    if not paths:
        paths = ["."]

    expanded: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    expanded.append(os.path.join(root, f))
        else:
            expanded.append(p)

    found_any = False
    ctx = args.context
    for filepath in expanded:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                file_lines = fh.readlines()
        except OSError:
            continue

        matches: list[int] = []
        for i, line in enumerate(file_lines):
            if pattern.search(line):
                matches.append(i)

        if not matches:
            continue
        found_any = True

        shown: set[int] = set()
        for m_idx in matches:
            lo = max(0, m_idx - ctx)
            hi = min(len(file_lines), m_idx + ctx + 1)
            for li in range(lo, hi):
                if li not in shown:
                    shown.add(li)
                    prefix = "  " if li != m_idx else "> "
                    print(f"{filepath}:{li + 1}:{prefix}{file_lines[li].rstrip()}")
            if ctx > 0 and m_idx != matches[-1]:
                print("--")

    return 0 if found_any else 1


def _cmd_hash(args) -> int:
    for p in args.paths:
        try:
            with open(p, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()[:12]
            print(f"{h}  {p}")
        except OSError as exc:
            print(f"multiedit hash: {exc}", file=sys.stderr)
            return 1
    return 0


def _cmd_wc(args) -> int:
    for p in args.paths:
        try:
            with open(p, "rb") as fh:
                raw = fh.read()
            text = raw.decode("utf-8", errors="replace")
            lines = text.count("\n")
            words = len(text.split())
            bytes_ = len(raw)
            print(f"{lines:>8} {words:>8} {bytes_:>8} {p}")
        except OSError as exc:
            print(f"multiedit wc: {exc}", file=sys.stderr)
            return 1
    return 0


# ----------------------------------------------------------------- CLI main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Block-addressed batch file read/write tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("read", help="emit block-addressed text for many files")
    r.add_argument("paths", nargs="+")
    r.add_argument("--granularity", type=int, default=DEFAULT_GRANULARITY)

    e = sub.add_parser("edit", help="read files, apply edits from JSON on stdin")
    e.add_argument("paths", nargs="+")
    e.add_argument("--granularity", type=int, default=DEFAULT_GRANULARITY)

    mv = sub.add_parser("mv", help="move / rename")
    mv.add_argument("src")
    mv.add_argument("dst")

    cp = sub.add_parser("cp", help="copy file or directory")
    cp.add_argument("src")
    cp.add_argument("dst")

    rm = sub.add_parser("rm", help="remove files or directories")
    rm.add_argument("paths", nargs="+")

    mk = sub.add_parser("mkdir", help="create directories")
    mk.add_argument("paths", nargs="+")

    g = sub.add_parser("grep", help="search for pattern in files")
    g.add_argument("pattern")
    g.add_argument("paths", nargs="*")
    g.add_argument("-C", "--context", type=int, default=0)

    h = sub.add_parser("hash", help="sha256 short hash per file")
    h.add_argument("paths", nargs="+")

    w = sub.add_parser("wc", help="line / word / byte counts")
    w.add_argument("paths", nargs="+")

    args = ap.parse_args(argv)

    dispatch = {
        "read": _cmd_read,
        "edit": _cmd_edit,
        "mv": _cmd_mv,
        "cp": _cmd_cp,
        "rm": _cmd_rm,
        "mkdir": _cmd_mkdir,
        "grep": _cmd_grep,
        "hash": _cmd_hash,
        "wc": _cmd_wc,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        ap.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
