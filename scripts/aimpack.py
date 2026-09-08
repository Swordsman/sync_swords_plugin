#!/usr/bin/env python3
"""aimpack - AI MimePack: LLM-ergonomic MIME containers with linear edit history.

munpack-compatible. Extension-ready. S-expression instruction support.
Spec: https://github.com/swordsman/aimpack
"""

import argparse, sys, os, re, uuid, json, hashlib, zlib, difflib, importlib.util, secrets, base64
from pathlib import Path
from datetime import datetime, timezone
from email.parser import Parser as MIMEParser

__version__ = "1.1.0"
SPEC_URL = "https://github.com/swordsman/aimpack"
CONFIG_DIR = Path.home() / ".aimpack"
EXTENSIONS_DIR = CONFIG_DIR / "extensions"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ── Config ────────────────────────────────────

def default_config():
    return {
        "resolver": {
            "chain": ["local", "github", "web", "ask"],
            "local_paths": [str(EXTENSIONS_DIR)],
            "github_repos": ["swordsman/aimpack"],
            "auto_install": False,
        }
    }

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return default_config()

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)

# ── S-Expression Parser ──────────────────────

def tokenize_sexpr(s):
    tokens, i = [], 0
    while i < len(s):
        c = s[i]
        if c in "()":
            tokens.append(c); i += 1
        elif c == '"':
            j = i + 1
            while j < len(s) and s[j] != '"':
                if s[j] == '\\': j += 1
                j += 1
            tokens.append(s[i:j+1]); i = j + 1
        elif c == ';':
            while i < len(s) and s[i] != '\n': i += 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < len(s) and s[j] not in '() \t\n\r";': j += 1
            tokens.append(s[i:j]); i = j
    return tokens

def _parse_tokens(tokens, idx):
    results = []
    while idx < len(tokens):
        t = tokens[idx]
        if t == '(':
            sub, idx = _parse_tokens(tokens, idx + 1)
            results.append(sub)
        elif t == ')':
            return results, idx + 1
        else:
            if t.startswith('"') and t.endswith('"'):
                results.append(t[1:-1].replace('\\"', '"').replace('\\\\', '\\'))
            elif t.startswith(':'):
                results.append(t)
            else:
                try: results.append(int(t))
                except ValueError:
                    try: results.append(float(t))
                    except ValueError: results.append(t)
            idx += 1
    return results, idx

def parse_sexpr(s):
    tokens = tokenize_sexpr(s.strip())
    result, _ = _parse_tokens(tokens, 0)
    return result[0] if len(result) == 1 else result

def sexpr_to_string(obj, indent=0):
    if isinstance(obj, list):
        if not obj: return "()"
        if len(obj) <= 3 and all(not isinstance(x, list) for x in obj):
            inner = " ".join(sexpr_to_string(x) for x in obj)
            return f"({inner})"
        pad = "  " * (indent + 1)
        head = sexpr_to_string(obj[0])
        chunks = []
        i = 1
        while i < len(obj):
            elem = obj[i]
            # Keep :keyword value pairs together on one line
            if isinstance(elem, str) and elem.startswith(':') and i + 1 < len(obj):
                nxt = obj[i + 1]
                if not isinstance(nxt, list):
                    chunks.append(f"\n{pad}{elem} {sexpr_to_string(nxt)}")
                    i += 2
                    continue
                else:
                    chunks.append(f"\n{pad}{elem} {sexpr_to_string(nxt, indent + 1)}")
                    i += 2
                    continue
            chunks.append(f"\n{pad}{sexpr_to_string(elem, indent + 1)}")
            i += 1
        return f"({head}{''.join(chunks)})"
    elif isinstance(obj, str):
        if obj.startswith(':') or re.match(r'^[a-zA-Z_][\w-]*$', obj):
            return obj
        return f'"{obj}"'
    else:
        return str(obj)

# ── Extension System ─────────────────────────

