"""
Xylem xonshrc — Loaded when xonsh starts inside the xylem terminal.

Sets up:
- Hy bridge (import hy and make it accessible)
- Xylem environment variables
- Convenience commands
"""

import os
import sys

# Make sure we can reach xylem modules
_xylem_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _xylem_src not in sys.path:
    sys.path.insert(0, _xylem_src)

# ── Hy bridge ──────────────────────────────────────────────────────

def _init_hy():
    """Import Hy and make it available in xonsh namespace."""
    try:
        import hy
        # Hy now compiles .hy files to Python AST at import time.
        # We import the xylem agent module which triggers any .hy files.
        try:
            from xylem import agent  # noqa: F401
            print("[xylem] Hy agent loaded")
        except ImportError:
            print("[xylem] Hy available (no agent module yet)")
        return hy
    except ImportError:
        print("[xylem] Hy not installed — 'pip install hy' to enable")
        return None


_hy = _init_hy()


# ── Convenience commands ───────────────────────────────────────────

def _xylem_hello(args):
    """Quick check that xylem's xonsh integration works."""
    print(f"xylem active (PID {os.getpid()})")
    print(f"  python: {sys.version.split()[0]}")
    if _hy:
        print(f"  hy:     {hy.__version__}")
    print(f"  xonsh:  hello")


aliases["xylem"] = _xylem_hello


# ── Prompt ─────────────────────────────────────────────────────────

__xonsh__.env["PROMPT"] = "{GREEN}xylem{WHITE} {BLUE}{cwd}{WHITE} > "
