"""winnow transcript format: `[tN speaker]` turns, same-speaker runs merged."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from transcript import number_turns, render_winnow  # noqa: E402

NAME = "winnow"
DESCRIPTION = "winnow transcript ([tN speaker] turns), input for winnow.py"
EXT = ".txt"


def format_conversation(events, metadata):
    return render_winnow(number_turns(events))
