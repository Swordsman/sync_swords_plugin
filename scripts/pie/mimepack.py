#!/usr/bin/env python3
"""
mimepack - Context-Optimized File Packaging for LLM Workflows

Four primitives in one tool:

  pack    — Bundle files into LLM-transparent MIME containers with
            session-based deduplication and multiple output formats.
  unpack  — Extract files from any mimepack-produced container.
  view    — Display file regions with custom-base line numbering,
            slicing, and context windows. The AI's `less`.
  scan    — Extract embedded base64 blocks from binary data.

Philosophy: Visibility over compression. Cognitive transparency is worth
more than byte efficiency when the consumer is an LLM.
"""

import sys
import os
import sqlite3
import hashlib
import mimetypes
import re
import json
import base64
import zlib
import time
import argparse
import pathlib
from typing import List, Dict, Optional, Tuple, Generator, Set
from dataclasses import dataclass
from email.message import EmailMessage
from email import policy
from email.parser import BytesParser
from contextlib import contextmanager

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

VERSION = "0.3.0"

# ============================================================================
# CUSTOM BASE ENCODING
# ============================================================================

# Predefined alphabets. Any string works as a custom alphabet — the base
# is just len(alphabet). These are curated for LLM readability: no ambiguous
# glyphs, no characters that commonly break tokenizers.

ALPHABETS = {
    'bin':    '01',
    'oct':    '01234567',
    'dec':    '0123456789',
    'hex':    '0123456789abcdef',
    'HEX':    '0123456789ABCDEF',
    'b32':    'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567',
    'b36':    '0123456789abcdefghijklmnopqrstuvwxyz',
    'b58':    '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz',
    'b62':    '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    'z85':    '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#',
}


def resolve_alphabet(spec: str) -> str:
    """Resolve an alphabet specifier to a character string.

    Accepts:
      - A named preset: 'hex', 'b62', 'dec', etc.
      - A raw alphabet string (len >= 2): used directly as the character set.

    Returns the alphabet string. Raises ValueError on bad input.
    """
    if spec in ALPHABETS:
        return ALPHABETS[spec]
    if len(spec) >= 2:
        if len(set(spec)) != len(spec):
            raise ValueError(f"Alphabet has duplicate characters: {spec!r}")
        return spec
    raise ValueError(
        f"Unknown alphabet {spec!r}. Use a preset ({', '.join(ALPHABETS)}) "
        f"or provide a custom string of 2+ unique characters."
    )


def encode_num(num: int, alphabet: str) -> str:
    """Encode a non-negative integer in the given positional base."""
    if num < 0:
        raise ValueError("Cannot encode negative numbers")
    base = len(alphabet)
    if num == 0:
        return alphabet[0]
    digits = []
    while num:
        num, rem = divmod(num, base)
        digits.append(alphabet[rem])
    return ''.join(reversed(digits))


# ============================================================================
# DATABASE SCHEMA & SESSION MANAGEMENT
# ============================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_hash TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    lines INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    last_seen INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created REAL NOT NULL,
    last_used REAL NOT NULL,
    mode TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_path ON files(file_path);
