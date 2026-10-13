"""Session recorder: ships a live session log through the configured modes.

Two modes, switched on separately (see lwconfig.py):

  raw  the session JSONL itself, as contiguous byte-range pieces. Each run
       ships the complete lines added since the last run; joining the
       pieces in order rebuilds the log byte for byte (`littlewing.py
       restore`).
  wno  a winnow record. Each run feeds winnow the turns closed since the
       last run, seeded with the record so far, and ships only the new
       deltas. Joining the parts in order gives the whole .wno log.

Each mode writes through one sink (a Store). A sink is either direct (the
hook writes it: local, git, rclone) or queued (claude-docs: the hook fills
an outbox and asks Claude to upload).

State lives under <home>/state/<session>/, one JSON file per mode and
sink, so changing a mode's sink mid-session starts that sink from zero.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lwconfig  # noqa: E402
import transcript as tx  # noqa: E402

try:
    import fcntl
except ImportError:          # Windows: run unlocked
    fcntl = None

TRIGGERS = ("push", "pr", "stop", "compact", "session_end", "session_start", "manual")
DEFAULT_WINNOW = HERE.parent / "winnow" / "winnow.py"
SCRIPT = HERE / "littlewing.py"


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@contextmanager
def _lock(path: Path, wait: float):
    """File lock; yields False when it can't be had within `wait` seconds."""
    if fcntl is None:
        yield True
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.2)
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


