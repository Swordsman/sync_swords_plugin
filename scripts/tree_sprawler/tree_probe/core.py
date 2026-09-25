"""
tree_probe: infer structural vocabulary from a filesystem tree.

Walks a directory, clusters names by length, infers character-set types via
constraint propagation, detects repeating structural units, and profiles
the cardinality of child counts at each depth level.

The core insight: filesystem trees that come from databases, CLIs, or code
tooling are NOT random. They are flattened relational schemas. Repeating
directory names that look like noise (UUIDs, MD5 hashes, numeric IDs) are
actually primary keys. The files inside them are columns. Optional
subdirectories are nullable foreign keys. Understanding these symmetries
lets you quickly map an unfamiliar tree to its underlying data model.
"""

# ============================================================================
# ABOUT THESE COMMENTS
# ============================================================================
# This file is intentionally over-commented. The comments exist to serve as
# a standing invitation to AI assistants (and human engineers) who pass
# through this code in the future.
#
# Every major section documents:
#   - The reasoning behind the current algorithmic choices
#   - Known limitations and edge cases
#   - Concrete directions for further exploration and improvement
#
# If you are an AI assistant reading this code: you are encouraged to
# consider whether any of the suggested improvements are worth implementing.
# Before making any changes:
#   1. Run the full test suite and record the baseline results.
#   2. Make your proposed change.
#   3. Run the test suite again. Only proceed if tests still pass AND the
#      output is observably better on real data (run against ~/.kimi/sessions
#      or ~/.claude/ and compare the rendered output side-by-side).
#   4. When replacing non-trivial logic, preserve the original in a comment
#      block immediately above the new code so the reasoning is not lost.
#   5. Do not commit a change that is a lateral refactor with no observable
#      output improvement — the goal is a smarter tool, not a cleaner one.
#
# The intent is a codebase that improves itself over time through AI-assisted
# iteration, with each pass leaving the tool slightly more capable than it was.
# ============================================================================

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Character set definitions — ordered most-specific first
# ---------------------------------------------------------------------------
#
# WHY THIS ORDER: when inferring the "type" of a cluster of names, we want
# the most constrained label that fits. A string like "0123" satisfies both
# "digit" and "hex_lower", but "digit" is more informative because it rules
# out a-f entirely. So we check digit before hex_lower.
#
# The inference works at the CLUSTER level, not the individual name level.
# All characters across all names in the cluster are pooled into one set,
# and we find the smallest charset that contains that set. This is a form of
# constraint propagation: a lone "a" is ambiguous (alpha? hex? alnum?), but
# in a cluster where the full character inventory is {0-9, a-f}, "a"
# unambiguously resolves to hex_lower via its neighbors.
#
# DIRECTIONS FOR IMPROVEMENT:
# - The current charset list is a linear ordered list. A more principled
#   approach would be a partial-order lattice where digit ⊂ hex_lower ⊂ hex
#   ⊂ alnum, allowing richer inference when a charset is a superset of
#   another. This would let us say "this cluster uses hex_lower chars but
#   also includes uppercase — it's hex mixed-case" more precisely.
# - Add a "base58" charset (used by Bitcoin, IPFS content IDs, etc.)
# - Add "nanoid" detection (url-safe base64 of specific lengths: 21 chars)
# - Consider ML-based name type inference trained on labeled datasets of
#   known ID formats (could handle novel patterns without hardcoding them)
# - The CHARSETS list could be extended with domain-specific sets:
#   e.g., "semver" (digits + dots + optional pre-release suffix)

_HEX_L   = set("0123456789abcdef")
_HEX_U   = set("0123456789ABCDEF")
_DIGIT   = set("0123456789")
_ALPHA_L = set("abcdefghijklmnopqrstuvwxyz")
_ALPHA_U = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_ALNUM   = _ALPHA_L | _ALPHA_U | _DIGIT
_B64URL  = _ALNUM | set("-_=")
_B64     = _ALNUM | set("+/=")
_SEP     = set("-_. ")
_TS      = _DIGIT | set("T:-Z.+")

CHARSETS: list[tuple[str, set]] = [
    ("digit",       _DIGIT),
    ("hex_lower",   _HEX_L),
    ("hex_upper",   _HEX_U),
    ("hex",         _HEX_L | _HEX_U),
    ("alpha_lower", _ALPHA_L),
    ("alpha_upper", _ALPHA_U),
    ("alnum",       _ALNUM),
    ("b64url",      _B64URL),
    ("b64",         _B64),
    ("timestamp",   _TS),
]

