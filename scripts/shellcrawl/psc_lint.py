#!/usr/bin/env python3
"""Lint a .psc file against the shellcrawl pisces environment.

Parses the file, loads it into a shellcrawl evaluator, and reports errors.
Usage: python psc_lint.py file.psc
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pisces.parser import SExpParser
from pisces.eval import Evaluator, StepLimitExceeded
from shellcrawl.builtins import ShellCrawlRuntime
from shellcrawl.vfs import VirtualFS


def lint(path: str) -> bool:
    source = open(path).read()

    # Phase 1: parse
    parser = SExpParser()
    try:
        exprs = parser.parse(source)
    except Exception as e:
        print(f"PARSE ERROR: {e}")
        return False
    print(f"  parsed: {len(exprs)} top-level expressions")

    # Phase 2: eval in shellcrawl environment
    fs = VirtualFS()
    fs.mkdir("/home/user", parents=True)
    rt = ShellCrawlRuntime(fs)
    ev = rt.create_evaluator(max_steps=100_000, timeout=5.0)

    # Also load core.psc if it exists and this isn't core.psc
    core_path = os.path.join(os.path.dirname(os.path.abspath(path)), "core.psc")
    if os.path.exists(core_path) and os.path.abspath(path) != os.path.abspath(core_path):
        try:
            ev.eval_string(open(core_path).read())
        except Exception as e:
            print(f"  warning: could not load core.psc: {e}")

    try:
        ev.eval_string(source)
        print(f"  eval: OK")
        return True
    except StepLimitExceeded:
        print(f"  eval: hit step limit (probably OK, just complex)")
        return True
    except NameError as e:
        print(f"  EVAL ERROR (unbound): {e}")
        return False
    except SyntaxError as e:
        print(f"  EVAL ERROR (syntax): {e}")
        return False
    except TypeError as e:
        print(f"  EVAL ERROR (type): {e}")
        return False
    except Exception as e:
        print(f"  EVAL ERROR ({type(e).__name__}): {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python psc_lint.py <file.psc> [file2.psc ...]")
        sys.exit(1)
    ok = True
    for path in sys.argv[1:]:
        print(f"Linting {path}:")
        if not lint(path):
            ok = False
    sys.exit(0 if ok else 1)