class ExtensionRegistry:
    def __init__(self):
        self._handlers = {}  # content_type -> module

    def load_dir(self, path):
        path = Path(path)
        if not path.is_dir(): return
        for f in path.glob("*.py"):
            try:
                mod = self._load_module(f)
                for ct in getattr(mod, 'CONTENT_TYPES', []):
                    self._handlers[ct] = mod
            except Exception as e:
                print(f"  ⚠ Failed to load extension {f.name}: {e}", file=sys.stderr)

    def _load_module(self, path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def get(self, content_type):
        return self._handlers.get(content_type)

    def list_handlers(self):
        return {ct: getattr(mod, '__file__', '?') for ct, mod in self._handlers.items()}

    def handlers(self):
        """Return {content_type: module} for all loaded handlers."""
        return dict(self._handlers)

    def resolve(self, content_type, config):
        chain = config.get("resolver", {}).get("chain", ["local"])
        for source in chain:
            if source == "local":
                for p in config.get("resolver", {}).get("local_paths", []):
                    self.load_dir(p)
                h = self.get(content_type)
                if h: return h
            elif source == "github":
                h = self._resolve_github(content_type, config)
                if h: return h
            elif source == "ask":
                print(f"  ? Unknown content type: {content_type}", file=sys.stderr)
                print(f"    No handler found in resolver chain.", file=sys.stderr)
        return None

    def _resolve_github(self, content_type, config):
        repos = config.get("resolver", {}).get("github_repos", [])
        for repo in repos:
            manifest_url = f"https://raw.githubusercontent.com/{repo}/main/extensions/manifest.json"
            try:
                import urllib.request
                resp = urllib.request.urlopen(manifest_url, timeout=5)
                manifest = json.loads(resp.read())
                for entry in manifest.get("extensions", []):
                    if content_type in entry.get("content_types", []):
                        if config.get("resolver", {}).get("auto_install"):
                            return self._install_from_url(entry["url"])
                        else:
                            print(f"  ℹ Handler available: {entry['name']} ({entry['url']})", file=sys.stderr)
                            print(f"    Run: aimpack ext install {entry['url']}", file=sys.stderr)
                            return None
            except Exception:
                continue
        return None

    def _install_from_url(self, url):
        ensure_dirs()
        import urllib.request
        filename = url.rsplit("/", 1)[-1]
        dest = EXTENSIONS_DIR / filename
        urllib.request.urlretrieve(url, dest)
        return self._load_module(dest)

_registry = ExtensionRegistry()

# ── Checksums ─────────────────────────────────

def compute_checksums(data, algorithms):
    result = {}
    for alg in algorithms:
        a = alg.lower()
        if a == "crc32":
            result["X-Aimpack-Checksum-CRC32"] = format(zlib.crc32(data) & 0xFFFFFFFF, "08x")
        elif a == "md5":
            result["X-Aimpack-Checksum-MD5"] = hashlib.md5(data).hexdigest()
        elif a == "sha256":
            result["X-Aimpack-Checksum-SHA256"] = hashlib.sha256(data).hexdigest()
    return result

# ── Container self-digest ─────────────────────
#
# A digest stored inside the thing it describes can never cover itself: writing
# it would change the bytes it just recorded, and no value would ever be stable.
# The canonical form is therefore the container text with its own checksum
# header line(s) deleted — defined textually, so verification never has to
# re-serialize the container and hope the bytes come back identical.

CONTAINER_CHECKSUM_PREFIX = "X-Aimpack-Container-Checksum-"
CONTAINER_CHECKSUM_RE = re.compile(
    r"^" + re.escape(CONTAINER_CHECKSUM_PREFIX) + r"[A-Za-z0-9]+:[^\n]*\n", re.M)

CONTAINER_DIGESTS = {"crc32", "md5", "sha256"}


def canonical_container_text(text):
    """Container text excluding its own checksum headers — the hashed form."""
    return CONTAINER_CHECKSUM_RE.sub("", text)


def compute_container_digest(text, alg="sha256"):
    data = canonical_container_text(text).encode("utf-8")
    if alg == "crc32":
        return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")
    return hashlib.new(alg, data).hexdigest()


def stamp_container_digest(text, algorithms):
    """Append checksum headers to a finished container.

    Appending after the fact — rather than adding to the header dict before
    building — is what keeps the digest honest: the value is computed over text
    that provably does not contain it, and deleting the header line restores
    exactly the bytes that were hashed.
    """
    algs = [a for a in algorithms if a in CONTAINER_DIGESTS]
    if not algs:
        return text
    end = text.find("\n\n")           # end of the global header block
    if end == -1:
        return text
    lines = "".join(f"\n{CONTAINER_CHECKSUM_PREFIX}{a.upper()}: "
                    f"{compute_container_digest(text, a)}" for a in algs)
    return text[:end] + lines + text[end:]


def verify_container_digest(text):
    """[(algorithm, expected, actual, ok)] for each recorded container digest."""
    results = []
    for m in CONTAINER_CHECKSUM_RE.finditer(text):
        line = m.group(0).strip()
        name, _, expected = line.partition(":")
        alg = name[len(CONTAINER_CHECKSUM_PREFIX):].lower()
        expected = expected.strip()
        if alg not in CONTAINER_DIGESTS:
            results.append((alg, expected, None, False))
            continue
        actual = compute_container_digest(text, alg)
        results.append((alg, expected, actual, actual == expected))
    return results


PART_CHECKSUM_PREFIX = "X-Aimpack-Checksum-"


def has_part_checksums(h):
    return any(k.startswith(PART_CHECKSUM_PREFIX) for k in h)


def recorded_digest_algs(gh):
    """Algorithms this container already records, so rewrites keep using them."""
    return [k[len(CONTAINER_CHECKSUM_PREFIX):].lower()
            for k in gh if k.startswith(CONTAINER_CHECKSUM_PREFIX)]


def without_digest_headers(gh):
    return {k: v for k, v in gh.items() if not k.startswith(CONTAINER_CHECKSUM_PREFIX)}


def write_container(path, gh, parts, boundary, algs):
    """Build, stamp and write a container in the one order that is self-consistent."""
    text = stamp_container_digest(build_message(gh, parts, boundary), algs)
    Path(path).write_text(text, encoding="utf-8")


def validate_checksums(data, headers):
    warnings = []
    for suffix, alg in [("CRC32", "crc32"), ("MD5", "md5"), ("SHA256", "sha256")]:
        key = f"X-Aimpack-Checksum-{suffix}"
        expected = headers.get(key)
        if expected:
            actual = compute_checksums(data, [alg])[key]
            if actual != expected:
                warnings.append(f"  ⚠ {suffix} mismatch: expected {expected}, got {actual}")
    return warnings

# ── Diffs ─────────────────────────────────────

NO_FINAL_NEWLINE = "X-Aimpack-Patch-No-Final-Newline"

def lacks_final_newline(text):
    return bool(text) and not text.endswith("\n")

def generate_diff(original, modified, filename):
    """Unified diff between two texts.

    Both sides are normalized to end with a newline so difflib cannot emit a
    truncated final line that would run into the next diff line. That
    normalization is lossy, so callers record the real state of the *modified*
    side in the NO_FINAL_NEWLINE part header and resolve_files undoes it.
    """
    orig = original.splitlines(keepends=True)
    mod = modified.splitlines(keepends=True)
    if orig and not orig[-1].endswith("\n"): orig[-1] += "\n"
    if mod and not mod[-1].endswith("\n"): mod[-1] += "\n"
    diff = list(difflib.unified_diff(orig, mod, f"a/{filename}", f"b/{filename}"))
    return "".join(diff) if diff else None

def apply_patch(original, patch_text):
    orig = original.splitlines(keepends=True)
    if orig and not orig[-1].endswith("\n"): orig[-1] += "\n"
    hunks, cur = [], None
    for line in patch_text.splitlines(keepends=True):
        if line.startswith("@@"):
            if cur: hunks.append(cur)
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            cur = {"start": int(m.group(1)), "lines": []} if m else None
        elif cur is None and line.startswith(("---", "+++")):
            # File header — only meaningful before the first hunk. Inside a hunk,
            # '---'/'+++' is an ordinary removal/addition of a content line that
            # itself begins with '--'/'++', and must not be skipped.
            continue
        elif cur is not None:
            cur["lines"].append(line)
    if cur: hunks.append(cur)

    result, idx = [], 0
    for hunk in hunks:
        target = hunk["start"] - 1
        while idx < target:
            if idx < len(orig): result.append(orig[idx])
            idx += 1
        for line in hunk["lines"]:
            if line.startswith("-"): idx += 1
            elif line.startswith("+"): result.append(line[1:])
            elif line.startswith(" "):
                if idx < len(orig): result.append(orig[idx])
                idx += 1
    while idx < len(orig):
        result.append(orig[idx]); idx += 1
    return "".join(result)

def invert_diff(diff_text):
    result = []
    in_hunk = False   # '---'/'+++' are headers only before the first @@ (see apply_patch)
    for line in diff_text.splitlines():
        if not in_hunk and line.startswith("--- "): result.append("+++ " + line[4:])
        elif not in_hunk and line.startswith("+++ "): result.append("--- " + line[4:])
        elif line.startswith("@@"):
            in_hunk = True
            m = re.match(r"@@ -(\S+) \+(\S+) @@(.*)", line)
            result.append(f"@@ -{m.group(2)} +{m.group(1)} @@{m.group(3)}" if m else line)
        elif in_hunk and line.startswith("-"): result.append("+" + line[1:])
        elif in_hunk and line.startswith("+"): result.append("-" + line[1:])
        else: result.append(line)
    return "\n".join(result)

# ── MIME Container (stdlib parser, minimal generator) ──

def parse_container(filepath):
    """Parse aimpack container using stdlib email.parser.
    Returns (global_headers_dict, [(part_headers_dict, body_str), ...])
    """
    text = Path(filepath).read_text(encoding="utf-8")
    msg = MIMEParser().parsestr(text)
    if not msg.is_multipart():
        raise ValueError("Not a multipart MIME message")

    global_headers = dict(msg.items())
    parts = []
    for part in msg.get_payload():  # direct children only
        headers = dict(part.items())
        body = part.get_payload(decode=False) or ""
        # Strip trailing newline added by email module
        if body.endswith("\n"): body = body[:-1]
        parts.append((headers, body))
    return global_headers, parts

def _make_boundary():
    return f"aimpack-{uuid.uuid4().hex[:16]}"

# ── Boundary selection ────────────────────────
#
# A boundary only has to be unambiguous against the content of its own
# container, which is fully known at pack time. The legacy 24-char uuid
# boundary bought global uniqueness the format never reads, and repeated it
# once per part — pure token overhead for an LLM consumer.

BOUNDARY_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
BOUNDARY_MAX_LEN = 70                 # RFC 2046 §5.1.1
BOUNDARY_ENTROPY = 4                  # random chars appended to the minimal safe length
# RFC 2046 bcharsnospace, minus space so the token stays one shell/regex word.
_BOUNDARY_RE = re.compile(r"^[A-Za-z0-9'()+_,./:=?-]{1,%d}$" % BOUNDARY_MAX_LEN)


def boundary_conflicts(boundary, texts):
    """Lines in `texts` that a MIME parser would read as a delimiter of `boundary`.

    Delimiters are line-initial, so only a line starting with '--<boundary>'
    can collide — and it collides on *prefix*, not equality: boundary "ab"
    is broken by a line reading '--abc'. Diff bodies routinely start lines
    with '--' ('--- a/file', or a removed line that itself began with '-'),
    which is the main reason this check exists.

    `texts` is an iterable of (label, text). Returns [(label, lineno, line)].
    """
    needle = "--" + boundary
    hits = []
    for label, text in texts:
        for n, line in enumerate(text.splitlines(), 1):
            if line.startswith(needle):
                hits.append((label, n, line))
    return hits


def _delimiter_tails(texts):
    """Every string following a line-initial '--'.

    A boundary is safe iff it is not a prefix of any of these.
    """
    tails = set()
    for _, text in texts:
        for line in text.splitlines():
            if line.startswith("--"):
                tails.add(line[2:])
    return tails


def _random_token(n):
    return "".join(secrets.choice(BOUNDARY_ALPHABET) for _ in range(n))


def minimal_boundary(texts, entropy=BOUNDARY_ENTROPY, attempts=256):
    """Shortest collision-free boundary for `texts`, plus `entropy` random chars.

    Grows the length only as far as the content forces it: with no '--' lines
    present (the common case) the minimal safe length is 1, so the result is
    1 + entropy characters. The random tail keeps two packs of the same tree
    from sharing a boundary, which is what makes container splicing safe.
    """
    tails = _delimiter_tails(texts)
    for base in range(1, BOUNDARY_MAX_LEN - entropy + 1):
        for _ in range(attempts):
            cand = _random_token(base + entropy)
            if not any(t.startswith(cand) for t in tails):
                return cand
    raise ValueError("no collision-free boundary fits in %d chars" % BOUNDARY_MAX_LEN)


def check_explicit_boundary(boundary, texts):
    """Validate a user-supplied --boundary, exiting with a diagnostic if unusable."""
    if not _BOUNDARY_RE.match(boundary):
        print(f"Error: invalid boundary {boundary!r}: must be 1-{BOUNDARY_MAX_LEN} chars "
              f"from A-Za-z0-9'()+_,-./:=?", file=sys.stderr)
        sys.exit(1)
    hits = boundary_conflicts(boundary, texts)
    if hits:
        print(f"Error: boundary {boundary!r} collides with content in "
              f"{len({h[0] for h in hits})} file(s):", file=sys.stderr)
        for label, n, line in hits[:5]:
            print(f"  {label}:{n}: {line[:72]}", file=sys.stderr)
        if len(hits) > 5:
            print(f"  ... and {len(hits) - 5} more", file=sys.stderr)
        print("Choose a different boundary, or omit --boundary to derive a safe one.",
              file=sys.stderr)
        sys.exit(1)
    return boundary


def ensure_boundary(boundary, texts, entropy=BOUNDARY_ENTROPY):
    """Keep `boundary` if it is still unambiguous against `texts`, else mint a new one.

    Rewriting commands (compact, squash) materialize file content that was
    never scanned when the container was packed, so the inherited boundary
    has to be re-checked. Returns (boundary, replaced).
    """
    if not boundary_conflicts(boundary, texts):
        return boundary, False
    return minimal_boundary(texts, entropy), True


def _scan_targets(parts):
    """Label built part strings for collision scanning. Headers are 'Key: value'
    and so can never begin with '--'; scanning whole parts is safe."""
    return [(f"part {i + 1}", p) for i, p in enumerate(parts)]


def _make_id():
    return str(uuid.uuid4())

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _format_headers(headers):
    return "\n".join(f"{k}: {v}" for k, v in headers.items())

def build_part(headers, body):
    return _format_headers(headers) + "\n\n" + body

def build_message(global_headers, parts, boundary):
    out = _format_headers(global_headers) + "\n\n"
    for part in parts:
        out += f"--{boundary}\n{part}\n\n"
    out += f"--{boundary}--\n"
    return out

def get_boundary(global_headers):
    ct = global_headers.get("Content-Type", "")
    m = re.search(r'boundary="?([^";\s]+)"?', ct)
    return m.group(1) if m else _make_boundary()

# ── Part classification ───────────────────────

def is_file_part(h):
    return "attachment" in h.get("Content-Disposition", "") and \
           "x-diff" not in h.get("Content-Type", "") and \
           "x-aimpack" not in h.get("Content-Type", "")

def is_diff_part(h):
    return "x-diff" in h.get("Content-Type", "")

def is_forward_diff(h):
    return is_diff_part(h) and h.get("X-Aimpack-Patch-Direction", "forward") == "forward"

def is_inverse_diff(h):
    return is_diff_part(h) and h.get("X-Aimpack-Patch-Direction", "") == "inverse"

def is_meta_part(h):
    return "x-aimpack-meta" in h.get("Content-Type", "")

def is_instructions_part(h):
    return "x-aimpack-instructions" in h.get("Content-Type", "")

def get_filename(h):
    m = re.search(r'filename="?([^";\n]+)"?', h.get("Content-Disposition", ""))
    return m.group(1).strip() if m else None

def get_seq(h): return int(h.get("X-Aimpack-Sequence", "0"))
def get_target(h): return h.get("X-Aimpack-Patch-Target")

def is_base64_part(h):
    return h.get("Content-Transfer-Encoding", "").strip().lower() == "base64"

# Resolved file content is `str` for text parts and `bytes` for base64 parts.
# These three helpers are the only places that need to care which it is.

def decode_part_body(h, body):
    """Part body → resolved content: bytes for base64 parts, str otherwise."""
    if not is_base64_part(h):
        return body
    try:
        return base64.b64decode(body)
    except Exception as e:
        print(f"  ⚠ base64 decode failed ({get_filename(h)}): {e}", file=sys.stderr)
        return body

def default_file_headers(fn, content):
    """Headers for a file part that has no prior part to inherit from."""
    h = {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{fn}"',
        "Content-Transfer-Encoding": "8bit",
    }
    if isinstance(content, bytes):
        h["Content-Type"] = "application/octet-stream"
        h["Content-Transfer-Encoding"] = "base64"
    return h

def part_payload(content):
    """Resolved content → part body, re-encoding bytes as base64."""
    if isinstance(content, bytes):
        return base64.b64encode(content).decode("ascii")
    return content

def content_bytes(content):
    """Resolved content → the raw file bytes, for checksums."""
    return content if isinstance(content, bytes) else content.encode("utf-8")

# ── File resolution ───────────────────────────

def resolve_files(parts):
    files = {}
    for h, body in parts:
        if is_file_part(h):
            fn = get_filename(h)
            if fn: files[fn] = decode_part_body(h, body)

    diffs = sorted(
        [(get_seq(h), get_target(h), h, body) for h, body in parts
         if is_forward_diff(h) and get_target(h)],
        key=lambda x: x[0]
    )
    for seq, target, h, diff_text in diffs:
        # A diff whose target has no file part is an addition: patch against empty.
        base = files.get(target, "")
        if isinstance(base, bytes):
            print(f"  ⚠ Diff #{seq} → {target}: binary part, patch skipped", file=sys.stderr)
            continue
        try:
            patched = apply_patch(base, diff_text)
            if h.get(NO_FINAL_NEWLINE) == "true" and patched.endswith("\n"):
                patched = patched[:-1]      # undo generate_diff's normalization
            files[target] = patched
        except Exception as e:
            print(f"  ⚠ Diff #{seq} → {target}: {e}", file=sys.stderr)
    return files

# ── Path security ─────────────────────────────

def safe_path(dest, fp):
    if fp.startswith(("/", "\\")): return False, "absolute"
    if ".." in Path(fp).parts: return False, "traversal"
    try:
        (dest / fp).resolve().relative_to(dest.resolve())
        return True, "ok"
    except ValueError:
        return False, "escape"

DEFAULT_EXCLUDES = {".git", "__pycache__", "node_modules", ".DS_Store",
                    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".venv"}
DEFAULT_EXCLUDE_GLOBS = {"*.pyc", "*.pyo", "*.swp", "*.swo", "*.egg-info"}


def read_text_arg(arg):
    """Contents of `arg` if it names a readable file, else `arg` taken literally.

    Path.is_file() only swallows a fixed set of errnos, and ENAMETOOLONG (36) is
    not among them on Linux. Because that error is raised per path *component*,
    any inline argument whose text before the first '/' exceeded NAME_MAX (255)
    used to crash here — intermittently, depending on where a slash happened to
    fall in the text.
    """
    try:
        p = Path(arg)
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except OSError:
        pass
    return arg

def _should_exclude(path, source, extra_excludes=None):
    """Check if a file/dir should be excluded from packing."""
    import fnmatch
    rel = path.relative_to(source)
    if any(part in DEFAULT_EXCLUDES for part in rel.parts):
        return True
    if rel.name in DEFAULT_EXCLUDES:
        return True
    if any(fnmatch.fnmatch(rel.name, g) for g in DEFAULT_EXCLUDE_GLOBS):
        return True
    if extra_excludes:
        for pat in extra_excludes:
            if fnmatch.fnmatch(str(rel), pat) or fnmatch.fnmatch(rel.name, pat):
                return True
    return False

# ── Commands ──────────────────────────────────

def cmd_pack(args):
    source = Path(args.directory)
    if not source.is_dir():
        print(f"Error: {source} is not a directory", file=sys.stderr); sys.exit(1)
    extra_excludes = args.exclude.split(",") if args.exclude else None
    files = sorted(f for f in source.rglob("*") if f.is_file() and not _should_exclude(f, source, extra_excludes))
    if not files:
        print(f"Error: no files in {source}", file=sys.stderr); sys.exit(1)

    cid = _make_id()
    checksums = args.checksum.split(",") if args.checksum else []

    parts, labels = [], []          # labels parallel to parts, for collision diagnostics

    def add_part(label, headers, body):
        parts.append(build_part(headers, body))
        labels.append(label)

    if not args.no_preamble:
        add_part("preamble",
                 {"Content-Type": "text/x-aimpack-meta; role=preamble"},
                 f"This is an aimpack container (AI MimePack).\nSpec: {SPEC_URL}")

    if args.instructions:
        ct = "application/x-aimpack-instructions"
        add_part("instructions", {"Content-Type": ct}, read_text_arg(args.instructions))

    if args.readme:
        add_part("readme", {"Content-Type": "text/x-aimpack-meta; role=readme"},
                 read_text_arg(args.readme))

    # Load extensions for custom file type handling
    config = load_config()
    _registry.load_dir(EXTENSIONS_DIR)
    for p in config.get("resolver", {}).get("local_paths", []):
        _registry.load_dir(p)

    for fp in files:
        rel = str(fp.relative_to(source))
        metadata = {"timestamps": args.timestamps, "checksums": checksums, "author": args.author}

        # Check extension handlers first
        handler = None
        for ct, mod in _registry.handlers().items():
            if hasattr(mod, 'on_pack') and hasattr(mod, 'FILE_EXTENSIONS'):
                if fp.suffix in mod.FILE_EXTENSIONS:
                    handler = mod
                    break

        if handler:
            try:
                ext_h, ext_body = handler.on_pack(fp, metadata)
                ext_h.setdefault("Content-Disposition", f'attachment; filename="{rel}"')
                add_part(rel, ext_h, ext_body)
                print(f"  ⚙ {rel} (extension: {handler.__name__})")
                continue
            except Exception as e:
                print(f"  ⚠ Extension failed for {rel}, using default: {e}", file=sys.stderr)

        h = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{rel}"',
            "Content-Transfer-Encoding": "8bit",
        }
        try:
            content = fp.read_text(encoding="utf-8")
            raw = content.encode("utf-8")
        except UnicodeDecodeError:
            raw = fp.read_bytes()
            h["Content-Type"] = "application/octet-stream"
            h["Content-Transfer-Encoding"] = "base64"
            content = base64.b64encode(raw).decode("ascii")

        if args.timestamps:
            h["X-Aimpack-Modified"] = datetime.fromtimestamp(
                fp.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if checksums:
            # Checksum the real file bytes, not the base64 transport encoding, so
            # validation on unpack actually proves the file survived the round trip.
            h.update(compute_checksums(raw, checksums))
        if args.author:
            h["X-Aimpack-Author"] = args.author
        add_part(rel, h, content)

    scan = list(zip(labels, parts))
    if args.boundary:
        boundary = check_explicit_boundary(args.boundary, scan)
    else:
        boundary = minimal_boundary(scan, entropy=args.boundary_entropy)

    gh = {
        "MIME-Version": "1.0",
        "Content-Type": f'multipart/mixed; boundary="{boundary}"',
        "X-Aimpack-Version": __version__,
        "X-Aimpack-Container-Id": cid,
    }
    if args.parent: gh["X-Aimpack-Parent"] = args.parent
    if args.timestamps: gh["X-Aimpack-Created"] = _now()

    out = Path(args.output) if args.output else Path(source.name + ".aimpack")
    write_container(out, gh, parts, boundary, checksums)
    print(f"✓ Packed {len(files)} files → {out} (boundary {boundary!r}, {len(parts) + 1} occurrences)")


def cmd_unpack(args):
    gh, parts = parse_container(args.container)
    files = resolve_files(parts)
    dest = Path(args.output) if args.output else Path(".")
    dest.mkdir(parents=True, exist_ok=True)

    # Validate each file part against its own recorded checksums. Checking the
    # *resolved* content instead would be a false alarm on any container with
    # forward diffs: the header describes the part body, not the patched result.
    for h, body in parts:
        if is_file_part(h) and has_part_checksums(h):
            for w in validate_checksums(content_bytes(decode_part_body(h, body)), h):
                print(f"  ⚠ {get_filename(h)}:{w}", file=sys.stderr)

    # Load extensions for unknown types
    config = load_config()
    _registry.load_dir(EXTENSIONS_DIR)

    extracted = 0
    for fn, content in files.items():
        ok, reason = safe_path(dest, fn)
        if not ok:
            print(f"  ⚠ SKIP {fn}: {reason}", file=sys.stderr); continue
        out = dest / fn
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            out.write_bytes(content)
        else:
            out.write_text(content, encoding="utf-8", newline="")
        print(f"  ✓ {fn}"); extracted += 1

    # Handle extension-managed parts
    for h, body in parts:
        ct = h.get("Content-Type", "")
        if not is_file_part(h) and not is_diff_part(h) and not is_meta_part(h) and not is_instructions_part(h):
            handler = _registry.get(ct) or _registry.resolve(ct, config)
            if handler and hasattr(handler, 'on_unpack'):
                try: handler.on_unpack(h, body, dest)
                except Exception as e:
                    print(f"  ⚠ Extension error ({ct}): {e}", file=sys.stderr)

    # Show instructions
    for h, body in parts:
        if is_instructions_part(h):
            print(f"\n📋 Instructions:\n{body}")

    print(f"\nExtracted {extracted} files → {dest}/")


def cmd_diff(args):
    gh, parts = parse_container(args.container)
    boundary = get_boundary(gh)
    current = resolve_files(parts)
    max_seq = max((get_seq(h) for h, _ in parts if is_diff_part(h)), default=0)

    targets = args.targets
    tp = Path(targets[0]) if targets else None
    pairs = []            # (name, new_content); additions patch against ""
    added = set()
    skipped_new = 0

    def note(name, new, old):
        """Record a change. `old is None` means the file is not in the container."""
        nonlocal skipped_new
        if old is None:
            if args.no_new:
                skipped_new += 1
                return
            added.add(name)
        pairs.append((name, new))

    def read_or_skip(path, name):
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"  ⚠ {name}: binary file, diffs are text-only", file=sys.stderr)
            return None

    if tp and tp.is_dir():
        # Walk the tree the way pack does, so files on disk that the container
        # has never seen register as additions instead of vanishing silently.
        extra = args.exclude.split(",") if args.exclude else None
        disk_files = sorted(f for f in tp.rglob("*")
                            if f.is_file() and not _should_exclude(f, tp, extra))
        for fp in disk_files:
            name = str(fp.relative_to(tp))
            old = current.get(name)
            if isinstance(old, bytes):
                print(f"  ⚠ {name}: binary part, skipped", file=sys.stderr); continue
            new = read_or_skip(fp, name)
            if new is None: continue
            if old is None or new != old:
                note(name, new, old)
    else:
        base = Path(args.base) if args.base else None
        for t in targets:
            p = Path(t)
            if not p.is_file():
                print(f"  ⚠ {t}: not found", file=sys.stderr); continue
            matched = next((c for c in current
                            if c == t or c.endswith("/" + t) or Path(c).name == p.name), None)
            if matched is not None and isinstance(current[matched], bytes):
                print(f"  ⚠ {matched}: binary part, skipped", file=sys.stderr); continue
            new = read_or_skip(p, t)
            if new is None: continue
            if matched is not None:
                if new != current[matched]: note(matched, new, current[matched])
                else: print(f"  — {matched}: no changes")
            else:
                # Not in the container: an addition. Name it relative to --base
                # when given, so it lands at the right path inside the container.
                name = str(p)
                if base:
                    try: name = str(p.relative_to(base))
                    except ValueError:
                        print(f"  ⚠ {t}: not under --base {base}", file=sys.stderr); continue
                note(name, new, None)

    if not pairs:
        msg = "No changes."
        if skipped_new:
            msg += (f" ({skipped_new} file(s) on disk are not in the container; "
                    f"drop --no-new to add them.)")
        print(msg); return

    # Drop any recorded digest before appending; it is restamped over the final
    # text below, since a digest of the pre-append container would be stale.
    digest_algs = recorded_digest_algs(gh)
    container_text = canonical_container_text(
        Path(args.container).read_text(encoding="utf-8"))
    closing = f"--{boundary}--"
    idx = container_text.rstrip().rfind(closing)
    if idx >= 0: container_text = container_text[:idx]

    appended = ""
    seq = max_seq
    for name, new_content in pairs:
        seq += 1
        diff_text = generate_diff(current.get(name, ""), new_content, name)
        if not diff_text: continue
        # diff appends cannot rewrite the container, so the inherited boundary is
        # fixed: a colliding patch body has to be refused, not silently written.
        hits = boundary_conflicts(boundary, [(name, diff_text)])
        if hits:
            print(f"Error: patch for {name} contains a line that would be read as this "
                  f"container's boundary {boundary!r}:", file=sys.stderr)
            for label, n, line in hits[:3]:
                print(f"  {label}:{n}: {line[:72]}", file=sys.stderr)
            print("Repack with a longer explicit boundary "
                  "(aimpack pack <dir> --boundary <token>) before diffing.", file=sys.stderr)
            sys.exit(1)
        h = {
            "Content-Type": "text/x-diff",
            "X-Aimpack-Patch-Target": name,
            "X-Aimpack-Sequence": str(seq),
            "X-Aimpack-Patch-Direction": "forward",
        }
        if name in added: h["X-Aimpack-Patch-Op"] = "add"
        if lacks_final_newline(new_content): h[NO_FINAL_NEWLINE] = "true"
        if args.message: h["X-Aimpack-Patch-Message"] = args.message
        if args.author: h["X-Aimpack-Author"] = args.author
        if args.timestamps: h["X-Aimpack-Patch-Timestamp"] = _now()
        appended += f"--{boundary}\n{build_part(h, diff_text)}\n\n"
        print(f"  ✓ diff #{seq}: {name}" + ("  (new file)" if name in added else ""))

    appended += f"--{boundary}--\n"
    out = Path(args.output) if args.output else Path(args.container)
    out.write_text(stamp_container_digest(container_text + appended, digest_algs),
                   encoding="utf-8")
    suffix = f", {len(added)} new" if added else ""
    print(f"Appended {seq - max_seq} diff(s){suffix} → {out}")