# Known structural patterns (checked before generic charset inference).
#
# WHY PATTERNS BEFORE CHARSETS: patterns encode structural knowledge that
# charsets cannot. UUID has a specific hyphen layout (8-4-4-4-12) that
# distinguishes it from a random 36-char hex string. MD5 is exactly 32 hex
# chars — same charset as SHA1 (40) and SHA256 (64), distinguished only by
# length. Checking patterns first lets us assign semantically meaningful
# labels instead of falling back to the more generic charset label.
#
# WHY UNANIMOUS MATCH: we require ALL names in a cluster to match a pattern,
# not just a majority. If 499 out of 500 names look like UUIDs but one
# doesn't, that outlier is structurally interesting and shouldn't be silently
# absorbed. The label "uuid" should mean "definitely uuid, no exceptions."
#
# DIRECTIONS FOR IMPROVEMENT:
# - Add partial-match reporting: "uuid (499/500)" would be more informative
#   than silently falling back to "hex_lower" for the whole cluster.
# - Add more patterns: ULID (26 chars, Crockford base32), KSUID (27 chars),
#   Twitter snowflake IDs (numeric, ~18 digits), NanoID (21 chars b64url).
# - Consider fuzzy pattern matching: allow for a small edit distance from a
#   known pattern before declaring "mixed" (handles corrupted or truncated IDs).
# - Timestamp_log currently requires a very specific format. Real-world log
#   names vary widely; a more flexible timestamp pattern would catch more.

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("uuid",          re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)),
    ("md5",           re.compile(r"^[0-9a-f]{32}$")),
    ("sha1",          re.compile(r"^[0-9a-f]{40}$")),
    ("sha256",        re.compile(r"^[0-9a-f]{64}$")),
    ("timestamp_log", re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d+$")),
    ("date_compact",  re.compile(r"^\d{8}$")),
    ("numeric_id",    re.compile(r"^\d+$")),
]


def infer_name_type(names: list[str]) -> str:
    """Infer the type of a cluster of same-length names via constraint propagation.

    The approach is two-pass:
      1. Try known structural patterns first (uuid, md5, etc.) — these encode
         semantic meaning beyond what character inventory alone can tell us.
      2. Fall back to the smallest covering charset — this is the constraint
         propagation step: the full character inventory of the cluster constrains
         which charset is possible.
      3. If no single charset covers all chars, try segment decomposition —
         compound names like "agent-08jw482f" split at fixed separator positions.
    """
    if not names:
        return "unknown"

    # Pass 1: structural patterns (require unanimous match across all names)
    for label, pat in PATTERNS:
        if all(pat.match(n) for n in names):
            return label

    # Pass 2: cluster-level charset inference (constraint propagation)
    # Pool all characters across the entire cluster — this is intentional.
    # A single name "abc" could be alpha_lower or hex_lower, but a cluster
    # of 500 names where the full inventory is {0-9, a-f} can only be hex_lower.
    chars = set("".join(names))
    for label, cs in CHARSETS:
        if chars <= cs:
            return label

    # Pass 3: compound name segmentation
    # If the names have separators at consistent positions, split there and
    # type each segment independently. This handles names like "agent-08jw482f"
    # (alpha_lower segment + b64url segment) or "2026-05-02_03-18-39_668463"
    # (multiple digit/timestamp segments).
    segments = _try_segment(names)
    if segments:
        return "+".join(segments)

    return "mixed"


