#!/usr/bin/env python3
"""wno: the front door to winnow's tools. Each command is its own script;
this only dispatches.

    wno.py fold       LOG [--snapshot] [--upto N] [--yield-curve]
    wno.py frontier   LOG [--upto N]        what's still open
    wno.py digest     LOG [--upto N]        the tiered window a model sees
    wno.py basis      LOG [--undermined | --node ID | --rests-on ID]
                                            what each conclusion rests on
    wno.py query      LOG EXPR | --concepts | --stale [N] | --hashes
    wno.py extract    TRANSCRIPT --out LOG ...   (winnow.py)
    wno.py merge      ...                   (merge.py)
    wno.py split      ...                   (split.py)
    wno.py mega-fold  ...                   (mega-fold.py)
    wno.py term-table ...                   (term-table.py)

`wno.py COMMAND --help` (or no arguments) shows that script's own usage.
"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMANDS = {
    "fold": "fold.py",
    "frontier": "frontier.py",
    "digest": "digest.py",
    "basis": "basis.py",
    "query": "query.py",
    "extract": "winnow.py",
    "merge": "merge.py",
    "split": "split.py",
    "mega-fold": "mega-fold.py",
    "term-table": "term-table.py",
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if argv else 1
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"wno: unknown command {cmd!r}; one of: {', '.join(COMMANDS)}",
              file=sys.stderr)
        return 2
    script = HERE / COMMANDS[cmd]
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    sys.argv = [str(script), *rest]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