def cmd_compact(args):
    gh, parts = parse_container(args.container)
    boundary = get_boundary(gh)
    current = resolve_files(parts)

    existing_inv = [(h, b) for h, b in parts if is_inverse_diff(h)]
    new_inv = []
    for h, b in parts:
        if is_forward_diff(h):
            ih = dict(h); ih["X-Aimpack-Patch-Direction"] = "inverse"
            # The flag describes the forward diff's result; the inverse restores
            # the prior state, whose newline status this header cannot express.
            ih.pop(NO_FINAL_NEWLINE, None)
            new_inv.append((ih, invert_diff(b)))

    new_parts = []
    emitted = set()
    for h, b in parts:
        if is_meta_part(h) or is_instructions_part(h):
            new_parts.append(build_part(h, b))

    for h, b in parts:
        if is_file_part(h):
            fn = get_filename(h)
            if fn and fn in current:
                nh = dict(h)
                if args.timestamps: nh["X-Aimpack-Modified"] = _now()
                cb = content_bytes(current[fn])
                for sfx, alg in [("CRC32","crc32"),("MD5","md5"),("SHA256","sha256")]:
                    k = f"X-Aimpack-Checksum-{sfx}"
                    if k in nh: nh.update(compute_checksums(cb, [alg]))
                new_parts.append(build_part(nh, part_payload(current[fn])))
                emitted.add(fn)

    # Files introduced by add-diffs have no file part yet; give them one, or
    # compaction would silently drop them.
    for fn in sorted(set(current) - emitted):
        nh = default_file_headers(fn, current[fn])
        if args.timestamps: nh["X-Aimpack-Modified"] = _now()
        new_parts.append(build_part(nh, part_payload(current[fn])))

    for h, b in existing_inv + new_inv:
        new_parts.append(build_part(h, b))

    for h, b in parts:
        ct = h.get("Content-Type", "")
        if "x-aimpack-ref" in ct or "x-aimpack-checkpoint" in ct:
            new_parts.append(build_part(h, b))

    # Compaction materializes file content that was never scanned at pack time,
    # so the inherited boundary has to be re-checked. This command rewrites the
    # whole container, so a replacement is safe here.
    boundary, replaced = ensure_boundary(boundary, _scan_targets(new_parts))
    if replaced:
        gh = dict(gh, **{"Content-Type": f'multipart/mixed; boundary="{boundary}"'})
        print(f"  ℹ boundary reissued as {boundary!r} (compacted content collided with the old one)")

    digest_algs = recorded_digest_algs(gh)
    out = Path(args.output) if args.output else Path(args.container)
    write_container(out, without_digest_headers(gh), new_parts, boundary, digest_algs)
    print(f"✓ Compacted: {len(current)} files, {len(existing_inv) + len(new_inv)} inverse diffs")