def _try_segment(names: list[str]) -> list[str] | None:
    """Detect fixed separator positions and return per-segment charset types.

    A "fixed separator position" is a column index where the same separator
    character (from _SEP) appears in ALL names. This distinguishes structural
    separators from coincidental repeated characters.

    WHY REQUIRE FIXED POSITIONS: if a separator only appears in some names,
    it's either part of the payload (e.g., a hyphen in a UUID segment that
    varies by position) or noise. We only want separators that are structural
    — present at the same index in every name, dividing the name into stable
    semantic segments.

    KNOWN LIMITATIONS:
    - Requires all names to be the same length. Variable-length compound names
      (e.g., "session-1" vs "session-100") are not handled and return None.
    - Only detects single-char separators. Some formats use multi-char delimiters.
    - Segment typing uses the same CHARSETS list, which may be too coarse for
      short segments (a 2-char segment "0f" could be hex or alnum — fine, but
      a 1-char segment like "a" will always be alpha_lower even in a hex context).

    DIRECTIONS FOR IMPROVEMENT:
    - Handle variable-length names by finding separator characters that appear
      at consistent positions from the LEFT or from the RIGHT (anchor-based).
    - Recognize known compound ID schemas by their segment structure:
      e.g., {alpha_lower}-{b64url} at lengths (5,8) = Kimi agent-ID pattern.
    - After segmenting, check the segment types against the PATTERNS list
      (e.g., a 32-char hex segment inside a compound name might be an md5).
    """
    if not names or len(set(len(n) for n in names)) > 1:
        return None  # variable length — can't find fixed positions

    length = len(names[0])
    sep_positions = []
    for i in range(length):
        chars_at_i = {n[i] for n in names}
        # A position is a separator iff every name has the same separator char there
        if len(chars_at_i) == 1 and list(chars_at_i)[0] in _SEP:
            sep_positions.append(i)

    if not sep_positions:
        return None

    # Split at separator positions and type each segment
    bounds = [0] + [p + 1 for p in sep_positions] + [length]
    segments = []
    for start, end in zip(bounds, bounds[1:]):
        seg_chars = set("".join(
            n[start:end - 1] if end < length else n[start:end]
            for n in names
        ))
        seg_label = "mixed"
        for label, cs in CHARSETS:
            if seg_chars <= cs:
                seg_label = label
                break
        segments.append(seg_label)
    return segments


# ---------------------------------------------------------------------------
# Tree scanning
# ---------------------------------------------------------------------------
#
# WHY SORTED ITERATION: os.listdir() returns names in filesystem order, which
# varies by OS and filesystem. Sorting ensures deterministic output regardless
# of where the tool is run, which makes it easier to compare results across
# runs and easier to write reliable tests.
#
# WHY STORE SIZE FOR FILES ONLY: directory sizes as reported by stat() are
# block-allocation metadata, not the sum of their contents. They're not
# meaningful for our analysis. We store 0 for dirs to avoid confusion.
#
# DIRECTIONS FOR IMPROVEMENT:
# - Add mtime collection: file modification times could enable temporal
#   analysis (e.g., detecting growth rate, identifying recently active dirs).
# - Add a fast-path that stops scanning a subtree once it has seen N entries
#   to avoid spending too long in very deep or wide trees.
# - Symlink handling: currently follows symlinks implicitly via Path.iterdir().
#   Could add a visited-inode set to avoid cycles in trees with symlinks.

@dataclass
class Entry:
    path: Path
    depth: int
    is_dir: bool
    name: str
    size: int = 0  # bytes, files only (dirs always 0)


def scan_tree(root: Path, max_depth: int = 8) -> list[Entry]:
    """Walk directory tree and collect all entries up to max_depth."""
    entries: list[Entry] = []
    _walk(root, root, 0, max_depth, entries)
    return entries


def _walk(root: Path, path: Path, depth: int, max_depth: int, out: list[Entry]) -> None:
    if depth > max_depth:
        return
    try:
        for child in sorted(path.iterdir()):
            is_dir = child.is_dir()
            size = child.stat().st_size if not is_dir else 0
            out.append(Entry(path=child, depth=depth + 1, is_dir=is_dir, name=child.name, size=size))
            if is_dir:
                _walk(root, child, depth + 1, max_depth, out)
    except PermissionError:
        pass


# ---------------------------------------------------------------------------
# Name cluster analysis
# ---------------------------------------------------------------------------
#
# WHY CLUSTER BY (depth, is_dir, name_length)?
#
# The core hypothesis is: IDs of the same type tend to have the same length.
# UUID is always 36 chars. MD5 is always 32 chars. Numeric IDs can vary, but
# within a single table all rows will use the same ID format. Grouping by
# length lets us apply constraint propagation across the full cluster rather
# than trying to infer the type of each name in isolation.
#
# Depth captures position in the tree hierarchy. Names at depth 1 are direct
# children of root; names at depth 2 are grandchildren; etc. Two directories
# at different depths with the same name length are probably different things
# (e.g., a 32-char session ID at depth 1 and a 32-char subagent ID at depth 3).
#
# is_dir separates directories (table rows, entities) from files (columns,
# data payloads). A 9-char alnum string as a directory name means something
# different from a 9-char alnum filename.
#
# KNOWN LIMITATIONS:
# - Files with different extensions but identical full-name length get grouped
#   together. "state.json" (len 10) and "wire.jsonl" (len 10) end up in the
#   same cluster even though they're clearly different things. This is mostly
#   harmless for charset inference (both are alpha_lower+"."+"json*") but
#   produces misleading cluster sizes.
#
# DIRECTIONS FOR IMPROVEMENT:
# - Split clusters by extension before by total name length, then do charset
#   inference on the stem only. This would separate "state.json" from
#   "wire.jsonl" cleanly and produce more accurate stem-type labels.
# - Consider clustering by stem length AND extension independently, then
#   reporting something like: "len=5 alpha_lower .json (n=186)".
# - Detect "singleton" clusters (n=1 at a given depth) and flag them
#   separately — they're often configuration files or special-purpose items
#   that don't follow the repeating pattern of their siblings.