"""


def _db_path(session_id: Optional[str]) -> Optional[str]:
    """Resolve database path for a session. None = stateless."""
    if not session_id:
        return None
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
    return os.path.join(runtime_dir, f'mimepack-{session_id}.db')


@contextmanager
def session_db(session_id: Optional[str]):
    """Context manager yielding a DB connection (or None for stateless).

    Commits on clean exit, rolls back on exception, always closes.
    """
    if not session_id:
        yield None
        return

    db_path = _db_path(session_id)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection):
    """Ensure tables exist (idempotent)."""
    conn.executescript(SCHEMA)


def init_session(session_id: str, mode: str = 'guardian'):
    """Create and initialize a session database."""
    with session_db(session_id) as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?)",
            (session_id, time.time(), time.time(), mode)
        )


def cleanup_session(session_id: str):
    """Remove a session database from disk."""
    db_path = _db_path(session_id)
    if db_path and os.path.exists(db_path):
        os.remove(db_path)


# ============================================================================
# HASHING & FILE I/O
# ============================================================================

def hash_content(content: bytes) -> str:
    """SHA-256 hash of content. Internal only — never exposed to AI consumers."""
    return hashlib.sha256(content).hexdigest()


def count_lines(content: bytes) -> int:
    """Count lines in text content. Returns 0 for binary (strict UTF-8 check)."""
    try:
        text = content.decode('utf-8', errors='strict')
        return text.count('\n') + 1
    except UnicodeDecodeError:
        return 0


def is_text(content: bytes) -> bool:
    """Heuristic: is this content likely text?"""
    return count_lines(content) > 0


def find_files(paths: List[str],
               exclude_patterns: Optional[List[str]] = None
               ) -> Generator[str, None, None]:
    """Yield resolved file paths, pruning excluded dirs/files by exact name."""
    excludes = set(exclude_patterns or [
        '.git', '__pycache__', '.env', 'node_modules',
        '.venv', '.mypy_cache', '.DS_Store',
    ])

    for path in paths:
        p = pathlib.Path(path)
        if p.is_file():
            if p.name not in excludes:
                yield str(p.resolve())
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in excludes]
                for fname in files:
                    if fname in excludes:
                        continue
                    yield str((pathlib.Path(root) / fname).resolve())


def read_file(file_path: str) -> Optional[bytes]:
    """Read file contents. Returns None on failure (logged to stderr)."""
    try:
        with open(file_path, 'rb') as f:
            return f.read()
    except (IOError, OSError) as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
        return None


def read_input(file_path: Optional[str] = None) -> bytes:
    """Read from a file path or stdin."""
    if file_path:
        data = read_file(file_path)
        if data is None:
            sys.exit(1)
        return data
    return sys.stdin.buffer.read()


# ============================================================================
# IMAGE HANDLING (optional Pillow dependency)
# ============================================================================

def encode_image(data: bytes, fmt: str = 'PNG') -> bytes:
    """Encode image data to base64. Uses Pillow if available for
    format conversion, otherwise passes through raw base64."""
    if not HAS_PILLOW:
        return base64.b64encode(data)
    import io
    try:
        img = Image.open(io.BytesIO(data))
        out = io.BytesIO()
        img.save(out, format=fmt)
        return base64.b64encode(out.getvalue())
    except Exception:
        return base64.b64encode(data)


def decode_image(b64_data: bytes) -> Optional[bytes]:
    """Decode base64 image data. Returns raw bytes.
    Pillow validation if available."""
    raw = base64.b64decode(b64_data)
    if HAS_PILLOW:
        import io
        try:
            Image.open(io.BytesIO(raw)).verify()
        except Exception:
            return None
    return raw


# ============================================================================
# VIEW — LLM-optimized file viewer
# ============================================================================

def get_slice(lines: list, *,
              start: Optional[int] = None,
              stop: Optional[int] = None,
              count: Optional[int] = None,
              target: Optional[int] = None,
              context: Optional[int] = None
              ) -> Tuple[list, int]:
    """Extract a slice of lines with flexible addressing.

    Three modes (checked in priority order):
      1. target + context: lines [target-context, target+context]
      2. start + stop/count: explicit range
      3. None: return all lines

    Returns (sliced_lines, 1-based_offset_of_first_line).
    """
    total = len(lines)

    if target is not None:
        ctx = context or 0
        # Convert to 0-based
        s = max(0, target - ctx - 1)
        e = min(total, target + ctx)
        return lines[s:e], s + 1

    if start is not None:
        s = max(0, start - 1)  # 1-based to 0-based
        if stop is not None:
            e = min(total, stop)
        elif count is not None:
            e = min(total, s + count)
        else:
            e = total
        return lines[s:e], s + 1

    return lines, 1


def generate_view(content: bytes, *,
                  alphabet: str = '0123456789',
                  start: Optional[int] = None,
                  stop: Optional[int] = None,
                  count: Optional[int] = None,
                  target: Optional[int] = None,
                  context: Optional[int] = None) -> bytes:
    """Generate a line-numbered view of text content.

    The line number column uses the specified alphabet as its positional base.
    An AI can request any encoding that fits its tokenizer.

    Returns UTF-8 encoded output suitable for stdout or context injection.
    """
    text = content.decode('utf-8', errors='replace')
    all_lines = text.splitlines(True)

    view_lines, offset = get_slice(
        all_lines, start=start, stop=stop,
        count=count, target=target, context=context
    )

    if not view_lines:
        return b""

    max_num = offset + len(view_lines) - 1
    pad = len(encode_num(max_num, alphabet))
    zero = alphabet[0]

    out = []
    for i, line in enumerate(view_lines, offset):
        num_str = encode_num(i, alphabet).rjust(pad, zero)
        out.append(f"{num_str}| {line}")

    return "".join(out).encode('utf-8')


# ============================================================================
# SCAN — base64 block extraction
# ============================================================================

# Matches base64 blocks of at least 40 chars (10 quartets).
_B64_PATTERN = re.compile(
    rb'(?:[A-Za-z0-9+/]{4}){10,}'
    rb'(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?'
)


def scan_b64_blocks(data: bytes,
                    printable_threshold: float = 0.9
                    ) -> List[Dict]:
    """Scan binary data for embedded base64 blocks.

    Returns a list of dicts with keys:
      - offset: byte offset of the match in the input
      - length: length of the base64 string
      - decoded: the decoded text (only if it passes the printability check)
      - raw_b64: the raw base64 string

    Only includes blocks whose decoded content is >= printable_threshold
    fraction printable characters.
    """
    results = []
    for match in _B64_PATTERN.finditer(data):
        b64_bytes = match.group(0)
        try:
            raw = base64.b64decode(b64_bytes)
            decoded = raw.decode('utf-8')
        except Exception:
            continue

        if not decoded:
            continue

        printable_ratio = sum(
            c.isprintable() or c in '\n\r\t' for c in decoded
        ) / len(decoded)

        if printable_ratio >= printable_threshold:
            results.append({
                'offset': match.start(),
                'length': len(b64_bytes),
                'decoded': decoded,
                'raw_b64': b64_bytes.decode('ascii'),
            })

    return results


# ============================================================================
# MIME VALIDATION & REPAIR
# ============================================================================

def validate_mime(data: bytes) -> Tuple[List, bytes]:
    """Parse MIME data, return (defects, repaired_bytes).

    If the parser found defects, the repaired version is the
    re-serialized message. Otherwise returns original data unchanged.
    """
    from email import message_from_bytes
    msg = message_from_bytes(data, policy=policy.default)
    defects = list(msg.defects)
    repaired = msg.as_bytes() if defects else data
    return defects, repaired


# ============================================================================
# PACK RESULT & FORMATTERS
# ============================================================================

@dataclass
class PackResult:
    file_path: str
    content: bytes
    file_hash: str
    size: int
    lines: int
    mime_type: Tuple[str, str]
    is_new: bool
    last_seen: Optional[int] = None


class BaseFormatter:
    """Base class for output formatters."""

    def __init__(self, session_id: Optional[str], manifest_mode: str):
        self.session_id = session_id
        self.manifest_mode = manifest_mode
        self.packed: List[PackResult] = []
        self.skipped: List[PackResult] = []

    def add(self, result: PackResult, skipped: bool = False):
        (self.skipped if skipped else self.packed).append(result)

    def output(self) -> bytes:
        raise NotImplementedError


class MIMEFormatter(BaseFormatter):
    """RFC 2822 MIME multipart output with optional checksums."""

    def __init__(self, session_id, manifest_mode, checksum=None):
        super().__init__(session_id, manifest_mode)
        self.checksum = checksum

    def output(self) -> bytes:
        msg = EmailMessage()
        msg.make_mixed()

        if self.skipped and self.manifest_mode == 'guardian':
            manifest = self._manifest()
            msg.add_attachment(
                manifest.encode('utf-8'),
                maintype='application', subtype='json',
                filename='mimepack-manifest.json'
            )

        for result in self.packed:
            main, sub = result.mime_type
            msg.add_attachment(
                result.content,
                maintype=main, subtype=sub,
                filename=os.path.basename(result.file_path)
            )
            part = msg.get_payload()[-1]
            part.add_header('X-File-Hash', result.file_hash)
            part.add_header('X-Original-Path', result.file_path)

            if self.checksum == 'md5':
                part.add_header('Content-MD5',
                                hashlib.md5(result.content).hexdigest())
            elif self.checksum == 'crc32':
                part.add_header('X-Checksum-CRC32',
                                format(zlib.crc32(result.content) & 0xFFFFFFFF, '08x'))

        return msg.as_bytes()

    def _manifest(self) -> str:
        return json.dumps({
            'skipped': [
                {'path': r.file_path, 'hash': r.file_hash,
                 'last_seen': r.last_seen}
                for r in self.skipped
            ]
        }, indent=2)


class CompactFormatter(BaseFormatter):
    """Compact markdown-fenced output for direct LLM context injection."""

    def output(self) -> bytes:
        lines = [
            "```mimepack",
            f"version: {VERSION}",
            f"session: {self.session_id or 'stateless'}",
            f"mode: {self.manifest_mode}",
            f"packed: {len(self.packed)}",
            f"skipped: {len(self.skipped)}",
            "---",
        ]

        if self.skipped and self.manifest_mode == 'guardian':
            for r in self.skipped:
                lines.append(f"SKIPPED: {r.file_path}")
                lines.append(f"  hash: {r.file_hash}")
                lines.append(f"  last_seen: turn {r.last_seen}")

        for result in self.packed:
            lines.append("")
            lines.append(f"=== FILE: {result.file_path} ===")
            lines.append(f"hash: {result.file_hash}")
            lines.append(f"size: {result.size} bytes")
            lines.append(f"lines: {result.lines}")
            lines.append("---")

            if result.lines > 0:
                text = result.content.decode('utf-8', errors='replace')
                content_lines = text.splitlines()
                pad = len(str(len(content_lines)))
                for i, line in enumerate(content_lines, 1):
                    lines.append(f"{str(i).rjust(pad)}| {line}")
            else:
                lines.append(f"[Binary content: {result.size} bytes]")

            lines.append("=== END FILE ===")

        lines.append("```")
        return '\n'.join(lines).encode('utf-8')


class JSONFormatter(BaseFormatter):
    """JSON Lines output for programmatic consumption."""

    def output(self) -> bytes:
        records = []

        records.append({
            'type': 'meta',
            'version': VERSION,
            'session': self.session_id,
            'mode': self.manifest_mode,
            'summary': {
                'packed': len(self.packed),
                'skipped': len(self.skipped),
            }
        })

        if self.manifest_mode == 'guardian':
            for r in self.skipped:
                records.append({
                    'type': 'skipped',
                    'path': r.file_path,
                    'hash': r.file_hash,
                    'last_seen': r.last_seen,
                })

        for result in self.packed:
            record = {
                'type': 'file',
                'path': result.file_path,
                'hash': result.file_hash,
                'size': result.size,
                'lines': result.lines,
                'mime': '/'.join(result.mime_type),
                'is_new': result.is_new,
            }
            if result.lines > 0:
                record['content'] = result.content.decode('utf-8', errors='replace')
            else:
                record['content_b64'] = base64.b64encode(result.content).decode('ascii')
            records.append(record)

        return '\n'.join(json.dumps(r) for r in records).encode('utf-8')


FORMATTERS = {
    'mime': MIMEFormatter,
    'compact': CompactFormatter,
    'json': JSONFormatter,
}

# ============================================================================
# PACKING LOGIC
# ============================================================================

def _is_seen(conn: Optional[sqlite3.Connection], file_hash: str) -> Optional[Dict]:
    """Check if file hash exists in the session DB."""
    if conn is None:
        return None
    cursor = conn.execute(
        "SELECT file_path, timestamp, last_seen FROM files WHERE file_hash = ?",
        (file_hash,)
    )
    row = cursor.fetchone()
    if row:
        return {'file_path': row[0], 'timestamp': row[1], 'last_seen': row[2]}
    return None


def _record(conn: Optional[sqlite3.Connection], file_path: str,
            file_hash: str, file_size: int, lines: int, turn: int):
    """Record a file in the session DB."""
    if conn is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO files "
        "(file_hash, file_path, file_size, lines, timestamp, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (file_hash, file_path, file_size, lines, time.time(), turn)
    )


def _should_skip(conn: Optional[sqlite3.Connection], file_hash: str,
                 known_hashes: Optional[Set[str]], force: bool) -> bool:
    """Determine if a file should be skipped."""
    if force:
        return False
    if known_hashes and file_hash in known_hashes:
        return True
    if _is_seen(conn, file_hash):
        return True
    return False


def pack_files(paths: List[str],
               session_id: Optional[str] = None,
               format_type: str = 'compact',
               manifest_mode: str = 'guardian',
               known_hashes: Optional[Set[str]] = None,
               checksum: Optional[str] = None,
               force: bool = False,
               turn: int = 0) -> bytes:
    """Pack files into the chosen output format.

    Primary entry point for both CLI and programmatic use.
    """
    formatter_cls = FORMATTERS.get(format_type)
    if formatter_cls is None:
        raise ValueError(f"Unknown format: {format_type}")

    if format_type == 'mime':
        formatter = formatter_cls(session_id, manifest_mode, checksum=checksum)
    else:
        formatter = formatter_cls(session_id, manifest_mode)

    with session_db(session_id) as conn:
        if conn is not None:
            _ensure_schema(conn)
            conn.execute(
                "UPDATE sessions SET last_used = ? WHERE session_id = ?",
                (time.time(), session_id)
            )

        for file_path in find_files(paths):
            content = read_file(file_path)
            if content is None:
                continue

            file_hash = hash_content(content)
            file_size = len(content)
            lines = count_lines(content)

            mime_str = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
            main, sub = mime_str.split('/', 1)

            skip = _should_skip(conn, file_hash, known_hashes, force)

            result = PackResult(
                file_path=file_path,
                content=content,
                file_hash=file_hash,
                size=file_size,
                lines=lines,
                mime_type=(main, sub),
                is_new=not skip,
            )

            if skip:
                seen = _is_seen(conn, file_hash)
                if seen:
                    result.last_seen = int(seen.get('last_seen', 0))
                formatter.add(result, skipped=True)
            else:
                formatter.add(result, skipped=False)
                _record(conn, file_path, file_hash, file_size, lines, turn)

    return formatter.output()


# ============================================================================
# UNPACKING LOGIC
# ============================================================================

def _safe_unpack_path(filename: str, output_dir: str) -> str:
    """Resolve an unpack target path, rejecting traversal attempts."""
    cleaned = pathlib.PurePosixPath(filename)
    parts = [p for p in cleaned.parts if p not in ('/', '\\', '..')]
    if not parts:
        raise ValueError(f"Empty or invalid filename: {filename}")

    target = pathlib.Path(output_dir).resolve() / pathlib.Path(*parts)
    target = target.resolve()

    if not str(target).startswith(str(pathlib.Path(output_dir).resolve())):
        raise ValueError(f"Path traversal blocked: {filename}")

    return str(target)


def unpack_mime(data: bytes, verify: bool = False) -> List[Tuple[str, bytes, Dict]]:
    """Unpack MIME format."""
    msg = BytesParser(policy=policy.default).parsebytes(data)
    files = []

    for part in msg.walk():
        if part.is_multipart():
            continue

        filename = part.get_filename()
        if not filename or filename == 'mimepack-manifest.json':
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        metadata = {
            'hash': part.get('X-File-Hash'),
            'path': part.get('X-Original-Path'),
            'size': len(payload),
            'md5': part.get('Content-MD5'),
            'crc32': part.get('X-Checksum-CRC32'),
        }

        if verify:
            if metadata['hash']:
                computed = hash_content(payload)
                if computed != metadata['hash']:
                    print(f"Warning: SHA-256 mismatch for {filename}",
                          file=sys.stderr)
            if metadata['md5']:
                if hashlib.md5(payload).hexdigest() != metadata['md5']:
                    print(f"Warning: MD5 mismatch for {filename}",
                          file=sys.stderr)
            if metadata['crc32']:
                computed_crc = format(zlib.crc32(payload) & 0xFFFFFFFF, '08x')
                if computed_crc != metadata['crc32']:
                    print(f"Warning: CRC32 mismatch for {filename}",
                          file=sys.stderr)

        files.append((filename, payload, metadata))

    return files


def unpack_compact(data: bytes) -> List[Tuple[str, bytes, Dict]]:
    """Unpack compact format."""
    text = data.decode('utf-8', errors='replace')
    files = []

    pattern = re.compile(r'=== FILE: (.+?) ===(.*?)=== END FILE ===', re.DOTALL)

    for match in pattern.finditer(text):
        filename = match.group(1).strip()
        body = match.group(2)

        content_lines = []
        in_content = False

        for line in body.split('\n'):
            if line.strip() == '---':
                in_content = True
                continue
            if in_content:
                # Strip line-number prefix: anything before first '| '
                if '| ' in line:
                    content_lines.append(line.split('| ', 1)[1])
                elif '|' in line:
                    content_lines.append(line.split('|', 1)[1])
                else:
                    content_lines.append(line)

        files.append((filename, '\n'.join(content_lines).encode('utf-8'),
                       {'path': filename}))

    return files


def unpack_json(data: bytes) -> List[Tuple[str, bytes, Dict]]:
    """Unpack JSON Lines format."""
    files = []

    for line in data.decode('utf-8').strip().split('\n'):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get('type') != 'file':
            continue

        if 'content_b64' in record:
            content = base64.b64decode(record['content_b64'])
        else:
            content = record.get('content', '').encode('utf-8')

        metadata = {
            'hash': record.get('hash'),
            'path': record.get('path'),
            'size': record.get('size'),
        }
        files.append((record.get('path', 'unknown'), content, metadata))

    return files


def detect_and_unpack(data: bytes,
                      verify: bool = False) -> List[Tuple[str, bytes, Dict]]:
    """Auto-detect format and unpack."""
    if data.startswith(b'MIME-Version:') or b'Content-Type:' in data[:1024]:
        return unpack_mime(data, verify)
    if data.startswith(b'```mimepack'):
        return unpack_compact(data)
    if data.startswith(b'{"type":'):
        return unpack_json(data)
    try:
        return unpack_mime(data, verify)
    except Exception:
        print("Error: Could not detect format", file=sys.stderr)
        sys.exit(1)


# ============================================================================
# SESSION STATUS
# ============================================================================

def show_session_status(session_id: str):
    """Display session statistics."""
    db_path = _db_path(session_id)
    if not db_path or not os.path.exists(db_path):
        print(f"Session {session_id} not found")
        return

    with session_db(session_id) as conn:
        _ensure_schema(conn)

        row = conn.execute(
            "SELECT created, last_used, mode FROM sessions"
        ).fetchone()
        if row:
            print(f"Session: {session_id}")
            print(f"Mode: {row[2]}")
            print(f"Created: {time.ctime(row[0])}")
            print(f"Last used: {time.ctime(row[1])}")

        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        total_size = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM files"
        ).fetchone()[0]
        print(f"Files tracked: {file_count}")
        print(f"Total size: {total_size:,} bytes")

        print("\nRecent files:")
        for row in conn.execute(
            "SELECT file_path, file_size, last_seen "
            "FROM files ORDER BY last_seen DESC LIMIT 10"
        ):
            print(f"  {row[0]} ({row[1]} bytes, turn {row[2]})")


# ============================================================================
# CLI
# ============================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='mimepack',
        description='Context-Optimized File Packaging for LLM Workflows',
    )
    parser.add_argument('--version', action='version',
                        version=f'mimepack {VERSION}')

    sub = parser.add_subparsers(dest='command', help='Command to run')

    # --- pack ---
    p_pack = sub.add_parser('pack', help='Pack files into a container')
    p_pack.add_argument('paths', nargs='+', help='Files/directories to pack')
    p_pack.add_argument('--session', help='Session ID for dedup tracking')
    p_pack.add_argument('--format', choices=['mime', 'compact', 'json'],
                        default='compact',
                        help='Output format (default: compact)')
    p_pack.add_argument('--manifest', choices=['guardian', 'explicit', 'none'],
                        default='guardian',
                        help='Manifest mode (default: guardian)')
    p_pack.add_argument('--known',
                        help='Comma-separated known hashes to skip')
    p_pack.add_argument('--checksum', choices=['md5', 'crc32'],
                        help='Add checksums to MIME output')
    p_pack.add_argument('--force', action='store_true',
                        help='Force pack all files (ignore dedup)')
    p_pack.add_argument('--turn', type=int, default=0,
                        help='Turn number for dedup tracking')

    # --- unpack ---
    p_unpack = sub.add_parser('unpack',
                              help='Unpack a container from stdin')
    p_unpack.add_argument('--verify', action='store_true',
                          help='Verify checksums')
    p_unpack.add_argument('--output-dir', default='.',
                          help='Output directory (default: cwd)')

    # --- view ---
    p_view = sub.add_parser(
        'view', help='Display file with custom-base line numbers')
    p_view.add_argument('file', nargs='?',
                        help='File to view (default: stdin)')
    p_view.add_argument('--alphabet', default='dec',
                        help='Line number base: preset name '
                             '(dec, hex, b62, ...) or custom alphabet string')
    p_view.add_argument('--start', type=int, help='Start line (1-based)')
    p_view.add_argument('--stop', type=int, help='Stop line (inclusive)')
    p_view.add_argument('--count', type=int,
                        help='Number of lines from start')
    p_view.add_argument('--target', type=int,
                        help='Center view on this line')
    p_view.add_argument('--context', type=int,
                        help='Lines of context around target')

    # --- scan ---
    p_scan = sub.add_parser('scan',
                            help='Scan for embedded base64 blocks')
    p_scan.add_argument('file', nargs='?',
                        help='File to scan (default: stdin)')
    p_scan.add_argument('--threshold', type=float, default=0.9,
                        help='Printability threshold (default: 0.9)')
    p_scan.add_argument('--json', action='store_true',
                        dest='json_output', help='Output as JSON')

    # --- session ---
    p_session = sub.add_parser('session', help='Manage sessions')
    p_session.add_argument('session_id', help='Session ID')
    p_session.add_argument('--init', action='store_true',
                           help='Initialize session')
    p_session.add_argument('--cleanup', action='store_true',
                           help='Remove session')
    p_session.add_argument('--status', action='store_true',
                           help='Show session status')

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # --- pack ---
    if args.command == 'pack':
        known_hashes = None
        if args.known:
            known_hashes = set(args.known.split(','))

        output = pack_files(
            paths=args.paths,
            session_id=args.session,
            format_type=args.format,
            manifest_mode=args.manifest,
            known_hashes=known_hashes,
            checksum=args.checksum,
            force=args.force,
            turn=args.turn,
        )
        sys.stdout.buffer.write(output)

    # --- unpack ---
    elif args.command == 'unpack':
        data = sys.stdin.buffer.read()
        files = detect_and_unpack(data, args.verify)

        output_dir = os.path.abspath(args.output_dir)
        os.makedirs(output_dir, exist_ok=True)

        for filename, content, metadata in files:
            try:
                target_path = _safe_unpack_path(filename, output_dir)
            except ValueError as e:
                print(f"Warning: {e}", file=sys.stderr)
                continue

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, 'wb') as f:
                f.write(content)
            print(f"Unpacked: {target_path} ({len(content)} bytes)")

    # --- view ---
    elif args.command == 'view':
        content = read_input(args.file)
        alphabet = resolve_alphabet(args.alphabet)

        output = generate_view(
            content, alphabet=alphabet,
            start=args.start, stop=args.stop,
            count=args.count, target=args.target,
            context=args.context,
        )
        sys.stdout.buffer.write(output)

    # --- scan ---
    elif args.command == 'scan':
        data = read_input(args.file)
        results = scan_b64_blocks(data, args.threshold)

        if args.json_output:
            sys.stdout.write(json.dumps(results, indent=2))
            sys.stdout.write('\n')
        else:
            if not results:
                print("No base64 blocks found.")
            for r in results:
                print(f"--- offset {r['offset']}, {r['length']} chars ---")
                print(r['decoded'])
                print()

    # --- session ---
    elif args.command == 'session':
        if args.init:
            init_session(args.session_id)
            print(f"Session {args.session_id} initialized")
        elif args.cleanup:
            cleanup_session(args.session_id)
            print(f"Session {args.session_id} cleaned up")
        elif args.status:
            show_session_status(args.session_id)
        else:
            print("Specify --init, --cleanup, or --status")


if __name__ == '__main__':
    main()
