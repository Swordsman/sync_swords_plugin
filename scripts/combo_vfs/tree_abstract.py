#!/usr/bin/env python3
"""
tree-abstract.py — produce an intelligently abstracted structural map of a
directory tree.

Detects groups of similarly-named files or folders (UUIDs, hashes, timestamps,
etc.) and collapses them into a single abstracted entry.

Grouping key is (pattern_label, extension, kind):
    * pattern_label is matched against the *stem* (name minus extension)
    * extension is the lowercased suffix (or "" for none / for dirs)
    * kind is "dir" or "file"

So `.txt` and `.md` hex-named files never merge, even if both are HEX.

Stdlib only.
"""

import os
import re
import sys
import argparse
from pathlib import Path
from collections import Counter

# --------------------------------------------------------------------------
# Pattern detection
#
# Order matters: more specific patterns must come before more general ones.
# Each entry: (label, compiled regex). The first match wins.
#
# Patterns are matched against the STEM (filename minus extension) only.
# --------------------------------------------------------------------------

_VER_SUFFIX = r'(?:@v\d+)'

PATTERNS = [
    # UUID, with optional @vN suffix
    ("UUID@vN", re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        + _VER_SUFFIX + r'$', re.I)),
    ("UUID", re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)),

    # Hash families with optional @vN suffix.
    ("SHA256@vN", re.compile(r'^[0-9a-f]{64}' + _VER_SUFFIX + r'$', re.I)),
    ("SHA256",    re.compile(r'^[0-9a-f]{64}$', re.I)),
    ("SHA1@vN",   re.compile(r'^[0-9a-f]{40}' + _VER_SUFFIX + r'$', re.I)),
    ("SHA1",      re.compile(r'^[0-9a-f]{40}$', re.I)),
    ("MD5@vN",    re.compile(r'^[0-9a-f]{32}' + _VER_SUFFIX + r'$', re.I)),
    ("MD5",       re.compile(r'^[0-9a-f]{32}$', re.I)),
    ("HEX@vN",    re.compile(r'^[0-9a-f]{7,16}' + _VER_SUFFIX + r'$', re.I)),
    ("HEX",       re.compile(r'^[0-9a-f]{7,16}$', re.I)),

    # Date / timestamp prefixes (e.g. 2026-04-28-foo, 20260428T120000-bar)
    ("TSDATE", re.compile(r'^(\d{4}-\d{2}-\d{2}|\d{8})[-_T].*$')),
    ("TSDATE_BARE", re.compile(r'^(\d{4}-\d{2}-\d{2}|\d{8})$')),

    # Pure-numeric IDs
    ("EPOCH", re.compile(r'^\d{10,13}$')),
    ("NUMID", re.compile(r'^\d{6,}$')),
]

SKIP_DIRS = {'.git'}

# Cap for how many `sometimes` items we list explicitly before truncating.
SOMETIMES_LIMIT = 8


def split_stem_ext(name: str):
    """
    Split `name` into (stem, ext_lower). Multi-part extensions like .tar.gz
    are kept whole — extension is everything from the FIRST dot onwards
    (excluding a leading dot, which means the file is a dotfile with no ext).
    """
    if not name:
        return name, ""
    # Leading-dot files (e.g. ".bashrc", ".gitignore") — treat as no extension.
    if name.startswith("."):
        # But ".tar.gz" alone shouldn't happen as a real filename; if a dotfile
        # has further dots (e.g. ".config.json"), treat from first non-leading dot.
        rest = name[1:]
        if "." not in rest:
            return name, ""
        idx = rest.index(".")
        stem = "." + rest[:idx]
        ext = rest[idx:].lower()
        return stem, ext
    if "." not in name:
        return name, ""
    idx = name.index(".")
    stem = name[:idx]
    ext = name[idx:].lower()
    return stem, ext


def detect_pattern_for_stem(stem: str):
    """Return the pattern label matching `stem`, or None."""
    for label, rx in PATTERNS:
        if rx.match(stem):
            return label
    return None


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------

def safe_scandir(path):
    """os.scandir wrapper that returns a list or None on PermissionError."""
    try:
        with os.scandir(path) as it:
            return list(it)
    except (PermissionError, OSError):
        return None