class Recorder:
    def __init__(self, cfg: dict, session_id: str, transcript_path: str,
                 cwd: str | None = None):
        self.cfg = cfg
        self.home = Path(cfg["home"])
        self.session_id = session_id
        self.transcript = Path(transcript_path)
        root = lwconfig.repo_root(cwd) if cwd else None
        self.repo = (root.name if root else None) or "unknown"
        self.state_dir = self.home / "state" / session_id
        self.results: list[dict] = []
        self.final = False

    # ------------------------------------------------------------ plumbing

    def log(self, **entry) -> None:
        entry = {"ts": _stamp(), "session": self.session_id, **entry}
        self.results.append(entry)
        try:
            self.home.mkdir(parents=True, exist_ok=True)
            with open(self.home / "littlewing.log", "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def _state_path(self, mode: str, sink: str) -> Path:
        return self.state_dir / f"{mode}.{sink}.json"

    def _load(self, mode: str, sink: str) -> dict:
        try:
            return json.loads(self._state_path(mode, sink).read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, mode: str, sink: str, st: dict) -> None:
        p = self._state_path(mode, sink)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".partial")
        tmp.write_text(json.dumps(st, indent=2) + "\n")
        os.replace(tmp, p)

    def _trigger_on(self, trigger: str) -> bool:
        t = self.cfg["triggers"]
        if trigger == "manual":
            return True
        v = t.get(trigger)
        return bool(v.get("enabled", True)) if isinstance(v, dict) else bool(v)

    def _minimum(self, trigger: str, queued: bool, unit: str) -> int:
        if trigger != "stop":
            return 1
        stop = self.cfg["triggers"].get("stop") or {}
        return int(stop.get(f"{'queued' if queued else 'direct'}_min_{unit}", 1))

    def _meta(self, mode: str, part: int, trigger: str, **kw) -> dict:
        return {"mode": mode, "session": self.session_id, "repo": self.repo,
                "part": part, "trigger": trigger, "date": _today(), **kw}

    # ------------------------------------------------------------ entry

    def run(self, trigger: str, hook: dict | None = None,
            final: bool = False) -> list[dict]:
        """Run every enabled mode for `trigger`. Never raises.

        `final` treats the session as over: the last turn counts as closed.
        """
        hook = hook or {}
        self.final = final or trigger == "session_end"
        if trigger not in TRIGGERS or not self._trigger_on(trigger):
            return self.results
        if trigger == "session_start":
            return self.results
        if not self.transcript.is_file():
            self.log(event="skip", why=f"no transcript at {self.transcript}")
            return self.results
        for mode, fn in (("raw", self._run_raw), ("wno", self._run_wno)):
            m = self.cfg["modes"].get(mode) or {}
            if not m.get("enabled"):
                continue
            try:
                store = lwconfig.build_store(self.cfg, mode)
                fn(trigger, store, m, hook)
            except Exception as e:  # a recorder failure must never surface as a hook failure
                self.log(event="error", mode=mode, trigger=trigger,
                         error=f"{type(e).__name__}: {e}")
        return self.results

    # ------------------------------------------------------------ raw

    def _run_raw(self, trigger: str, store, m: dict, hook: dict) -> None:
        sink = m["sink"]
        with _lock(self.state_dir / f"raw.{sink}.lock", wait=60) as ok:
            if not ok:
                self.log(event="skip", mode="raw", why="locked")
                return
            st = self._load("raw", sink)
            offset, part = st.get("offset", 0), st.get("part", 0)
            size = self.transcript.stat().st_size
            if size < offset:                 # log was replaced; start over
                self.log(event="reset", mode="raw", was=offset, size=size)
                offset = 0
            if size - offset < self._minimum(trigger, store.agent_mediated, "bytes"):
                return
            cap = int(m.get("max_piece_bytes") or 0) or (1 << 62)
            with open(self.transcript, "rb") as f:
                f.seek(offset)
                while offset < size:
                    chunk = f.read(min(cap, size - offset))
                    cut = chunk.rfind(b"\n") + 1
                    while cut == 0 and offset + len(chunk) < size:
                        # one line longer than the cap: the piece is that line
                        more = f.read(min(cap, size - offset - len(chunk)))
                        if not more:              # log shrank under us
                            break
                        nl = more.find(b"\n")
                        chunk += more
                        if nl >= 0:
                            cut = len(chunk) - len(more) + nl + 1
                    if cut == 0:              # no complete line yet
                        break
                    data = chunk[:cut]
                    f.seek(offset + cut)
                    part += 1
                    start, end = offset, offset + cut
                    key = (f"raw/{self.repo}/{self.session_id}/"
                           f"p{part:04d}_{start}-{end}.jsonl{store.suffix}")
                    store.write(key, data, meta=self._meta(
                        "raw", part, trigger, range=[start, end],
                        raw_sha256=hashlib.sha256(data).hexdigest()))
                    offset = end
                    st.update(offset=offset, part=part, updated=_stamp())
                    self._save("raw", sink, st)
                    self.log(event="shipped", mode="raw", sink=sink, key=key,
                             bytes=len(data), queued=store.agent_mediated)

    # ------------------------------------------------------------ wno

    def _run_wno(self, trigger: str, store, m: dict, hook: dict) -> None:
        sink = m["sink"]
        # winnow runs for minutes; a second trigger meanwhile just skips,
        # and the next one after it picks up the turns it missed
        with _lock(self.state_dir / f"wno.{sink}.lock", wait=0) as ok:
            if not ok:
                self.log(event="skip", mode="wno", why="winnow already running")
                return
            st = self._load("wno", sink)
            done, part = st.get("turn", 0), st.get("part", 0)
            turns = tx.number_turns(tx.events_from_jsonl(self.transcript))
            closed = tx.closed_turns(turns, hook.get("last_assistant_message"),
                                     final=self.final)
            new = [t for t in closed if t[0] > done]
            replies = sum(1 for t in new if t[1] == "assistant")
            if not new or replies < self._minimum(trigger, store.agent_mediated, "turns"):
                return

            work = self.state_dir / f"wno.{sink}"
            work.mkdir(parents=True, exist_ok=True)
            full, nxt, inp = work / "record.wno", work / "next.wno", work / "input.txt"
            inp.write_text(tx.render_winnow(new))
            winnow = Path(m.get("winnow") or DEFAULT_WINNOW)
            cmd = [sys.executable, str(winnow), str(inp), "--out", str(nxt),
                   "--backend", m.get("backend", "deepseek"), "--model", m.get("model", "flash"),
                   *[str(a) for a in m.get("args") or []]]
            if full.exists():
                cmd += ["--seed", str(full)]
            env = dict(os.environ, **{k: str(v) for k, v in (m.get("env") or {}).items()})
            nxt.unlink(missing_ok=True)
            first, last = new[0][0], new[-1][0]
            failed = None
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                   timeout=int(m.get("timeout", 1500)))
                if r.returncode != 0 or not nxt.exists():
                    failed = {"error": "winnow failed", "code": r.returncode,
                              "stderr": r.stderr[-2000:]}
            except subprocess.TimeoutExpired:
                failed = {"error": "winnow timed out"}
            if failed:
                self.log(event="error", mode="wno", turns=[first, last], **failed)
                # winnow rewrites its log after every batch, so what it got
                # through before failing is a valid record: keep that, and
                # retry only the turns after it next time
                reached = _last_turn(winnow, nxt.read_text()) if nxt.exists() else 0
                if reached <= done:
                    return
                last = reached
                self.log(event="salvaged", mode="wno", turns=[first, last])

            old = full.read_text() if full.exists() else ""
            fresh = nxt.read_text()
            piece, kind = _new_part(winnow, old, fresh)
            if piece.strip():
                part += 1
                key = (f"wno/{self.repo}/{self.session_id}/"
                       f"p{part:04d}_t{first}-t{last}.wno{store.suffix}")
                store.write(key, piece.encode(), meta=self._meta(
                    "wno", part, trigger, turns=[first, last], kind=kind,
                    log_id=f"wno-{_today().replace('-', '')}-{self.repo}-"
                           f"{self.session_id[:8]}-p{part}"))
                self.log(event="shipped", mode="wno", sink=sink, key=key,
                         bytes=len(piece), kind=kind, queued=store.agent_mediated)
            else:
                self.log(event="no-signal", mode="wno", turns=[first, last])
            os.replace(nxt, full)
            st.update(turn=last, part=part, updated=_stamp())
            self._save("wno", sink, st)


