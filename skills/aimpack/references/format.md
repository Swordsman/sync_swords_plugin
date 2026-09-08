MIME parts in order: meta, instructions, files, diffs, refs, checkpoints.

Part types: `text/x-aimpack-meta; role=preamble|readme|manifest`, `application/x-aimpack-instructions` (S-expr), `text/plain` with `Content-Disposition: attachment; filename="path"` (file), `text/x-diff` (patch), `application/x-aimpack-ref` (external container), `application/x-aimpack-checkpoint`.

Global headers: `X-Aimpack-Container-Id` (uuid), `X-Aimpack-Parent` (fork source uuid), `X-Aimpack-Fork-Point` (sequence at fork), `X-Aimpack-Version`, `X-Aimpack-Container-Checksum-{CRC32,MD5,SHA256}`.

Container digest: computed over the container text with every `X-Aimpack-Container-Checksum-*` header line removed, then appended to the global header block. A digest stored inside what it describes cannot cover itself — writing it would change the bytes it recorded — so the canonical form is defined by textual deletion of those lines, and rewriting commands restamp.

Diff headers: `X-Aimpack-Patch-Direction` (forward|inverse), `X-Aimpack-Sequence` (global, gaps legal post-squash), `X-Aimpack-Patch-Target` (filename), `X-Aimpack-Patch-Message`, `X-Aimpack-Author`, `X-Aimpack-Patch-Timestamp`, `X-Aimpack-Squashed-Range` (FROM:TO if squashed).

File headers: `X-Aimpack-Checksum-{CRC32,MD5,SHA256}`, `X-Aimpack-Modified`, `X-Aimpack-Author`, `X-Aimpack-Patch-Error` (set on failed patch, file skipped).

Ref headers: `X-Aimpack-Ref-Type` (parent|dependency|merge-source), `X-Aimpack-Ref-Container-Id`.

Behavioral semantics: file-part checksums describe that part's own body, not the post-diff resolved content. checksum fail → continue, warn. Patch fail → skip file, tag `X-Aimpack-Patch-Error`, continue. Sequences global scope. Fork parents referenced by UUID, not embedded. `(par)` is fork-join: all branches complete, individual failure doesn't kill siblings.

## Invariants

These were violated in 1.0.0. Breaking any of them corrupts user data silently.

- **Binary files round-trip byte-exactly.** Non-UTF-8 files are base64-encoded with `Content-Transfer-Encoding: base64` and *decoded* on unpack. Checksums cover real file bytes, not base64 transport — otherwise validation passes on a corrupt file.
- **`---` and `+++` inside a hunk are content, not headers.** They are only file headers before the first `@@`. A file with a line starting with `--` is ordinary; treating it as a header eats the line.
- **Trailing-newline state survives the diff lifecycle.** `generate_diff` normalizes both sides to end with a newline, so the modified side's real state is recorded in `X-Aimpack-Patch-No-Final-Newline` and undone by `resolve_files`.
- **A diff whose target has no file part is an addition**, patched against empty. `compact` and `fork` must materialize file parts for those, or added files vanish on the next rewrite.
- **The container digest excludes itself.** `X-Aimpack-Container-Checksum-<ALG>` is computed over the container with those header lines removed, then stamped by appending. Every rewriting command restamps. Never compute the digest with the header already in the dict.
- **Part checksums describe the part body, not the resolved file.** After a forward diff, resolved content differs from the part body. Validating resolved bytes against a part header is a false alarm.
- **Boundaries are content-derived.** Shortest non-colliding prefix + random chars. Collision is a *prefix* relation: boundary `ab` is broken by `--abc`. `pack`/`fork` derive; `compact`/`squash`/`set-*` reissue after rewriting; `diff` refuses rather than corrupting.

Example:
```
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="aimpack-a1b2c3d4"
X-Aimpack-Container-Id: 550e8400-e29b-41d4-a716-446655440000

--aimpack-a1b2c3d4
Content-Type: text/x-aimpack-meta; role=preamble

This is an aimpack container (AI MimePack).
Spec: https://github.com/swordsman/aimpack

--aimpack-a1b2c3d4
Content-Type: application/x-aimpack-instructions

(task "review src/main.py for security issues")

--aimpack-a1b2c3d4
Content-Type: text/plain; charset=utf-8
Content-Disposition: attachment; filename="src/main.py"
Content-Transfer-Encoding: 8bit

print("hello")

--aimpack-a1b2c3d4
Content-Type: text/x-diff
X-Aimpack-Patch-Target: src/main.py
X-Aimpack-Sequence: 1
X-Aimpack-Patch-Direction: forward
X-Aimpack-Patch-Message: added greet function

--- a/src/main.py
+++ b/src/main.py
@@ -1 +1,3 @@
+def greet():
+    return "hello"
 print("hello")

--aimpack-a1b2c3d4--
```
