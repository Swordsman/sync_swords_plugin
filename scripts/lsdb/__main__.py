"""Run as `python3 <plugin>/scripts/lsdb ...` (or `python3 -m lsdb` with scripts/ on the path)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lsdb.cli import main  # noqa: E402

sys.exit(main())