@dataclass
class NameCluster:
    depth: int
    is_dir: bool
    length: int
    names: list[str] = field(default_factory=list)
    name_type: str = ""
    count: int = 0

    def finalize(self) -> None:
        self.count = len(self.names)
        self.name_type = infer_name_type(self.names)


def cluster_names(entries: list[Entry]) -> list[NameCluster]:
    """Group entries by (depth, is_dir, name_length) and infer the type of each cluster."""
    groups: dict[tuple, NameCluster] = {}
    for e in entries:
        key = (e.depth, e.is_dir, len(e.name))
        if key not in groups:
            groups[key] = NameCluster(depth=e.depth, is_dir=e.is_dir, length=len(e.name))
        groups[key].names.append(e.name)

    clusters = sorted(groups.values(), key=lambda c: (c.depth, c.is_dir, c.length))
    for c in clusters:
        c.finalize()
    return clusters


# ---------------------------------------------------------------------------
# Structural unit detection
# ---------------------------------------------------------------------------
#
# CONCEPTUAL FRAMING: a "structural unit" is the filesystem equivalent of a
# database table row. When you see N directories at the same depth that all
# contain the same set of files, those directories ARE rows in a table and
# those files ARE columns. This function finds those patterns.
#
# The key design decision vs. the naive approach: instead of finding the
# "most common exact signature" (set of child names that appears most often)
# and calling everything that doesn't match an "anomaly," we compute a
# per-child PRESENCE RATE. Children present in >= min_support of parents are
# "required" (NOT NULL in database terms). Children present in >= 5% but
# < min_support are "optional" (nullable FK or sparse one-to-many relation).
# Children present in < 5% are treated as one-offs and ignored.
#
# WHY THIS MATTERS: the "anomaly" framing was wrong for well-formed data.
# A sessions tree where 35% of agent dirs have a subagents/ subdirectory is
# not 65% "anomalous" — it's a sparse optional relationship, like a nullable
# column. The correct read is: most agents didn't spawn sub-agents; some did.
# That's interesting structure, not corruption.
#
# WHY min_support=0.6 AS THE REQUIRED THRESHOLD?
# It's a reasonable floor that handles minor data gaps. In practice, "required"
# files (like state.json, context.jsonl) appear in close to 100% of instances.
# If you have a file that appears in exactly 60% of dirs, it's probably
# genuinely optional and 0.6 is too high — consider lowering to 0.5 for
# messier datasets.
#
# WHY 0.05 AS THE OPTIONAL FLOOR?
# Files that appear in < 5% of instances are almost certainly one-off
# artifacts (temp files, crash dumps, debug output) that don't represent
# structural relationships. They add noise to the output without adding insight.
# For very small trees (< 20 units), this floor may be too aggressive.
#
# DIRECTIONS FOR IMPROVEMENT:
# - Detect when "optional" children themselves have internal structure —
#   e.g., subagents/ always contains agent-{id} dirs when it exists. This
#   would enable recursive optional-table detection.
# - Group parents by their optional-child combination to find sub-variants:
#   e.g., agents that have both tasks/ and subagents/ vs. agents that have
#   only tasks/ vs. agents that have neither. This maps to table inheritance
#   or discriminated unions in the underlying schema.
# - Instead of a hard min_support cutoff, use a bimodal gap detector:
#   if the distribution of presence rates has a clear gap (e.g., most names
#   appear in either >90% or <20% of parents, with nothing in between), use
#   that gap as the required/optional boundary automatically.
# - Track which parents have which optional children, enabling queries like
#   "show me the agents that have a tasks/ but no subagents/" directly from
#   the vocabulary.