def is_real_dir(entry):
    """True if entry is a directory and not a symlink."""
    try:
        if entry.is_symlink():
            return False
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


# --------------------------------------------------------------------------
# Abstraction grouping
# --------------------------------------------------------------------------

def group_entries(entries, threshold):
    """
    Partition `entries` into:
      * groups: dict[(label, ext, kind)] -> list[DirEntry]   (for groups >= threshold)
      * leftover: list[DirEntry]

    Grouping key:
      - label: pattern matched against STEM
      - ext: lowercased extension (e.g. ".txt", ".tar.gz") or "" for no ext / dirs
      - kind: "dir" or "file"
    """
    buckets = {}  # (label, ext, kind) -> list[entry]
    unmatched = []

    for e in entries:
        kind = "dir" if is_real_dir(e) else "file"
        if kind == "dir":
            # Dirs: pattern-match the whole name; extension forced to "".
            label = detect_pattern_for_stem(e.name)
            ext = ""
        else:
            stem, ext = split_stem_ext(e.name)
            label = detect_pattern_for_stem(stem)

        if label is None:
            unmatched.append(e)
            continue
        buckets.setdefault((label, ext, kind), []).append(e)

    groups = {}
    leftover = list(unmatched)
    for key, members in buckets.items():
        if len(members) >= threshold:
            groups[key] = members
        else:
            leftover.extend(members)

    return groups, leftover


# --------------------------------------------------------------------------
# Template-pattern grouping (second pass for names with embedded variable segments)
# --------------------------------------------------------------------------

_TEMPLATE_SUBS = [
    (re.compile(r'\d{4}-\d{2}-\d{2}[T_]\d{2}[:\-]\d{2}[:\-]\d{2}(?:[_\.]\d+)?'), '{ts}'),
    (re.compile(r'\d{10,13}'), '{N}'),
    (re.compile(r'\d{6,}'), '{N}'),
]


def make_template(name: str):
    result = name
    for rx, placeholder in _TEMPLATE_SUBS:
        result = rx.sub(placeholder, result)
    return result if result != name else None


def group_by_template(entries, threshold):
    buckets = {}
    unmatched = []
    for e in entries:
        kind = "dir" if is_real_dir(e) else "file"
        tmpl = make_template(e.name)
        if tmpl is None:
            unmatched.append(e)
            continue
        buckets.setdefault((tmpl, kind), []).append(e)

    template_groups = {}
    still_leftover = list(unmatched)
    for key, members in buckets.items():
        if len(members) >= threshold:
            template_groups[key] = members
        else:
            still_leftover.extend(members)
    return template_groups, still_leftover


def child_name_stats(instance_paths):
    """
    For each path in `instance_paths` (assumed to be directories), tally the
    names of their immediate children. Returns (always, usually, sometimes)
    where each is a list of (name, is_dir_majority) sorted by frequency desc
    then name asc.
    """
    total = len(instance_paths)
    name_counts = Counter()
    name_dir_votes = Counter()
    name_seen = Counter()

    for inst in instance_paths:
        entries = safe_scandir(inst)
        if entries is None:
            continue
        seen_here = set()
        for e in entries:
            if e.name in seen_here:
                continue
            seen_here.add(e.name)
            name_counts[e.name] += 1
            name_seen[e.name] += 1
            if is_real_dir(e):
                name_dir_votes[e.name] += 1

    always, usually, sometimes = [], [], []
    for name, count in sorted(name_counts.items(), key=lambda x: (-x[1], x[0].lower())):
        ratio = count / total if total else 0
        is_dir_majority = name_dir_votes[name] >= (name_seen[name] / 2)
        bucket_entry = (name, is_dir_majority)
        if ratio >= 1.0:
            always.append(bucket_entry)
        elif ratio >= 0.5:
            usually.append(bucket_entry)
        else:
            sometimes.append(bucket_entry)
    return always, usually, sometimes


