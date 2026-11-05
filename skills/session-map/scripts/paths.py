"""Where sibling tools live: inside the sync_swords_plugin layout (skills/session-map/scripts next to
skills/jev-toolkit/scripts and scripts/littlewing), or the working copies under /home/claude. Env vars override."""
from __future__ import annotations

import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def _first(env: str, *candidates: pathlib.Path) -> pathlib.Path:
    if os.environ.get(env):
        return pathlib.Path(os.environ[env])
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"set {env}: none of {[str(c) for c in candidates]} exists")


JEV_TOOLKIT = _first("JEV_TOOLKIT", HERE.parents[1] / "jev-toolkit" / "scripts",
                     pathlib.Path("/home/claude/skills/jev-toolkit/scripts"))
LITTLEWING = _first("LITTLEWING_DIR", HERE.parents[2] / "scripts" / "littlewing",
                    pathlib.Path("/home/claude/sync_swords_plugin/scripts/littlewing"))
PLUGIN = _first("SYNC_SWORDS_PLUGIN", HERE.parents[2], pathlib.Path("/home/claude/sync_swords_plugin"))
if not (PLUGIN / "skills" / "winnow").is_dir():   # HERE.parents[2] exists outside the plugin too: check its shape
    PLUGIN = pathlib.Path(os.environ.get("SYNC_SWORDS_PLUGIN", "/home/claude/sync_swords_plugin"))
RUNS = pathlib.Path(os.environ.get("COMPACTION_RUNS", pathlib.Path.home() / "compaction-check" / "runs"))