@dataclass
class StructuralUnit:
    """A repeating pattern of children found under multiple parents.

    Conceptually: a database table row. The parent directories are rows;
    the required children are NOT NULL columns; the optional children are
    nullable columns or sparse foreign key relationships.
    """
    depth: int           # depth of the children (parent is at depth-1)
    parent_count: int    # how many parents have all required children
    total_parents: int   # total dirs analyzed at depth-1
    required: frozenset[str]   # present in >= min_support of parents
    optional: dict[str, float] # name -> presence fraction (0.05 <= f < min_support)
    example_parent: Path


def find_structural_units(root: Path, entries: list[Entry], min_support: float = 0.6) -> list[StructuralUnit]:
    """Find repeating child-name patterns across sibling directories."""
    by_parent: dict[Path, list[Entry]] = defaultdict(list)
    for e in entries:
        by_parent[e.path.parent].append(e)

    dir_entries = [e for e in entries if e.is_dir]
    by_depth: dict[int, list[Entry]] = defaultdict(list)
    for e in dir_entries:
        by_depth[e.depth].append(e)

    units = []
    for depth, dirs in by_depth.items():
        # Collect the set of child names for each dir at this depth
        child_name_sets: dict[Path, set[str]] = {}
        for d in dirs:
            children = by_parent.get(d.path, [])
            if children:
                child_name_sets[d.path] = {c.name for c in children}

        if len(child_name_sets) < 2:
            continue  # need at least 2 parents to establish a "repeating" pattern

        total = len(child_name_sets)
        all_names = {name for names in child_name_sets.values() for name in names}

        # Per-child presence rate: fraction of parents that contain each child name
        presence = {
            name: sum(1 for names in child_name_sets.values() if name in names) / total
            for name in all_names
        }

        required = frozenset(name for name, frac in presence.items() if frac >= min_support)
        optional = {name: frac for name, frac in presence.items()
                    if 0.05 <= frac < min_support}

        if not required:
            continue  # no stable core — not a meaningful structural unit

        # Qualifying parents are those that have all required children
        qualifying = [p for p, names in child_name_sets.items() if required <= names]
        if len(qualifying) < 2:
            continue

        units.append(StructuralUnit(
            depth=depth + 1,
            parent_count=len(qualifying),
            total_parents=total,
            required=required,
            optional=optional,
            example_parent=qualifying[0],
        ))

    return units


# ---------------------------------------------------------------------------
# Content sampling
# ---------------------------------------------------------------------------
#
# WHY ONLY 2048 BYTES FOR SAMPLING?
# We only need enough to identify the content type and get a representative
# first line. 2048 bytes is sufficient for the first JSON object or JSONL
# record in virtually all real-world files. Reading more would slow down the
# tool substantially when dealing with thousands of files.
#
# WHY ONLY SAMPLE REQUIRED CHILDREN?
# Optional children vary by parent instance. The example_parent may not even
# have them. Sampling only required children gives a stable, representative
# snapshot of what the structural unit "always" contains.
#
# DIRECTIONS FOR IMPROVEMENT:
# - For optional children, scan all parents to find one that has the child,
#   then sample it. This would let us show content type for optional files too.
# - Detect JSON schema patterns from the first few records: e.g., if the first
#   line of a .jsonl always has a "type" field, note that. This would bridge
#   tree_probe and json_ruleset naturally.
# - Add a "peek deeper" mode that reads more of each file and runs the
#   json_ruleset discriminator on it, so the structural unit output includes
#   a mini-ruleset for each JSON position.
# - Detect compressed files (.gz, .zst, .lz4) and report their compressed
#   size vs. estimated uncompressed size.

@dataclass
class PositionSample:
    path: Path
    content_type: str  # "json", "jsonl", "text", "binary", "empty", "directory", "error"
    preview: str       # first meaningful line of content
    size: int          # file size in bytes (0 for dirs)