def cmd_squash(args):
    gh, parts = parse_container(args.container)
    boundary = get_boundary(gh)
    current = resolve_files(parts)

    if not args.range or ":" not in args.range:
        print("Error: --range FROM:TO required", file=sys.stderr); sys.exit(1)
    r_from, r_to = map(int, args.range.split(":"))
    if r_from <= r_to:
        print("Error: FROM > TO required", file=sys.stderr); sys.exit(1)

    inv_by_target = {}
    other = []
    for h, b in parts:
        if is_inverse_diff(h):
            t = get_target(h)
            if t: inv_by_target.setdefault(t, []).append((get_seq(h), h, b))
        else:
            other.append((h, b))

    new_parts = [build_part(h, b) for h, b in other]

    for target, diffs in inv_by_target.items():
        diffs.sort(key=lambda x: x[0], reverse=True)
        in_range = [d for d in diffs if r_to < d[0] <= r_from]
        outside = [d for d in diffs if d[0] <= r_to or d[0] > r_from]

        if len(in_range) < 2 or target not in current:
            for s, h, b in diffs: new_parts.append(build_part(h, b))
            continue

        # Walk backwards from current to compute states
        states = {}
        st = current[target]
        for s, h, b in diffs:
            states[s + 1] = st
            try: st = apply_patch(st, b)
            except: pass
            states[s] = st

        s_from = states.get(r_from + 1, states.get(r_from))
        s_to = states.get(r_to)
        if s_from is not None and s_to is not None:
            sq = generate_diff(s_from, s_to, target)
            if sq:
                new_parts.append(build_part({
                    "Content-Type": "text/x-diff",
                    "X-Aimpack-Patch-Target": target,
                    "X-Aimpack-Sequence": str(r_from),
                    "X-Aimpack-Patch-Direction": "inverse",
                    "X-Aimpack-Squashed-Range": f"{r_from}:{r_to}",
                }, sq))
        for s, h, b in outside: new_parts.append(build_part(h, b))

    # Squashing synthesizes new patch bodies; re-check as in compact.
    boundary, replaced = ensure_boundary(boundary, _scan_targets(new_parts))
    if replaced:
        gh = dict(gh, **{"Content-Type": f'multipart/mixed; boundary="{boundary}"'})
        print(f"  ℹ boundary reissued as {boundary!r} (squashed content collided with the old one)")

    digest_algs = recorded_digest_algs(gh)
    out = Path(args.output) if args.output else Path(args.container)
    write_container(out, without_digest_headers(gh), new_parts, boundary, digest_algs)
    print(f"✓ Squashed range {r_from}:{r_to}")


