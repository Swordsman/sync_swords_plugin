"""Format plugin discovery for littlewing output.

Drop a .py file in this directory to add a format. Each plugin exports:
    NAME: str           — CLI name (e.g. "plain")
    DESCRIPTION: str    — one-liner for help text
    EXT: str            — file extension (e.g. ".txt")
    format_conversation(events: list[dict], metadata: dict) -> str

Events are dicts with keys: role, timestamp, text.
Metadata has: session_id, project, first_ts, last_ts.
"""

import importlib.util
from pathlib import Path

_FORMAT_DIR = Path(__file__).parent


def discover():
    """Scan this directory for format plugins. Returns {name: module}."""
    formats = {}
    for py_file in sorted(_FORMAT_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            continue
        name = getattr(mod, "NAME", None)
        if name and hasattr(mod, "format_conversation"):
            formats[name] = mod
    return formats
