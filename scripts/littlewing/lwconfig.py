"""littlewing configuration: layered JSON, environment overrides last.

Layers, later wins (dicts merge key by key, lists replace):
  1. built-in DEFAULTS: both recording modes off, records kept on disk
  2. user file     $XDG_CONFIG_HOME/littlewing/config.json (~/.config/...)
  3. project file  .littlewing.json at the repo root (or the cwd)
  4. LITTLEWING_CONFIG       path to one more config file
  5. LITTLEWING_CONFIG_JSON  inline JSON; the easy route in cloud
                             environments, where only env vars carry over
  6. shortcuts:
       LITTLEWING_HOME   state, outbox and local records root
       LITTLEWING_RAW    raw JSONL mode: off | on | <sink name>
       LITTLEWING_WNO    winnow mode:    off | on | <sink name>
       LITTLEWING_DOCS   comma-separated Claude Docs urls; defines sink "docs"

Strings may use {home} (the resolved home) and ~.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

DEFAULTS = {
    "home": "~/.littlewing",
    # where the older CLI commands (ingest, list, bridge, overlay) keep
    # whole-session copies; point it at any directory or repo checkout
    "archive": "{home}/archive",
    "modes": {
        "raw": {
            "enabled": False,
            "sink": "disk",
            # None = automatic: xz, plus base85 when the sink takes text only
            "transforms": None,
            # raw bytes per piece; 32 MiB packs to ~8 MB of base85, well
            # under the 20 MiB Claude Docs upload cap
            "max_piece_bytes": 33554432,
        },
        "wno": {
            "enabled": False,
            "sink": "disk",
            "transforms": None,     # automatic: none (a .wno is text)
            "winnow": None,         # path to winnow.py; None = plugin copy
            "backend": "deepseek",
            "model": "flash",
            "think": "max",         # thinking effort; Joe: never run winnow below max
            "args": [],             # extra winnow.py arguments
            "env": {},              # extra environment for the winnow run
            "timeout": 6600,        # max effort is slow; stays under the hooks' 7200 s
        },
    },
    "sinks": {
        "disk": {"transport": "local", "root": "{home}/records"},
    },
    "triggers": {
        "push": True,           # after a `git push` (PostToolUse on Bash)
        "pr": True,             # after a pull request is created
        "compact": True,        # before compaction (PreCompact)
        "session_end": True,    # SessionEnd; Claude can't act then, so
                                # queued sinks wait for the next session
        "session_start": True,  # remind Claude of uploads still queued
        "stop": {               # backup, after each reply
            "enabled": True,
            "direct_min_bytes": 1,          # hook-written sinks: any growth
            "queued_min_bytes": 1048576,    # Claude-uploaded sinks: 1 MiB
            "direct_min_turns": 1,
            "queued_min_turns": 20,
        },
        "renotify_minutes": 60,  # re-ask about a queued upload at most this often
    },
}

_OFF = {"", "0", "off", "false", "no", "none"}
_ON = {"1", "on", "true", "yes"}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ValueError(f"littlewing config {path}: {e}") from e


def repo_root(cwd: str | None) -> Path | None:
    if not cwd:
        return None
    p = Path(cwd).resolve()
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return d
    return p


def config_files(cwd: str | None = None, env=None) -> list[Path]:
    env = os.environ if env is None else env
    xdg = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    files = [Path(xdg) / "littlewing" / "config.json"]
    root = repo_root(cwd)
    if root:
        files.append(root / ".littlewing.json")
    if env.get("LITTLEWING_CONFIG"):
        files.append(Path(env["LITTLEWING_CONFIG"]).expanduser())
    return files


def _mode_switch(cfg: dict, mode: str, value: str) -> None:
    v = value.strip()
    m = cfg["modes"][mode]
    if v.lower() in _OFF:
        m["enabled"] = False
    elif v.lower() in _ON:
        m["enabled"] = True
    else:
        m["enabled"] = True
        m["sink"] = v


def load(cwd: str | None = None, env=None) -> dict:
    env = os.environ if env is None else env
    cfg = copy.deepcopy(DEFAULTS)
    for f in config_files(cwd, env):
        cfg = deep_merge(cfg, _read_json(f))
    if env.get("LITTLEWING_CONFIG_JSON"):
        try:
            cfg = deep_merge(cfg, json.loads(env["LITTLEWING_CONFIG_JSON"]))
        except ValueError as e:
            raise ValueError(f"LITTLEWING_CONFIG_JSON: {e}") from e
    if env.get("LITTLEWING_HOME"):
        cfg["home"] = env["LITTLEWING_HOME"]
    if env.get("LITTLEWING_DOCS"):
        docs = [u.strip() for u in env["LITTLEWING_DOCS"].split(",") if u.strip()]
        cfg["sinks"]["docs"] = deep_merge(cfg["sinks"].get("docs", {}),
                                          {"transport": "claude-docs", "docs": docs})
    for mode, var in (("raw", "LITTLEWING_RAW"), ("wno", "LITTLEWING_WNO")):
        if var in env:
            _mode_switch(cfg, mode, env[var])
    cfg["home"] = str(Path(cfg["home"]).expanduser())
    return expand(cfg, cfg["home"])


def expand(value, home: str):
    if isinstance(value, str):
        s = value.replace("{home}", home)
        return str(Path(s).expanduser()) if s.startswith("~") else s
    if isinstance(value, dict):
        return {k: expand(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, home) for v in value]
    return value


def any_enabled(cfg: dict) -> bool:
    return any(m.get("enabled") for m in cfg["modes"].values())


def archive_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load(os.getcwd())
    return Path(cfg["archive"])


def build_store(cfg: dict, mode: str):
    """The Store (transport + transforms) a mode writes through."""
    from backends import Store
    from backends.transports import Transport
    from backends.transforms import Transform

    m = cfg["modes"][mode]
    sink_name = m["sink"]
    if sink_name not in cfg["sinks"]:
        raise KeyError(f"mode {mode!r} uses sink {sink_name!r}, which isn't configured "
                       f"(known: {', '.join(sorted(cfg['sinks']))})")
    sink = cfg["sinks"][sink_name]
    tname = sink["transport"]
    kwargs = {k: v for k, v in sink.items() if k not in ("transport", "transforms")}
    tcls = Transport.get(tname)
    if getattr(tcls, "agent_mediated", False):
        kwargs.setdefault("outbox", cfg["home"])
    transport = tcls(**kwargs)

    spec = m.get("transforms")
    if spec is None:
        spec = sink.get("transforms")
    if spec is None:
        spec = ["xz"] if mode == "raw" else []
    chain = []
    for item in spec:
        item = {"name": item} if isinstance(item, str) else dict(item)
        name = item.pop("name")
        chain.append(Transform.get(name)(**item))
    # every transform but base85 emits binary; a text-only sink needs armor
    if getattr(transport, "text_only", False) and chain and chain[-1].name != "base85":
        chain.append(Transform.get("base85")())
    return Store(transport=transport, transforms=chain)
