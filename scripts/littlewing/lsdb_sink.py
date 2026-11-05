"""littlewing's lsdb backend: a session doc plus the winnow record (and optionally the raw log, one blob per generation) in an artifact db.

Off unless `lsdb.url` is set (config) or LITTLEWING_LSDB names a store. Per session it writes
`sessions/<id>` (title, start, update, sizes, where the other records went) and the .wno record
as blob `wno-<id>`; with `lsdb.raw` also the JSONL as blob `raw-<id>`, skipped past `lsdb.raw_max_bytes`
because an artifact holds 100 MB in all. sync() never raises and gives up after `lsdb.budget` seconds.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the plugin's scripts/, for the lsdb package

STATE_FILE = "lsdb.json"
DESCRIPTION = "One doc per recorded Claude Code session: title, times, sizes, where its records went"


def enabled(cfg: dict) -> bool:
    return bool((cfg.get("lsdb") or {}).get("url"))


def sync(rec, trigger: str) -> None:
    """Push `rec`'s session to the store, in a thread bounded by the budget. Never raises."""
    cfg = rec.cfg.get("lsdb") or {}
    if not enabled(rec.cfg):
        return
    try:
        state = _load(rec)
        interval = float(cfg.get("stop_interval", 300))
        if trigger == "stop" and time.time() - state.get("synced_epoch", 0) < interval and state.get("url") == cfg["url"]:
            return
        worker = threading.Thread(target=_guarded, args=(rec, cfg, state, trigger), daemon=True)
        worker.start()
        worker.join(float(cfg.get("budget", 90)))
        if worker.is_alive():
            rec.log(event="error", mode="lsdb", trigger=trigger, error="over budget, abandoned")
    except Exception as exc:
        rec.log(event="error", mode="lsdb", trigger=trigger, error=f"{type(exc).__name__}: {exc}")


def _guarded(rec, cfg, state, trigger) -> None:
    try:
        _push(rec, cfg, state, trigger)
    except Exception as exc:          # LsdbEnvError off-session, LsdbApiError, OSError: all just logged
        rec.log(event="error", mode="lsdb", trigger=trigger, error=f"{type(exc).__name__}: {str(exc)[:300]}")


def _push(rec, cfg, state, trigger) -> None:
    import lsdb
    url = cfg["url"]
    if state.get("url") != url:
        state = {"url": url}
    blobs = {}
    record = rec.state_dir / f"wno.{rec.cfg['modes']['wno']['sink']}" / "record.wno"
    if record.is_file():
        text = record.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode()).hexdigest()
        if state.get("record_sha") != digest:
            lsdb.put_blob(url, f"wno-{rec.session_id}", text, {"session": rec.session_id, "repo": rec.repo})
            state["record_sha"] = digest
        blobs["wno"] = f"wno-{rec.session_id}"
    size = rec.transcript.stat().st_size
    if cfg.get("raw") and size <= int(cfg.get("raw_max_bytes", 20_000_000)):
        blobs["raw"] = _push_raw(rec, url, state, size)
    elif cfg.get("raw"):
        rec.log(event="skip", mode="lsdb", why=f"raw log {size} bytes is over raw_max_bytes")
    title, started = transcript_facts(rec.transcript)
    doc = {"id": rec.session_id, "repo": rec.repo, "title": title, "started": started, "updated": _now(),
           "trigger": trigger, "sizes": {"transcript": size, "record": record.stat().st_size if record.is_file() else 0},
           "blobs": blobs, "records": records_elsewhere(rec)}
    lsdb.set_doc(url, f"sessions/{rec.session_id}", doc)
    if not state.get("registered"):
        lsdb.register(url, "sessions", DESCRIPTION, view="table")
        state["registered"] = True
    state["synced_epoch"] = time.time()
    _save(rec, state)
    rec.log(event="shipped", mode="lsdb", trigger=trigger, blobs=sorted(blobs), bytes=size)


def _push_raw(rec, url, state, size) -> list[str]:
    """The log as blob raw-<id>. Compaction rewrites the log shorter, so a smaller or different head
    starts a new generation (raw-<id>-g2, ...) and the pre-compaction blob stays as it was."""
    import lsdb
    head = hashlib.sha256(rec.transcript.read_bytes()[:4096]).hexdigest()
    gen = state.get("raw_gen", 1)
    if state.get("raw_size") and (size < state["raw_size"] or head != state.get("raw_head")):
        gen += 1
    keys = [f"raw-{rec.session_id}" + (f"-g{n}" if n > 1 else "") for n in range(1, gen + 1)]
    if (gen, size) != (state.get("raw_gen"), state.get("raw_size")):
        text = rec.transcript.read_text(encoding="utf-8", errors="replace")
        lsdb.put_blob(url, keys[-1], text, {"session": rec.session_id, "repo": rec.repo, "generation": gen})
    state.update(raw_gen=gen, raw_size=size, raw_head=head)
    return keys


def records_elsewhere(rec) -> list[dict]:
    """Where the raw and wno modes put this session's records, from their state files."""
    out = []
    for mode, spec in rec.cfg["modes"].items():
        if spec.get("enabled"):
            sink = spec["sink"]
            st = rec._load(mode, sink)
            out.append({"mode": mode, "sink": sink, "transport": rec.cfg["sinks"].get(sink, {}).get("transport"),
                        "part": st.get("part", 0), "upto": st.get("offset", st.get("turn", 0))})
    return out


def transcript_facts(path: Path) -> tuple[str | None, str | None]:
    """(title, start time): a title entry if the log has one, else the first user prompt's opening."""
    title = prompt = started = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if prompt and started and 'itle"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            started = started or event.get("timestamp")
            kind = str(event.get("type", ""))
            if kind.endswith("title"):
                title = next((v for k, v in event.items() if "itle" in k and isinstance(v, str)), title)
            elif kind == "user" and not prompt:
                prompt = _prompt_text((event.get("message") or {}).get("content"))
    return title or (prompt[:80] if prompt else None), started


def _prompt_text(content) -> str | None:
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return " ".join(content.split()) if isinstance(content, str) and content.strip() else None


def _load(rec) -> dict:
    try:
        return json.loads((rec.state_dir / STATE_FILE).read_text())
    except (OSError, ValueError):
        return {}


def _save(rec, state: dict) -> None:
    rec.state_dir.mkdir(parents=True, exist_ok=True)
    (rec.state_dir / STATE_FILE).write_text(json.dumps(state))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