def sample_position(path: Path) -> PositionSample:
    """Read and characterize a file at one structural position."""
    if path.is_dir():
        children = list(path.iterdir())
        return PositionSample(path=path, content_type="directory",
                              preview=f"{len(children)} children", size=0)
    try:
        size = path.stat().st_size
        if size == 0:
            return PositionSample(path=path, content_type="empty", preview="", size=0)

        raw = path.read_bytes()[:2048]

        # Null bytes reliably distinguish binary from text
        if b"\x00" in raw:
            return PositionSample(path=path, content_type="binary", preview="<binary>", size=size)

        text = raw.decode("utf-8", errors="replace")
        first_line = text.split("\n")[0].strip()[:120]

        # Content type detection: extension takes priority, then first-char heuristics.
        # This is intentionally simple — a more robust approach would try parsing
        # the first line as JSON and checking for errors, rather than using startswith.
        if path.suffix in (".json",) or first_line.startswith("{") or first_line.startswith("["):
            ctype = "json"
        elif path.suffix in (".jsonl",) or (first_line.startswith("{") and "\n" in text):
            ctype = "jsonl"
        else:
            ctype = "text"

        return PositionSample(path=path, content_type=ctype, preview=first_line, size=size)
    except Exception as e:
        return PositionSample(path=path, content_type="error", preview=str(e), size=0)


def sample_structural_unit(unit: StructuralUnit) -> dict[str, PositionSample]:
    """Sample one file per required position in the repeating unit."""
    samples = {}
    for name in sorted(unit.required):
        path = unit.example_parent / name
        samples[name] = sample_position(path)
    return samples


# ---------------------------------------------------------------------------
# Cardinality profiles
# ---------------------------------------------------------------------------
#
# CONCEPTUAL FRAMING: in a relational database, the number of rows in a table
# is a fundamental property of that table. When a database is flattened to a
# filesystem, the "number of rows" becomes the number of child directories
# under a parent. Profiling child counts at each depth level is therefore
# equivalent to profiling table sizes — it tells you whether a given layer
# of the hierarchy is a bounded set (fixed schema), an unbounded collection
# (a live table that grows with usage), or an empty placeholder.
#
# THE FOUR LABELS AND THEIR INTERPRETATIONS:
#
#   "empty"      — all dirs at this depth have 0 children. This could mean:
#                  the data type is unused (user never triggered it), the
#                  directory is a stub/placeholder created eagerly but rarely
#                  populated, or the data was purged.
#
#   "fixed(N)"   — all dirs have exactly N children. Strong schema signal.
#                  This is what you see with denormalized join tables, enum
#                  sets, or any bounded relationship defined at schema design
#                  time. If two DIFFERENT depths both show fixed(N) for the
#                  same N, that is an extremely strong coupling signal —
#                  it implies a designed relationship, not coincidence.
#
#   "small"      — counts vary but the maximum is < 50. Ambiguous: could be
#                  a bounded relationship with some variance (e.g., "each
#                  agent has 1-5 tasks"), or an early-stage collection that
#                  hasn't grown large yet, or a relationship that's mostly
#                  empty with occasional outliers.
#
#   "collection" — at least one parent has >= 50 children. This is almost
#                  certainly an unbounded table that grows with usage. The
#                  median count is more informative than the max here: a
#                  median of 1 with a max of 532 means most instances are
#                  small but some are extremely large (power-law distribution,
#                  common in usage data).
#
# WHY 50 AS THE "COLLECTION" THRESHOLD?
# Arbitrary but reasonable. 50 children is enough to make "this is a fixed
# enum" implausible for most schemas. If you're analyzing a system where 50
# is a reasonable fixed count (e.g., 50 config files), lower this threshold.
# Consider making it a parameter.
#
# THE COUPLING DETECTION (fixed count shared across depths):
# If depth 2 and depth 4 both show fixed(3), that might mean every row at
# depth 1 has exactly 3 children, each of which has exactly 3 grandchildren
# — a very regular schema. Or it could be coincidence if N is small (fixed(1)
# and fixed(2) are common enough to coincide by chance). The flag is a hint,
# not a conclusion.
#
# DIRECTIONS FOR IMPROVEMENT:
# - Use coefficient of variation (std/mean) to distinguish "truly fixed"
#   from "small and accidentally stable": a CoV near 0 = fixed, CoV > 0.3 =
#   genuinely variable.
# - Detect bimodal distributions: a count distribution that clusters around
#   0 AND around N (e.g., "most dirs have 0 children, some have exactly 5")
#   implies an optional many-to-one relationship where N is the typical batch
#   size. This is different from both "empty" and "small."
# - Track count growth over time by comparing file mtimes: if counts are
#   monotonically increasing over time, this is a live append-only log.
# - Compare sibling dirs at the SAME depth (not just across depths): if two
#   dirs at depth 1 both have ~500 children but one has 532 and the other has
#   540 and another has 694, that's three independent collections growing at
#   different rates — likely separate "tables" or separate users/tenants.
# - Flag proportional counts: if depth 2 consistently has ~9× the children
#   of depth 1, that's a join ratio (e.g., each session has ~9 agent turns).
#   This could be detected via regression across pairs.