def cmd_log(args):
    gh, parts = parse_container(args.container)
    cid = gh.get("X-Aimpack-Container-Id", "?")
    print(f"Container: {cid}")
    print(f"Version:   {gh.get('X-Aimpack-Version', '?')} (reader: {__version__})")
    print(f"Boundary:  {get_boundary(gh)!r}")
    if "X-Aimpack-Created" in gh: print(f"Created:   {gh['X-Aimpack-Created']}")
    if "X-Aimpack-Parent" in gh: print(f"Parent:    {gh['X-Aimpack-Parent']}")

    fnames = [get_filename(h) for h, _ in parts if is_file_part(h)]
    print(f"Files:     {len(fnames)}")
    for f in fnames: print(f"  📄 {f}")

    diffs = [(h, b) for h, b in parts if is_diff_part(h)]
    if diffs:
        print(f"\nHistory ({len(diffs)}):")
        for h, _ in sorted(diffs, key=lambda x: get_seq(x[0])):
            d = h.get("X-Aimpack-Patch-Direction", "forward")
            arrow = "→" if d == "forward" else "←"
            s = f"  {arrow} #{get_seq(h)} {get_target(h) or '?'}"
            sq = h.get("X-Aimpack-Squashed-Range")
            if sq: s += f" [squashed {sq}]"
            a = h.get("X-Aimpack-Author")
            if a: s += f" ({a})"
            m = h.get("X-Aimpack-Patch-Message")
            if m: s += f" — {m}"
            t = h.get("X-Aimpack-Patch-Timestamp")
            if t: s += f" [{t}]"
            print(s)

    # Instructions
    for h, b in parts:
        if is_instructions_part(h):
            print(f"\n📋 Instructions:")
            # Try to pretty-print if S-expr
            try:
                parsed = parse_sexpr(b)
                print(sexpr_to_string(parsed, indent=1))
            except:
                print(b)

    meta = [re.search(r"role=(\w+)", h.get("Content-Type","")) for h,_ in parts if is_meta_part(h)]
    roles = [m.group(1) for m in meta if m]
    if roles: print(f"\nMeta: {', '.join(roles)}")

    # Extension-handled parts
    config = load_config()
    _registry.load_dir(EXTENSIONS_DIR)
    for h, b in parts:
        ct = h.get("Content-Type", "")
        if not is_file_part(h) and not is_diff_part(h) and not is_meta_part(h) and not is_instructions_part(h):
            handler = _registry.get(ct)
            if handler and hasattr(handler, 'on_display'):
                try:
                    summary = handler.on_display(h, b)
                    if summary: print(f"  ⚙ {ct}: {summary}")
                except Exception as e:
                    print(f"  ⚠ Display error ({ct}): {e}", file=sys.stderr)