def format_name_list(items, abstract_patterns=True):
    """
    Format a list of (name, is_dir) tuples as 'a/, b, c/' style.

    If `abstract_patterns` is True, runs of names sharing the same
    (pattern, ext, kind) get collapsed to '[LABEL × N <kindword>]'.
    """
    if not abstract_patterns:
        return ", ".join(name + ("/" if is_dir else "") for name, is_dir in items)

    pat_counts = Counter()  # (label, ext, is_dir) -> count
    for name, is_dir in items:
        if is_dir:
            label = detect_pattern_for_stem(name)
            ext = ""
        else:
            stem, ext = split_stem_ext(name)
            label = detect_pattern_for_stem(stem)
        if label is not None:
            pat_counts[(label, ext, is_dir)] += 1

    collapse = {key for key, c in pat_counts.items() if c >= 2}

    parts = []
    emitted_collapse = set()
    for name, is_dir in items:
        if is_dir:
            label = detect_pattern_for_stem(name)
            ext = ""
        else:
            stem, ext = split_stem_ext(name)
            label = detect_pattern_for_stem(stem)
        key = (label, ext, is_dir) if label else None
        if key is not None and key in collapse:
            if key in emitted_collapse:
                continue
            emitted_collapse.add(key)
            count = pat_counts[key]
            if is_dir:
                kind_word = "dirs"
                parts.append(f"[{label} × {count} {kind_word}]")
            else:
                kind_word = "files"
                ext_word = f"{ext} " if ext else ""
                parts.append(f"[{label} × {count} {ext_word}{kind_word}]")
        else:
            parts.append(name + ("/" if is_dir else ""))
    return ", ".join(parts)


def pick_representative(instance_paths):
    """Pick the instance with the most children (best example)."""
    best = None
    best_count = -1
    for inst in instance_paths:
        entries = safe_scandir(inst)
        if entries is None:
            continue
        if len(entries) > best_count:
            best_count = len(entries)
            best = inst
    return best


# --------------------------------------------------------------------------
# Tree rendering
# --------------------------------------------------------------------------

def render_template_group(tmpl, kind, members, prefix, child_prefix, connector, args, depth):
    count = len(members)
    kind_word = "dirs" if kind == "dir" else "files"
    print(f"{prefix}{connector}[{tmpl} × {count} {kind_word}]")
    if kind == "file":
        return
    instance_paths = [Path(e.path) for e in members]
    rep = pick_representative(instance_paths)
    if rep is not None and (args.max_depth is None or depth + 1 <= args.max_depth):
        print(f"{child_prefix}└── [representative: {rep.name}]")
        render_dir_contents(str(rep), child_prefix + "    ", args, depth + 1)


def render_dir_contents(path, prefix, args, depth):
    """Render the contents of directory `path`, applying abstraction."""
    if args.max_depth is not None and depth > args.max_depth:
        return

    entries = safe_scandir(path)
    if entries is None:
        print(f"{prefix}[permission denied]")
        return
    if not entries:
        return

    if args.no_abstract:
        groups = {}
        template_groups = {}
        leftover = list(entries)
    else:
        groups, leftover = group_entries(entries, args.threshold)
        template_groups, leftover = group_by_template(leftover, args.threshold)

    # Build a unified, sorted list of items to render.
    items = []
    for e in leftover:
        items.append(("entry", e))
    for (label, ext, kind), members in groups.items():
        items.append(("group", label, ext, kind, members))
    for (tmpl, kind), members in template_groups.items():
        items.append(("tmpl_group", tmpl, kind, members))

    def item_sort_key(it):
        if it[0] == "entry":
            e = it[1]
            return (0 if is_real_dir(e) else 1, e.name.lower())
        elif it[0] == "group":
            _tag, label, ext, kind, _members = it
            return (0 if kind == "dir" else 1, f"[{label}{ext}]".lower())
        else:  # tmpl_group
            _tag, tmpl, kind, _members = it
            return (0 if kind == "dir" else 1, tmpl.lower())

    items.sort(key=item_sort_key)

    n = len(items)
    for i, item in enumerate(items):
        is_last = (i == n - 1)
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        if item[0] == "entry":
            render_entry(item[1], prefix, child_prefix, connector, args, depth)
        elif item[0] == "group":
            _tag, label, ext, kind, members = item
            render_group(label, ext, kind, members, prefix, child_prefix, connector, args, depth)
        else:
            _tag, tmpl, kind, members = item
            render_template_group(tmpl, kind, members, prefix, child_prefix, connector, args, depth)