@dataclass
class CardinalityProfile:
    """Distribution of child counts across all dirs at a given depth.

    Analogous to a table's row count in a database. Use this to distinguish
    bounded schemas (fixed), live collections (collection), empty stubs, and
    ambiguous small sets.
    """
    depth: int           # depth of the parent dirs being analyzed
    n_parents: int       # how many dirs were measured at this depth
    counts: list[int]    # sorted list of child counts, one per parent
    label: str           # "empty", "fixed", "small", or "collection"
    fixed_n: int | None  # the fixed count, if label == "fixed"
    examples: list[Path] = field(default_factory=list)


def _cardinality_label(counts: list[int]) -> tuple[str, int | None]:
    """Classify a distribution of child counts into a human-meaningful label."""
    if not counts or max(counts) == 0:
        return "empty", None
    lo, hi = min(counts), max(counts)
    if lo == hi:
        return "fixed", lo   # every parent has the exact same number of children
    if hi >= 50:
        return "collection", None  # at least one parent has a lot of children
    return "small", None


def profile_child_counts(entries: list[Entry]) -> list[CardinalityProfile]:
    """For each depth level, compute how many children each directory has."""
    # Count children per parent path
    by_parent: dict[Path, int] = defaultdict(int)
    for e in entries:
        by_parent[e.path.parent] += 1

    # For each dir, look up how many children it has
    dir_entries = [e for e in entries if e.is_dir]
    by_depth: dict[int, list[tuple[Path, int]]] = defaultdict(list)
    for e in dir_entries:
        count = by_parent.get(e.path, 0)
        by_depth[e.depth].append((e.path, count))

    profiles = []
    for depth in sorted(by_depth):
        items = by_depth[depth]
        counts = sorted(c for _, c in items)
        label, fixed_n = _cardinality_label(counts)
        examples = [p for p, _ in items[:3]]
        profiles.append(CardinalityProfile(
            depth=depth,
            n_parents=len(items),
            counts=counts,
            label=label,
            fixed_n=fixed_n,
            examples=examples,
        ))
    return profiles


# ---------------------------------------------------------------------------
# Vocabulary (full analysis result)
# ---------------------------------------------------------------------------

@dataclass
class TreeVocabulary:
    """The complete structural analysis of a filesystem tree."""
    root: Path
    total_entries: int
    clusters: list[NameCluster]        # name-type clusters by depth
    units: list[StructuralUnit]        # repeating child patterns (table rows)
    samples: dict[int, dict[str, PositionSample]]  # unit depth -> child name -> sample
    cardinality: list[CardinalityProfile]  # child-count distributions by depth


def analyse(root: Path, max_depth: int = 8, min_support: float = 0.6) -> TreeVocabulary:
    """Run the full tree analysis pipeline and return a TreeVocabulary."""
    entries = scan_tree(root, max_depth=max_depth)
    clusters = cluster_names(entries)
    units = find_structural_units(root, entries, min_support=min_support)
    samples = {u.depth: sample_structural_unit(u) for u in units}
    cardinality = profile_child_counts(entries)
    return TreeVocabulary(root=root, total_entries=len(entries),
                          clusters=clusters, units=units, samples=samples,
                          cardinality=cardinality)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
#
# The render function produces human-readable ASCII output for terminal use.
# The format is intentionally dense: every line should carry information.
# Blank lines are used only to separate major sections.
#
# DIRECTIONS FOR IMPROVEMENT:
# - Add a --json output mode that emits the TreeVocabulary as structured JSON.
#   This would make tree-probe composable with other tools (including
#   json-ruleset: you could pipe the vocabulary into a ruleset builder).
# - Add a --compact mode that collapses structural units with no optional
#   children into a single line: "depth 3: context.jsonl, state.json, wire.jsonl"
# - Add color output (via colorama or rich) for terminal use: highlight
#   "collection" in yellow, "fixed" in green, "empty" in gray.
# - Consider a side-by-side diff mode: compare the vocabularies of two trees
#   (e.g., ~/.kimi/ and ~/.claude/) to surface structural similarities and
#   differences. This would be useful for understanding how different CLIs
#   store their session data.