def is_readme_part(h):
    return is_meta_part(h) and "role=readme" in h.get("Content-Type", "")


def _replace_or_insert(parts, match, headers, body):
    """Replace the first part satisfying `match`; if absent, insert it ahead of
    the first file or diff part, since meta parts lead the container."""
    out, done = [], False
    for h, b in parts:
        if not done and match(h):
            out.append((headers, body)); done = True
        else:
            out.append((h, b))
    if not done:
        idx = next((i for i, (h, _) in enumerate(out)
                    if is_file_part(h) or is_diff_part(h)), len(out))
        out.insert(idx, (headers, body))
    return out, done


def cmd_set_meta(args):
    """set-instructions / set-readme: rewrite one meta part in place.

    Repacking to change instructions mints a new container id and discards
    lineage, which made every merge ship the baseline's stale instructions.
    """
    gh, parts = parse_container(args.container)
    boundary = get_boundary(gh)

    if args.command == "set-instructions":
        headers = {"Content-Type": "application/x-aimpack-instructions"}
        match, label = is_instructions_part, "instructions"
    else:
        headers = {"Content-Type": "text/x-aimpack-meta; role=readme"}
        match, label = is_readme_part, "readme"

    new_parts, replaced_existing = _replace_or_insert(
        parts, match, headers, read_text_arg(args.value))
    built = [build_part(h, b) for h, b in new_parts]

    boundary, reissued = ensure_boundary(boundary, _scan_targets(built))
    if reissued:
        gh = dict(gh, **{"Content-Type": f'multipart/mixed; boundary="{boundary}"'})
        print(f"  ℹ boundary reissued as {boundary!r} (new {label} collided with the old one)")

    digest_algs = recorded_digest_algs(gh)
    out = Path(args.output) if args.output else Path(args.container)
    write_container(out, without_digest_headers(gh), built, boundary, digest_algs)
    print(f"✓ {'Replaced' if replaced_existing else 'Added'} {label} → {out} "
          f"(container {gh.get('X-Aimpack-Container-Id', '?')})")