def render_entry(entry, prefix, child_prefix, connector, args, depth):
    """Render a single concrete entry (file/dir/symlink)."""
    name = entry.name

    # Symlink: show target, do not follow
    try:
        if entry.is_symlink():
            try:
                target = os.readlink(entry.path)
            except OSError:
                target = "?"
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            suffix = "/" if is_dir else ""
            print(f"{prefix}{connector}{name}{suffix} -> {target}")
            return
    except OSError:
        pass

    if is_real_dir(entry):
        if name in SKIP_DIRS:
            print(f"{prefix}{connector}{name}/ [skipped]")
            return
        print(f"{prefix}{connector}{name}/")
        if args.max_depth is None or depth + 1 <= args.max_depth:
            render_dir_contents(entry.path, child_prefix, args, depth + 1)
        # If max-depth exceeded: stop silently (no [...] indicator).
    else:
        print(f"{prefix}{connector}{name}")


def render_group(label, ext, kind, members, prefix, child_prefix, connector, args, depth):
    """Render an abstracted group of entries sharing (label, ext, kind)."""
    count = len(members)
    if kind == "dir":
        kind_word = "dirs"
        header = f"[{label} × {count} {kind_word}]"
    else:
        kind_word = "files"
        ext_word = f"{ext} " if ext else ""
        header = f"[{label} × {count} {ext_word}{kind_word}]"
    print(f"{prefix}{connector}{header}")

    if kind == "file":
        # Files have no children — header alone is enough.
        return

    # Directory group: child-name stats + representative subtree.
    instance_paths = [Path(e.path) for e in members]
    always, usually, sometimes = child_name_stats(instance_paths)

    sublines = []

    if always:
        sublines.append(("static", f"always:    {format_name_list(always)}"))
    if usually:
        sublines.append(("static", f"usually:   {format_name_list(usually)}"))
    if sometimes:
        if len(sometimes) > SOMETIMES_LIMIT:
            shown = sometimes[:SOMETIMES_LIMIT]
            extra = len(sometimes) - SOMETIMES_LIMIT
            text = f"sometimes: {format_name_list(shown)}  (and {extra} more)"
        else:
            text = f"sometimes: {format_name_list(sometimes)}"
        sublines.append(("static", text))

    rep = pick_representative(instance_paths)
    rep_allowed = (
        rep is not None
        and (args.max_depth is None or depth + 1 <= args.max_depth)
    )
    if rep_allowed:
        sublines.append(("rep", rep))
    elif rep is not None:
        sublines.append(("static", f"[representative: {rep.name}]  (max-depth reached)"))

    if not sublines:
        print(f"{child_prefix}└── (no inspectable contents)")
        return

    n = len(sublines)
    for i, sub in enumerate(sublines):
        is_last = (i == n - 1)
        sub_connector = "└── " if is_last else "├── "
        sub_child_prefix = child_prefix + ("    " if is_last else "│   ")

        if sub[0] == "static":
            print(f"{child_prefix}{sub_connector}{sub[1]}")
        else:  # "rep"
            rep_path = sub[1]
            print(f"{child_prefix}{sub_connector}[representative: {rep_path.name}]")
            render_dir_contents(str(rep_path), sub_child_prefix, args, depth + 1)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Crawl a directory tree and produce an intelligently "
                    "abstracted structural map (UUID/hash/timestamp folders "
                    "and files get collapsed, grouped by pattern + extension)."
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="Root directory to crawl (default: CWD)")
    parser.add_argument("--threshold", type=int, default=3, metavar="N",
                        help="Minimum siblings sharing a (pattern, ext, kind) "
                             "to trigger abstraction (default: 3)")
    parser.add_argument("--max-depth", type=int, default=None, metavar="D",
                        help="Maximum recursion depth (default: unlimited)")
    parser.add_argument("--no-abstract", action="store_true",
                        help="Disable abstraction; show raw tree")
    args = parser.parse_args()

    root = Path(args.path).expanduser()
    try:
        root = root.resolve()
    except OSError as ex:
        print(f"Error resolving path: {ex}", file=sys.stderr)
        sys.exit(1)

    if not root.exists():
        print(f"Error: path does not exist: {root}", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    print(f"{root}/")
    render_dir_contents(str(root), "", args, depth=1)


if __name__ == "__main__":
    main()