def _sexpr(winnow: Path):
    """winnow's own s-expression reader: sexpr.py beside the configured
    winnow.py (older winnow copies keep it inside fold.py), else the
    plugin's own copy."""
    import importlib.util
    candidates = [d / f for d in (winnow.parent, DEFAULT_WINNOW.parent)
                  for f in ("sexpr.py", "fold.py")]
    src = next(c for c in candidates if c.exists())
    spec = importlib.util.spec_from_file_location("_lw_winnow_sexpr", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _last_turn(winnow: Path, text: str) -> int:
    """The highest `:turn` any delta in a .wno log carries (0 if none)."""
    sx = _sexpr(winnow)
    turns = [sx.anns(f[1:3]).get("turn") for f in sx.parse(sx.tokenize(text))
             if f and f[0] == "delta"]
    return max((int(t) for t in turns if str(t).isdigit()), default=0)


def _new_part(winnow: Path, old: str, fresh: str) -> tuple[str, str]:
    """What a seeded winnow run added: (text to ship, kind).

    winnow re-serializes the seed's forms when it continues a record, so the
    new output doesn't start with the old text byte for byte. Compare parsed
    forms instead: when the old record's forms open the new one, ship only
    the forms after them ("delta"); otherwise ship it all ("full", or
    "full-rewrite" when a record existed but no longer matches).
    """
    if not old:
        return fresh, "full"
    sx = _sexpr(winnow)

    def body(text):
        return [sx.sx(f) for f in sx.parse(sx.tokenize(text)) if f and f[0] != "meta"]

    was, now = body(old), body(fresh)
    if now[:len(was)] == was:
        added = now[len(was):]
        return ("\n\n".join(added) + "\n" if added else ""), "delta"
    return fresh, "full-rewrite"


# ------------------------------------------------------------ notices

def queued_sinks(cfg: dict) -> list[str]:
    """Names of enabled modes' sinks that Claude has to upload."""
    from backends.transports import Transport
    out = []
    for m in cfg["modes"].values():
        if not m.get("enabled"):
            continue
        s = cfg["sinks"].get(m.get("sink"), {})
        try:
            if getattr(Transport.get(s.get("transport", "")), "agent_mediated", False):
                out.append(m["sink"])
        except KeyError:
            continue
    return out


DEFAULT_STEPS = [
    "Upload the file to the first doc listed: Artifact tool, publish with "
    "url=<doc>, file_path=<file>, asset=true. If the doc is full (1 GiB or "
    "5,000 uploads), use the next doc; if none is left, tell the user.",
    "Add a row for it to that doc's index table: Date | Repo | Log id | "
    "Record | Asset id | What it covers. Raw pieces go in a table on a tab "
    "named Raw.",
    "Mark it sent: {script} outbox done <id> --asset <asset id> "
    "(add --doc <url> if it went to a doc other than the first).",
]


def notice(cfg: dict, force: bool = False) -> tuple[str | None, list[str]]:
    """Text asking Claude to upload queued records, plus the ids it covers.

    Returns (None, []) when nothing is due. An entry is due when it was
    never announced, or was announced over `renotify_minutes` ago.
    """
    from backends.transports.claude_docs import Outbox
    pending = Outbox(cfg["home"]).pending()
    if not pending:
        return None, []
    gap = 60 * float(cfg["triggers"].get("renotify_minutes", 60))
    now = time.time()
    due = [p for p in pending if force or now - p.get("announced_epoch", 0) >= gap]
    if not due:
        return None, []
    steps = DEFAULT_STEPS
    for name in queued_sinks(cfg):
        steps = cfg["sinks"][name].get("steps") or steps
        break
    docs = []
    for p in pending:
        for d in p.get("docs") or []:
            if d not in docs:
                docs.append(d)
    lines = [f"littlewing: {len(pending)} session record(s) queued for upload to Claude Docs. "
             "Upload them now, then carry on with what you were doing.",
             "Docs, in order: " + ", ".join(docs), "Steps for each file:"]
    lines += [f"  {i}. {s.replace('{script}', f'python3 {SCRIPT}')}"
              for i, s in enumerate(steps, 1)]
    lines.append("Queued:")
    for p in pending:
        what = (f"bytes {p['range'][0]}-{p['range'][1]}" if p.get("range")
                else f"turns t{p['turns'][0]}-t{p['turns'][1]}" if p.get("turns") else "")
        lines.append(f"  id={p['id']}  {p.get('mode')} part {p.get('part')} of "
                     f"{p.get('repo')} session {str(p.get('session'))[:8]}, {what}"
                     + (f", log id {p['log_id']}" if p.get("log_id") else "")
                     + f"\n    file={p['file']}")
    lines.append("Details: the littlewing skill, section \"Uploading queued records\".")
    return "\n".join(lines), [p["id"] for p in due]