def cmd_fork(args):
    gh, parts = parse_container(args.container)
    current = resolve_files(parts)
    parent_id = gh.get("X-Aimpack-Container-Id", "?")
    max_seq = max((get_seq(h) for h, _ in parts if is_diff_part(h)), default=0)

    new_id = _make_id()
    new_parts = [
        build_part({"Content-Type": "text/x-aimpack-meta; role=preamble"},
                    f"This is an aimpack container (AI MimePack).\nSpec: {SPEC_URL}"),
        build_part({
            "Content-Type": "application/x-aimpack-ref",
            "X-Aimpack-Ref-Type": "parent",
            "X-Aimpack-Ref-Container-Id": parent_id,
        }, f"Forked from {parent_id} at sequence {max_seq}"),
    ]

    for h, b in parts:
        if is_meta_part(h) and "preamble" not in h.get("Content-Type", ""):
            new_parts.append(build_part(h, b))
        if is_instructions_part(h):
            new_parts.append(build_part(h, b))

    forked = set()
    for h, _ in parts:
        if is_file_part(h):
            fn = get_filename(h)
            if fn and fn in current:
                nh = dict(h); nh["X-Aimpack-Modified"] = _now()
                new_parts.append(build_part(nh, part_payload(current[fn])))
                forked.add(fn)

    for fn in sorted(set(current) - forked):     # files added by diffs, as in compact
        nh = default_file_headers(fn, current[fn])
        nh["X-Aimpack-Modified"] = _now()
        new_parts.append(build_part(nh, part_payload(current[fn])))

    scan = _scan_targets(new_parts)
    boundary = (check_explicit_boundary(args.boundary, scan) if args.boundary
                else minimal_boundary(scan, entropy=args.boundary_entropy))
    new_gh = {
        "MIME-Version": "1.0",
        "Content-Type": f'multipart/mixed; boundary="{boundary}"',
        "X-Aimpack-Version": __version__,
        "X-Aimpack-Container-Id": new_id,
        "X-Aimpack-Parent": parent_id,
        "X-Aimpack-Fork-Point": str(max_seq),
        "X-Aimpack-Created": _now(),
    }

    out = Path(args.output) if args.output else Path("fork.aimpack")
    write_container(out, new_gh, new_parts, boundary, recorded_digest_algs(gh))
    print(f"✓ Forked {parent_id} → {new_id} (seq {max_seq}) → {out}")


def cmd_verify(args):
    """Check recorded checksums without unpacking."""
    path = Path(args.container)
    text = path.read_text(encoding="utf-8")
    gh, parts = parse_container(str(path))
    problems = 0

    results = verify_container_digest(text)
    if results:
        for alg, expected, actual, ok in results:
            if ok:
                print(f"  ✓ container {alg}: {expected}")
            else:
                problems += 1
                detail = f"got {actual}" if actual else "unknown algorithm"
                print(f"  ✗ container {alg}: expected {expected}, {detail}", file=sys.stderr)
    else:
        print("  — no container digest recorded")

    checked = 0
    for h, body in parts:
        if not (is_file_part(h) and has_part_checksums(h)):
            continue
        checked += 1
        warnings = validate_checksums(content_bytes(decode_part_body(h, body)), h)
        for w in warnings:
            problems += 1
            print(f"  ✗ {get_filename(h)}:{w}", file=sys.stderr)
        if not warnings and args.verbose:
            print(f"  ✓ {get_filename(h)}")

    n_files = sum(1 for h, _ in parts if is_file_part(h))
    print(f"{n_files} file part(s), {checked} with checksums, {problems} problem(s)")
    if problems:
        sys.exit(1)


def cmd_ext(args):
    ensure_dirs()
    if args.ext_command == "list":
        _registry.load_dir(EXTENSIONS_DIR)
        handlers = _registry.list_handlers()
        if handlers:
            for ct, path in handlers.items():
                print(f"  {ct} → {path}")
        else:
            print(f"  No extensions installed. Dir: {EXTENSIONS_DIR}")

    elif args.ext_command == "install":
        url = args.source
        if url.startswith(("http://", "https://")):
            import urllib.request
            filename = url.rsplit("/", 1)[-1]
            dest = EXTENSIONS_DIR / filename
            urllib.request.urlretrieve(url, dest)
            print(f"  ✓ Installed → {dest}")
        else:
            src = Path(url)
            if src.is_file():
                import shutil
                dest = EXTENSIONS_DIR / src.name
                shutil.copy2(src, dest)
                print(f"  ✓ Installed → {dest}")
            else:
                print(f"  Error: {url} not found", file=sys.stderr)

    elif args.ext_command == "resolve":
        config = load_config()
        _registry.load_dir(EXTENSIONS_DIR)
        handler = _registry.resolve(args.content_type, config)
        if handler:
            print(f"  ✓ Found: {handler.__file__}")
        else:
            print(f"  ✗ No handler for {args.content_type}")

    elif args.ext_command == "config":
        config = load_config()
        print(json.dumps(config, indent=2))


# ── Dedup ─────────────────────────────────────

def find_shared_blocks(files, min_lines=5):
    """Find verbatim identical contiguous blocks across multiple files.
    Returns [{hash, text, files: [(name, start_line, end_line)]}]"""
    from difflib import SequenceMatcher
    import hashlib

    filenames = sorted(files.keys())
    blocks = {}  # hash -> {"text": str, "files": set()}

    for i, fn1 in enumerate(filenames):
        text1 = files[fn1].splitlines(keepends=True)
        for fn2 in filenames[i+1:]:
            text2 = files[fn2].splitlines(keepends=True)
            sm = SequenceMatcher(None, text1, text2, autojunk=False)
            for match in sm.get_matching_blocks():
                if match.size >= min_lines:
                    block_text = ''.join(text1[match.a:match.a + match.size])
                    h = hashlib.md5(block_text.encode()).hexdigest()[:12]
                    if h not in blocks:
                        blocks[h] = {"text": block_text, "files": set()}
                    blocks[h]["files"].update([fn1, fn2])

    # Keep only blocks shared by 2+ files
    return {h: b for h, b in blocks.items() if len(b["files"]) >= 2}