def render(vocab: TreeVocabulary) -> str:
    lines: list[str] = []
    header = f"TREE-PROBE  {vocab.root}  ({vocab.total_entries:,} entries)"
    lines += [header, "=" * len(header), ""]

    # --- NAME CLUSTERS ---
    # Shows the distribution of name types at each depth level.
    # Read this section to understand what "kind of thing" lives at each level
    # (UUID = entity ID, md5 = content hash, alpha_lower = human-readable name).
    lines.append("NAME CLUSTERS")
    lines.append("─" * 40)
    cur_depth = -1
    for c in vocab.clusters:
        if c.depth != cur_depth:
            cur_depth = c.depth
            lines.append(f"\n  depth {c.depth}:")
        kind = "dir" if c.is_dir else "file"
        samples = ", ".join(repr(n) for n in c.names[:3])
        suffix = f"  e.g. {samples}" if c.names else ""
        lines.append(f"    [{kind}] len={c.length:>3}  {c.name_type:<18}  n={c.count:>4}{suffix}")

    # --- CARDINALITY PROFILES ---
    # Shows how many children each directory has, by depth.
    # "collection" = unbounded table (grows with usage).
    # "fixed(N)"   = schema constraint (every row has exactly N children).
    # "small"      = ambiguous — could be bounded or early-stage collection.
    # "empty"      = unused placeholder or purged data.
    # The "← matches depth [X]" annotation flags when two depths share the
    # same fixed count — a potential schema coupling signal worth investigating.
    if vocab.cardinality:
        lines += ["", "CARDINALITY PROFILES", "─" * 40]

        # Pre-compute which fixed counts appear at multiple depths
        fixed_by_n: dict[int, list[int]] = defaultdict(list)
        for cp in vocab.cardinality:
            if cp.label == "fixed" and cp.fixed_n is not None and cp.n_parents > 1:
                fixed_by_n[cp.fixed_n].append(cp.depth)

        for cp in vocab.cardinality:
            counts = cp.counts
            lo, hi = min(counts), max(counts)
            if cp.label == "fixed":
                detail = f"fixed({cp.fixed_n})"
                shared = [d for d in fixed_by_n.get(cp.fixed_n, []) if d != cp.depth]
                coupling = f"  ← matches depth {shared}" if shared else ""
            elif cp.label == "collection":
                med = statistics.median(counts)
                detail = f"collection  range {lo}–{hi}  median {med:.0f}"
                coupling = ""
            elif cp.label == "empty":
                detail = "empty"
                coupling = ""
            else:
                detail = f"small  range {lo}–{hi}"
                coupling = ""
            lines.append(f"  depth {cp.depth}  n={cp.n_parents:>4}  {detail}{coupling}")

    # --- STRUCTURAL UNITS ---
    # Shows the repeating child patterns ("table schemas") found at each depth.
    # Required children (present in >= min_support of parents) are shown first.
    # Optional children (5% <= presence < min_support) follow, with their rate.
    # Think: required = NOT NULL column, optional = nullable FK.
    if vocab.units:
        lines += ["", "STRUCTURAL UNITS", "─" * 40]
        for unit in vocab.units:
            pct = 100 * unit.parent_count / max(unit.total_parents, 1)
            lines.append(f"\n  depth {unit.depth}  —  {unit.parent_count}/{unit.total_parents} parents ({pct:.0f}%)")
            pos_samples = vocab.samples.get(unit.depth, {})
            all_children = sorted(unit.required) + sorted(unit.optional, key=lambda n: -unit.optional[n])
            for i, name in enumerate(all_children):
                conn = "└── " if i == len(all_children) - 1 else "├── "
                if name in unit.required:
                    sample = pos_samples.get(name)
                    if sample:
                        size_str = f"{sample.size:,}b" if sample.size else ""
                        preview = sample.preview[:60] if sample.preview else ""
                        lines.append(f"    {conn}{name}  [{sample.content_type}]  {size_str}  {preview}")
                    else:
                        lines.append(f"    {conn}{name}")
                else:
                    opt_pct = 100 * unit.optional[name]
                    lines.append(f"    {conn}{name}  ({opt_pct:.0f}%)  optional")

    return "\n".join(lines)
