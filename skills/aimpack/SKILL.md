---
name: aimpack
description: "AI MimePack: munpack-compatible MIME containers for LLM workflows. Plaintext-readable file packaging with linear edit history (diff/compact/squash/fork), S-expression instruction support, and an extension system for custom content types. Use when packaging files for AI-to-AI transfer, when files must remain readable/editable in-place, or when orchestrating multi-agent pipelines via embedded instructions. Spec: https://github.com/swordsman/aimpack"
---

# aimpack

Standard MIME `multipart/mixed` containers optimized for AI cognitive ergonomics. Files stay plaintext-readable in place — no decompression, no representation swapping. Compatible with Linux `munpack`.

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/aimpack.py <command>` (or `python3 scripts/aimpack.py <command>` from the plugin root).

Commands: `pack <dir> -o out.aimpack [--timestamps] [--checksum sha256] [--author X] [--exclude pat] [--instructions sexpr] [--readme file] [--no-preamble] [--boundary tok] [--boundary-entropy N] [--parent id]`, `unpack <container> -o <dir>`, `diff <container> <dir_or_files> [-m msg] [--author X] [--no-new] [--base DIR] [--exclude pat]`, `compact <container>`, `squash <container> --range FROM:TO`, `log <container>`, `fork <container> -o branch.aimpack`, `verify <container> [-v]`, `set-instructions <container> <text-or-file>`, `set-readme <container> <text-or-file>`, `dedup <container_or_dir> [-m min-lines]`, `ext list|install|resolve|config`.

Default excludes: `.git`, `__pycache__`, `node_modules`, `.DS_Store`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `.venv`, `*.pyc`, `*.pyo`, `*.swp`, `*.swo`, `*.egg-info`.

Edit lifecycle: pack → diff (append, no rewrite; adds new files as well as edits) → compact (forwards applied to files, inverses stored one-to-one, full chain) → squash (opt-in, lossy) → fork (separate container, parent ref). File parts are always current post-compact. Inverse diffs are archaeology.

Boundaries are derived from container content: the shortest delimiter that cannot collide with any line, plus a few random characters. Pass `--boundary` to pin one explicitly — packing fails rather than corrupting if it collides. Use it when you need two packs to be byte-comparable.

`--checksum` records per-file checksums plus a whole-container digest; `verify` checks both without unpacking and exits non-zero on mismatch. The container digest is computed with its own `X-Aimpack-Container-Checksum-*` header lines removed — a hash stored inside what it describes cannot include itself — and every rewriting command restamps it. File-part checksums describe that part's body, not the post-diff resolved content.

Binary files are carried base64-encoded with `Content-Transfer-Encoding: base64` and restored byte-exactly on unpack; diffs are text-only and skip binary parts.

Read `references/format.md` for the wire format and headers. Read `references/dsl.md` when writing S-expression instructions, orchestration pipelines, or working with extensions.