def cmd_dedup(args):
    """Scan text files for verbatim identical sections and deduplicate."""
    import shutil, tempfile

    # Resolve input (container or directory)
    target = Path(args.container)
    workdir = Path(tempfile.mkdtemp(prefix="aimpack_dedup_"))

    if target.suffix == '.aimpack' or (target.is_file()):
        # Unpack container
        tmp_unpack = workdir / "unpacked"
        tmp_unpack.mkdir()
        gh, parts = parse_container(str(target))
        current = resolve_files(parts)
        for name, content in current.items():
            outpath = tmp_unpack / name
            outpath.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                outpath.write_bytes(content)
            else:
                outpath.write_text(content, encoding="utf-8")
        target = tmp_unpack
    elif not target.is_dir():
        print(f"Error: {target} is not a directory or aimpack container", file=sys.stderr)
        sys.exit(1)

    # Collect text files
    TEXT_EXTS = {'.md', '.txt', '.py', '.sh', '.json', '.yaml', '.yml',
                 '.html', '.css', '.js', '.xml', '.cfg', '.ini', '.toml',
                 '.tex', '.rst', '.csv', '.tsv'}
    files = {}
    for fpath in target.rglob('*'):
        if fpath.is_file() and fpath.suffix.lower() in TEXT_EXTS:
            try:
                content = fpath.read_text(encoding="utf-8")
                if len(content) > 50:  # skip tiny files
                    files[str(fpath.relative_to(target))] = content
            except:
                pass

    if len(files) < 2:
        print(f"Need at least 2 text files; found {len(files)}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {len(files)} files (min {args.min_lines} lines per block)...")
    blocks = find_shared_blocks(files, min_lines=args.min_lines)

    if not blocks:
        print("No shared blocks found.")
        return

    # Sort by prevalence (most shared first)
    sorted_blocks = sorted(blocks.items(), key=lambda x: -len(x[1]["files"]))

    # Write dedup output
    outdir = Path(args.output) if args.output else (target.parent / f"{target.name}_dedup")
    outdir.mkdir(parents=True, exist_ok=True)
    shared_dir = outdir / "_shared"
    shared_dir.mkdir(exist_ok=True)

    # Write each shared block
    for h, block in sorted_blocks:
        (shared_dir / f"{h}.txt").write_text(block["text"], encoding="utf-8")

    # Build manifest
    manifest = {"blocks": {}, "files": {}}
    for h, block in sorted_blocks:
        lines = len(block["text"].splitlines())
        manifest["blocks"][h] = {
            "size_lines": lines,
            "size_chars": len(block["text"]),
            "shared_by": sorted(block["files"]),
            "preview": block["text"][:80].replace("\n", "↵"),
        }

    # Per-file composition (simplified: just list which blocks each file contains)
    for fname in sorted(files.keys()):
        manifest["files"][fname] = []
        for h, block in sorted_blocks:
            if fname in block["files"]:
                manifest["files"][fname].append(h)

    manifest_path = outdir / "dedup-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Summary
    shared_count = len(sorted_blocks)
    total_shared_lines = sum(len(b["text"].splitlines()) for _, b in sorted_blocks)
    max_shared = len(sorted_blocks[0][1]["files"]) if sorted_blocks else 0

    print(f"  Blocks found:  {shared_count}")
    print(f"  Most shared:   {max_shared} files")
    print(f"  Shared lines:  {total_shared_lines}")
    print(f"  Output:        {outdir}")
    print(f"  Manifest:      {manifest_path}")

    if not args.keep_workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    else:
        print(f"  Workdir:       {workdir}")




def main():
    p = argparse.ArgumentParser(prog="aimpack",
        description="AI MimePack: LLM-ergonomic MIME containers.")
    p.add_argument("--version", action="version", version=f"aimpack {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # pack
    s = sub.add_parser("pack", help="Pack directory into container")
    s.add_argument("directory")
    s.add_argument("-o", "--output")
    s.add_argument("--timestamps", action="store_true")
    s.add_argument("--checksum", help="crc32,md5,sha256 (per file part and whole container)")
    s.add_argument("--author")
    s.add_argument("--instructions", help="Text, S-expr, or path to file")
    s.add_argument("--readme", help="Text or path to file")
    s.add_argument("--no-preamble", action="store_true")
    s.add_argument("--exclude", help="Extra exclude patterns, comma-separated")
    s.add_argument("--boundary", help="Explicit boundary token; fails if it collides with content")
    s.add_argument("--boundary-entropy", type=int, default=BOUNDARY_ENTROPY,
                   metavar="N", help=f"Random chars appended to the minimal safe "
                                     f"boundary length (default: {BOUNDARY_ENTROPY})")
    s.add_argument("--parent", metavar="CONTAINER-ID",
                   help="Declare lineage: records X-Aimpack-Parent on a fresh pack")

    # unpack
    s = sub.add_parser("unpack", help="Extract files from container")
    s.add_argument("container")
    s.add_argument("-o", "--output")

    # diff
    s = sub.add_parser("diff", help="Append diffs for changes")
    s.add_argument("container")
    s.add_argument("targets", nargs="+")
    s.add_argument("-m", "--message")
    s.add_argument("--author")
    s.add_argument("--timestamps", action="store_true")
    s.add_argument("-o", "--output")
    s.add_argument("--no-new", action="store_true",
                   help="Only diff files already in the container; ignore additions")
    s.add_argument("--base", metavar="DIR",
                   help="Name added files relative to DIR (named-target mode)")
    s.add_argument("--exclude", help="Extra exclude patterns, comma-separated (directory mode)")

    # compact
    s = sub.add_parser("compact", help="Apply forward diffs, store inverses")
    s.add_argument("container")
    s.add_argument("-o", "--output")
    s.add_argument("--timestamps", action="store_true")

    # squash
    s = sub.add_parser("squash", help="Merge inverse diff range")
    s.add_argument("container")
    s.add_argument("--range", required=True, help="FROM:TO (e.g. 5:2)")
    s.add_argument("-o", "--output")

    # log
    s = sub.add_parser("log", help="Show container info and history")
    s.add_argument("container")

    # fork
    s = sub.add_parser("fork", help="Fork with parent reference")
    s.add_argument("container")
    s.add_argument("-o", "--output")
    s.add_argument("--boundary", help="Explicit boundary token; fails if it collides with content")
    s.add_argument("--boundary-entropy", type=int, default=BOUNDARY_ENTROPY,
                   metavar="N", help=f"Random chars appended to the minimal safe "
                                     f"boundary length (default: {BOUNDARY_ENTROPY})")

    # verify
    s = sub.add_parser("verify", help="Check recorded checksums without unpacking")
    s.add_argument("container")
    s.add_argument("-v", "--verbose", action="store_true", help="List each valid part")

    # set-instructions / set-readme
    for _name, _help in [("set-instructions", "Replace the instructions part in place"),
                         ("set-readme", "Replace the readme part in place")]:
        s = sub.add_parser(_name, help=_help)
        s.add_argument("container")
        s.add_argument("value", help="Text, S-expr, or path to file")
        s.add_argument("-o", "--output")

    # ext
    s = sub.add_parser("ext", help="Manage extensions")
    es = s.add_subparsers(dest="ext_command", required=True)
    es.add_parser("list", help="List installed extensions")
    ei = es.add_parser("install", help="Install extension")
    ei.add_argument("source", help="URL or local path")
    er = es.add_parser("resolve", help="Find handler for content type")
    er.add_argument("content_type")
    es.add_parser("config", help="Show config")

    # dedup
    s = sub.add_parser("dedup", help="Find verbatim identical sections across files")
    s.add_argument("container", help="Aimpack container or directory to scan")
    s.add_argument("-o", "--output", help="Output directory for shared blocks")
    s.add_argument("-m", "--min-lines", type=int, default=5,
                   help="Minimum identical lines to consider (default: 5)")
    s.add_argument("--keep-workdir", action="store_true",
                   help="Keep temporary unpack directory")

    args = p.parse_args()
    cmds = {
        "pack": cmd_pack, "unpack": cmd_unpack, "diff": cmd_diff,
        "compact": cmd_compact, "squash": cmd_squash, "log": cmd_log,
        "fork": cmd_fork, "ext": cmd_ext, "dedup": cmd_dedup,
        "set-instructions": cmd_set_meta, "set-readme": cmd_set_meta,
        "verify": cmd_verify,
    }
    cmds[args.command](args)

if __name__ == "__main__":
    main()
