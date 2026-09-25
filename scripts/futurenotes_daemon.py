#!/usr/bin/env python3
"""
FutureNotes Daemon — monitors Kimi CLI context files for <FutureNotes> tags
and persists extracted notes to notes.md and notes.db.

Usage:
    python daemon.py                        # run in foreground
    python daemon.py --poll-interval 5      # 5-second poll interval
    python daemon.py --session-dir ~/.kimi/sessions  # custom session path
"""

import json
import os
import re
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

# ── defaults ────────────────────────────────────────────────────────────────
DEFAULT_SESSION_DIR = os.path.expanduser("~/.kimi/sessions")
DEFAULT_POLL_INTERVAL = 3  # seconds
NOTES_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.md")
NOTES_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.db")

# Regex for <FutureNotes>...</FutureNotes> — dotall so it works across newlines
_TAG_RE = re.compile(r"<FutureNotes>(.*?)</FutureNotes>", re.DOTALL)


class FutureNotesDaemon:
    """Monitors the most-recently-active Kimi session's context.jsonl for
    structured <FutureNotes> tags, persists captures to Markdown and SQLite."""

    def __init__(
        self,
        session_dir: str = DEFAULT_SESSION_DIR,
        notes_md: str = NOTES_MD,
        notes_db: str = NOTES_DB,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ):
        self.session_dir = Path(session_dir)
        self.notes_md = Path(notes_md)
        self.notes_db = Path(notes_db)
        self.poll_interval = poll_interval
        self._running = False

        # File tracking
        self._current_file: Path | None = None
        self._last_inode: int | None = None
        self._last_position: int = 0

        # Deduplication cache (in-memory, backed by DB for restarts)
        self._seen_hashes: set[str] = set()

        # Ensure data files exist
        self._ensure_md()
        self._ensure_db()

    # ── startup helpers ─────────────────────────────────────────────────

    def _ensure_md(self) -> None:
        """Create notes.md if it does not exist."""
        if not self.notes_md.exists():
            self.notes_md.write_text(
                "# FutureNotes\n\nNotes extracted from Kimi CLI sessions.\n\n"
            )

    def _ensure_db(self) -> None:
        """Create notes.db and the `notes` table if they do not exist."""
        conn = sqlite3.connect(str(self.notes_db))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                status    TEXT    NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','active','done')),
                content_hash TEXT UNIQUE NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

    # ── session discovery ───────────────────────────────────────────────

    def _find_current_context_file(self) -> Path | None:
        """Return the context.jsonl of the most-recently-modified session
        subdirectory, or None if no session is available.

        Session layout:  sessions/<hash>/<uuid>/context.jsonl
        We pick the subdirectory whose context.jsonl has the newest mtime."""
        best_path: Path | None = None
        best_mtime: float = 0.0

        if not self.session_dir.is_dir():
            return None

        for session_hash_dir in self.session_dir.iterdir():
            if not session_hash_dir.is_dir():
                continue
            for subdir in session_hash_dir.iterdir():
                if not subdir.is_dir():
                    continue
                ctx = subdir / "context.jsonl"
                if not ctx.is_file():
                    continue
                try:
                    mtime = ctx.stat().st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_path = ctx

        return best_path

    # ── content extraction ──────────────────────────────────────────────

    @staticmethod
    def _extract_notes(text: str) -> list[str]:
        """Return all captured FutureNotes bodies in *text*."""
        return [m.strip() for m in _TAG_RE.findall(text)]

    @staticmethod
    def _content_hash(content: str) -> str:
        """SHA-256 hex digest of *content* (used for deduplication)."""
        return sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_text_from_line(line: str) -> str:
        """Given one JSON line from context.jsonl, extract every text/think
        payload from assistant content blocks and return them concatenated."""
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return ""

        # assistant messages carry a "content" list
        if obj.get("role") != "assistant":
            return ""

        content_list = obj.get("content")
        if not isinstance(content_list, list):
            return ""

        parts: list[str] = []
        for block in content_list:
            for key in ("text", "think"):
                val = block.get(key)
                if isinstance(val, str):
                    parts.append(val)
        return "\n".join(parts)

    # ── persistence ─────────────────────────────────────────────────────

    def _persist_note(self, timestamp: str, content: str) -> None:
        """Write a single note to both notes.md and notes.db."""
        chash = self._content_hash(content)

        # Dedup: check memory + DB
        if chash in self._seen_hashes:
            return
        if self._hash_exists_in_db(chash):
            self._seen_hashes.add(chash)
            return

        # Markdown append
        entry = (
            f"\n---\n"
            f"**{timestamp}**  \n"
            f"{content}\n"
        )
        with open(self.notes_md, "a") as fh:
            fh.write(entry)

        # SQLite insert
        conn = sqlite3.connect(str(self.notes_db))
        try:
            conn.execute(
                "INSERT INTO notes (timestamp, content, status, content_hash) "
                "VALUES (?, ?, 'pending', ?)",
                (timestamp, content, chash),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # hash collision or race — harmless
            pass
        finally:
            conn.close()

        self._seen_hashes.add(chash)

    def _hash_exists_in_db(self, chash: str) -> bool:
        """Return True if *chash* is already stored in notes.db."""
        conn = sqlite3.connect(str(self.notes_db))
        row = conn.execute(
            "SELECT 1 FROM notes WHERE content_hash = ?", (chash,)
        ).fetchone()
        conn.close()
        return row is not None

    # ── main loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        """Blocking main loop.  Polls for new context.jsonl lines every
        *poll_interval* seconds until stop() is called."""
        self._running = True

        while self._running:
            try:
                ctx_file = self._find_current_context_file()

                if ctx_file is None:
                    time.sleep(self.poll_interval)
                    continue

                # Detect file rotation (new file or inode change)
                try:
                    inode = ctx_file.stat().st_ino
                except OSError:
                    time.sleep(self.poll_interval)
                    continue

                if ctx_file != self._current_file or inode != self._last_inode:
                    # New file — reset position
                    self._current_file = ctx_file
                    self._last_inode = inode
                    self._last_position = 0

                self._scan_new_lines(ctx_file)

            except Exception:
                # Never let the daemon die on a transient error
                pass

            time.sleep(self.poll_interval)

    def _scan_new_lines(self, ctx_file: Path) -> None:
        """Read any new lines from *ctx_file* since last position and
        extract + persist any FutureNotes found."""
        try:
            with open(ctx_file, "r") as fh:
                fh.seek(0, os.SEEK_END)
                file_size = fh.tell()

                if file_size < self._last_position or self._last_position < 0:
                    # File was truncated or position invalid — reset
                    self._last_position = 0

                if file_size == self._last_position:
                    return  # nothing new

                fh.seek(self._last_position)
                new_data = fh.read()
                self._last_position = fh.tell()
        except OSError:
            return

        if not new_data:
            return

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for line in new_data.splitlines():
            line = line.strip()
            if not line:
                continue
            text = self._extract_text_from_line(line)
            if not text:
                continue
            for note in self._extract_notes(text):
                self._persist_note(now_utc, note)

    def stop(self) -> None:
        """Signal the main loop to exit gracefully."""
        self._running = False


# ── CLI entry point ─────────────────────────────────────────────────────────

def _parse_args() -> dict:
    """Minimal argument parser — no stdlib argparse to keep deps at zero."""
    kwargs: dict = {}
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--poll-interval" and i + 1 < len(args):
            kwargs["poll_interval"] = int(args[i + 1])
            i += 2
        elif args[i] == "--session-dir" and i + 1 < len(args):
            kwargs["session_dir"] = args[i + 1]
            i += 2
        elif args[i] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            i += 1
    return kwargs


def main() -> None:
    kwargs = _parse_args()
    daemon = FutureNotesDaemon(**kwargs)

    # Graceful shutdown on SIGTERM / SIGINT
    signal.signal(signal.SIGTERM, lambda _sig, _frame: daemon.stop())
    signal.signal(signal.SIGINT, lambda _sig, _frame: daemon.stop())

    print(f"[FutureNotes] Watching {daemon.session_dir} …")
    print(f"[FutureNotes] Writing to {daemon.notes_md}  +  {daemon.notes_db}")
    print(f"[FutureNotes] Poll interval: {daemon.poll_interval}s")

    daemon.run()
    print("[FutureNotes] Daemon stopped.")


if __name__ == "__main__":
    main()
