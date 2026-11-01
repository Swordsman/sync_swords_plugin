#!/usr/bin/env python3
"""Offload heavy work from Claude's context to DeepSeek.

Subcommands:
    bundle JOBDIR --task TASKFILE [FILES or GLOBS...]
    run JOBDIR [--model deepseek-v4-pro]
    wait JOBDIR [--poll 30] [--timeout SECONDS]
    apply JOBDIR --root REPO [--dry-run]
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

DEFAULT_MODEL = "deepseek-v4-pro"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

DEFAULT_TOKEN_MAX_TRIES = 50
INITIAL_TOKEN_LENGTH = 8
APPLY_MODES = ("all-or-nothing", "partial")


# ---------------------------------------------------------------------------
# marker helpers
# ---------------------------------------------------------------------------

def _section_marker(name: str, token: str) -> str:
    return f"==={name}-{token}===" if token else f"==={name}==="


def _marker(base: str, token: str) -> str:
    return f"{base}-{token}" if token else base


def _token_markers(token: str) -> list[str]:
    return [
        _section_marker("EDITS", token),
        _section_marker("DIGEST", token),
        _marker("<<<EDIT", token),
        _marker("<<<FIRST", token),
        _marker(">>>NEW", token),
        _marker(">>>END", token),
    ]


class MarkerCollisionError(RuntimeError):
    pass


def _generate_token(length: int = INITIAL_TOKEN_LENGTH) -> str:
    raw = os.urandom(16) + str(time.time()).encode("utf-8")
    token = hashlib.sha256(raw).hexdigest()
    while len(token) < length:
        token += hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token[:length]


def _find_marker_collision(
    texts: list[tuple[str, str]], token: str
) -> tuple[str, str] | None:
    for marker in _token_markers(token):
        for source, text in texts:
            if marker in text:
                return source, marker
    return None


def _choose_token(
    texts: list[tuple[str, str]], token_on_collision: str, max_tries: int
) -> str:
    if token_on_collision not in ("grow", "fail"):
        raise ValueError(
            f"invalid token_on_collision: {token_on_collision!r}"
        )

    plain_collision = _find_marker_collision(texts, "")
    if plain_collision is None:
        return ""

    if token_on_collision == "fail":
        source, marker = plain_collision
        raise MarkerCollisionError(
            f"marker {marker!r} found in {source!r}; "
            "plain markers cannot be used with --token-on-collision fail"
        )

    length = INITIAL_TOKEN_LENGTH
    failed = 0
    while True:
        token = _generate_token(length)
        collision = _find_marker_collision(texts, token)
        if collision is None:
            return token

        failed += 1
        if token_on_collision == "fail":
            source, marker = collision
            raise MarkerCollisionError(
                f"generated token marker {marker!r} collides "
                f"with content in {source!r}"
            )

        if failed >= max_tries:
            length += 1


def _build_response_format(token: str) -> str:
    edits = _section_marker("EDITS", token)
    digest = _section_marker("DIGEST", token)
    edit = _marker("<<<EDIT", token)
    first = _marker("<<<FIRST", token)
    new = _marker(">>>NEW", token)
    end = _marker(">>>END", token)

    return f"""===RESPONSE FORMAT===
Answer with exactly two sections.

{edits}
List the edits using the EXACT grammar below. Do not include anything else in this section.

{edit} path lines A-B
{first}
the exact original text of line A, without its number prefix
{new}
replacement lines (can be empty to delete A..B)
{end}

{edit} path insert-after A
{first}
the exact original text of line A, without its number prefix
{new}
replacement lines to insert after line A
{end}

For A=0, the file starts at the top and {first} must be empty.

{edit} path new
{new}
new file contents
{end}

Line numbers come from the numbered listing in the bundle. FIRST must copy line A exactly (we compare after stripping trailing whitespace). Never invent files that were not shown, except when the edit type is new.

{digest}
At most 15 short plain lines for the coordinator: what changed, what's left, anything needing a human.
"""


RESPONSE_FORMAT = _build_response_format("")


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------

def cmd_bundle(
    jobdir: str,
    taskfile: str,
    file_args: list[str],
    token_on_collision: str = "grow",
    max_tries: int = DEFAULT_TOKEN_MAX_TRIES,
) -> None:
    if token_on_collision not in ("grow", "fail"):
        raise ValueError(
            f"invalid token_on_collision: {token_on_collision!r}"
        )

    os.makedirs(jobdir, exist_ok=True)
    out_path = os.path.join(jobdir, "bundle.txt")

    with open(taskfile, "r", encoding="utf-8", errors="replace") as tf:
        task_text = tf.read()

    texts: list[tuple[str, str]] = [(taskfile, task_text)]
    entries: list[tuple[str, str, list[str], bool]] = []

    for arg in file_args:
        paths: list[str] = []
        if glob.has_magic(arg):
            matches = sorted(glob.glob(arg))
            if not matches:
                entries.append((arg, "", [], False))
                continue
            paths = matches
        else:
            paths = [arg]

        for path in paths:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                lines = content.splitlines()
                entries.append((path, content, lines, True))
                texts.append((path, content))
            else:
                entries.append((path, "", [], False))

    token = _choose_token(texts, token_on_collision, max_tries)

    with open(os.path.join(jobdir, "token.txt"), "w", encoding="utf-8") as f:
        f.write(token)

    format_text = _build_response_format(token)

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(format_text)
        out.write("\n\n")

        out.write(task_text)
        out.write("\n\n")

        for path, content, lines, exists in entries:
            if not exists:
                out.write(f"#### FILE {path} (does not exist)\n")
                continue

            out.write(f"#### FILE {path} ({len(lines)} lines)\n")
            for number, line in enumerate(lines, 1):
                out.write(f"{number}: {line}\n")

        out.write("\n\n")
        out.write(format_text)
        out.write("\n")


# ---------------------------------------------------------------------------
# run / child
# ---------------------------------------------------------------------------

def build_request_body(bundle_text: str, model: str = DEFAULT_MODEL) -> dict:
    return {
        "model": model,
        "stream": True,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "messages": [
            {"role": "user", "content": bundle_text},
        ],
    }


def _append_error(jobdir: str, message: str) -> None:
    path = os.path.join(jobdir, "error.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write(message.rstrip("\n") + "\n")


def _write_metadata(jobdir: str, usage_obj: dict | None, finish_reason: str) -> None:
    usage_path = os.path.join(jobdir, "usage.json")
    with open(usage_path, "w", encoding="utf-8") as f:
        json.dump(usage_obj or {}, f, indent=2, sort_keys=True)

    finish_path = os.path.join(jobdir, "finish.txt")
    with open(finish_path, "w", encoding="utf-8") as f:
        f.write(str(finish_reason or ""))


def _stream_deepseek(jobdir: str, model: str) -> None:
    bundle_path = os.path.join(jobdir, "bundle.txt")
    with open(bundle_path, "r", encoding="utf-8") as f:
        bundle_text = f.read()

    body = build_request_body(bundle_text, model)
    data = json.dumps(body).encode("utf-8")

    api_key = os.environ.get("DEEPSEEK_API_KEY", "proxy")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error: Exception | None = None

    for attempt in range(1, 3):
        usage_obj: dict = {}
        finish_reason = ""
        think_path = os.path.join(jobdir, "think.txt")
        out_path = os.path.join(jobdir, "out.txt")

        try:
            request = urllib.request.Request(
                DEEPSEEK_URL,
                data=data,
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(request) as response:
                with open(think_path, "w", encoding="utf-8") as think_f, \
                     open(out_path, "w", encoding="utf-8") as out_f:
                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data:"):
                            continue

                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break

                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        choices = obj.get("choices") or []
                        if choices:
                            choice = choices[0]
                            delta = choice.get("delta") or {}

                            reasoning = delta.get("reasoning_content")
                            if reasoning:
                                think_f.write(str(reasoning))
                                think_f.flush()

                            content = delta.get("content")
                            if content:
                                out_f.write(str(content))
                                out_f.flush()

                            finish = choice.get("finish_reason") or delta.get("finish_reason")
                            if finish:
                                finish_reason = str(finish)

                        if obj.get("usage"):
                            usage_obj = obj["usage"]

            _write_metadata(jobdir, usage_obj, finish_reason)
            return

        except urllib.error.HTTPError as exc:
            _append_error(jobdir, f"HTTP error {exc.code}: {exc.reason}")
            try:
                detail = exc.read().decode("utf-8", errors="replace")
                if detail:
                    _append_error(jobdir, detail)
            except Exception:
                pass
            _write_metadata(jobdir, usage_obj, finish_reason)
            raise

        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            _append_error(jobdir, f"network error: {exc}")
            _write_metadata(jobdir, usage_obj, finish_reason)
            continue

    if last_error is not None:
        raise last_error


def _run_child_command(args: argparse.Namespace) -> None:
    jobdir = os.path.abspath(args.jobdir)
    os.makedirs(jobdir, exist_ok=True)

    try:
        _stream_deepseek(jobdir, args.model)
    except Exception:
        traceback.print_exc()
        _append_error(jobdir, traceback.format_exc())
    finally:
        with open(os.path.join(jobdir, "DONE"), "w", encoding="utf-8") as f:
            f.write("")


def cmd_run(jobdir: str, model: str = DEFAULT_MODEL) -> None:
    jobdir = os.path.abspath(jobdir)
    os.makedirs(jobdir, exist_ok=True)

    log_path = os.path.join(jobdir, "daemon.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                os.path.abspath(__file__),
                "_run_child",
                jobdir,
                "--model",
                model,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    print(proc.pid, flush=True)


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------

def _read_token_file(jobdir: str) -> str:
    token_path = os.path.join(jobdir, "token.txt")
    if not os.path.exists(token_path):
        return ""
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _extract_digest(text: str, token: str = "") -> str:
    marker = _section_marker("DIGEST", token)
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text[:1500]


def _format_usage(jobdir: str) -> str:
    usage_path = os.path.join(jobdir, "usage.json")
    if not os.path.exists(usage_path):
        return ""

    try:
        with open(usage_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return ""

    if not isinstance(obj, dict):
        return ""

    parts = []
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in obj:
            parts.append(f"{key}={obj[key]}")

    if parts:
        return "usage: " + ", ".join(parts)
    if obj:
        return "usage: " + json.dumps(obj)
    return ""


def cmd_wait(jobdir: str, poll: float = 30.0, timeout: float | None = None) -> int:
    jobdir = os.path.abspath(jobdir)
    done_path = os.path.join(jobdir, "DONE")

    start = time.monotonic()
    while not os.path.exists(done_path):
        if timeout is not None and time.monotonic() - start >= timeout:
            return 1
        time.sleep(poll)

    finish_path = os.path.join(jobdir, "finish.txt")
    if os.path.exists(finish_path):
        with open(finish_path, "r", encoding="utf-8") as f:
            finish_reason = f.read().strip()
    else:
        finish_reason = ""

    print(f"finish_reason: {finish_reason}")

    error_path = os.path.join(jobdir, "error.txt")
    if os.path.exists(error_path):
        with open(error_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line:
                    print(f"error: {line}")

    usage_line = _format_usage(jobdir)
    if usage_line:
        print(usage_line)

    token = _read_token_file(jobdir)
    digest_marker = _section_marker("DIGEST", token)

    out_text = ""
    out_path = os.path.join(jobdir, "out.txt")
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            out_text = f.read()

    print(digest_marker)
    if digest_marker in out_text:
        print(_extract_digest(out_text, token))
    else:
        print("(no DIGEST section found; showing first 1500 characters of output)")
        print(out_text[:1500])

    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

@dataclass
class Edit:
    path: str
    kind: str
    a: int | None = None
    b: int | None = None
    first_text: str = ""
    new_lines: list[str] = field(default_factory=list)
    error: str = ""


def _find_marker(lines: list[str], marker: str, start: int) -> int | None:
    for idx in range(start, len(lines)):
        if lines[idx].strip() == marker:
            return idx
    return None


def _parse_edit(lines: list[str], start: int, token: str) -> tuple[Edit, int]:
    header = lines[start].strip()
    edit_marker = _marker("<<<EDIT", token)
    first_marker = _marker("<<<FIRST", token)
    new_marker = _marker(">>>NEW", token)
    end_marker = _marker(">>>END", token)

    marker_pattern = re.escape(edit_marker)
    re_replace = re.compile(
        r"^" + marker_pattern + r"\s+(?P<path>.+?)\s+lines\s+(?P<a>\d+)-(?P<b>\d+)\s*$"
    )
    re_insert = re.compile(
        r"^" + marker_pattern + r"\s+(?P<path>.+?)\s+insert-after\s+(?P<a>\d+)\s*$"
    )
    re_new = re.compile(
        r"^" + marker_pattern + r"\s+(?P<path>.+?)\s+new\s*$"
    )

    m = re_replace.match(header)
    if m:
        kind = "replace"
        path = m.group("path")
        a = int(m.group("a"))
        b = int(m.group("b"))
    else:
        m = re_insert.match(header)
        if m:
            kind = "insert"
            path = m.group("path")
            a = int(m.group("a"))
            b = None
        else:
            m = re_new.match(header)
            if m:
                kind = "new"
                path = m.group("path")
                a = None
                b = None
            else:
                return (
                    Edit(path="", kind="malformed", error="unrecognized edit header"),
                    start + 1,
                )

    if kind == "new":
        new_idx = _find_marker(lines, new_marker, start + 1)
        if new_idx is None:
            return Edit(path=path, kind="new", error="missing >>>NEW"), start + 1
        end_idx = _find_marker(lines, end_marker, new_idx + 1)
        if end_idx is None:
            return Edit(path=path, kind="new", error="missing >>>END"), start + 1
        return Edit(path=path, kind="new", new_lines=lines[new_idx + 1:end_idx]), end_idx + 1

    first_idx = _find_marker(lines, first_marker, start + 1)
    if first_idx is None:
        return Edit(path=path, kind=kind, error="missing <<<FIRST"), start + 1

    new_idx = _find_marker(lines, new_marker, first_idx + 1)
    if new_idx is None:
        return Edit(path=path, kind=kind, error="missing >>>NEW"), start + 1

    end_idx = _find_marker(lines, end_marker, new_idx + 1)
    if end_idx is None:
        return Edit(path=path, kind=kind, error="missing >>>END"), start + 1

    first_text = "\n".join(lines[first_idx + 1:new_idx])
    new_lines = lines[new_idx + 1:end_idx]

    return (
        Edit(
            path=path,
            kind=kind,
            a=a,
            b=b,
            first_text=first_text,
            new_lines=new_lines,
        ),
        end_idx + 1,
    )


def _extract_edits_section(text: str, token: str = "") -> str | None:
    edits_marker = _section_marker("EDITS", token)
    digest_marker = _section_marker("DIGEST", token)

    lines = text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == edits_marker:
            start_idx = idx + 1
            break

    if start_idx is None:
        return None

    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if lines[idx].strip() == digest_marker:
            end_idx = idx
            break

    return "\n".join(lines[start_idx:end_idx])


def _parse_edits(section: str, token: str = "") -> list[Edit]:
    lines = section.splitlines()
    edits: list[Edit] = []
    idx = 0
    edit_marker = _marker("<<<EDIT", token)

    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped == edit_marker or stripped.startswith(edit_marker + " "):
            edit, next_idx = _parse_edit(lines, idx, token)
            edits.append(edit)
            idx = max(next_idx, idx + 1)
        else:
            idx += 1

    return edits


def _detect_newline_style(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def _has_parent_component(path: str) -> bool:
    return ".." in path.replace("\\", "/").split("/")


def _edit_overlaps(e1: Edit, e2: Edit) -> bool:
    if e1.path != e2.path:
        return False

    if e1.kind == "new" or e2.kind == "new":
        return e1.kind == e2.kind == "new"

    def interval(e: Edit) -> tuple[int, int] | None:
        if e.kind == "replace":
            return (e.a or 0, e.b or 0)
        if e.kind == "insert":
            return (e.a or 0, e.a or 0)
        return None

    i1 = interval(e1)
    i2 = interval(e2)
    if i1 is None or i2 is None:
        return False

    return max(i1[0], i2[0]) <= min(i1[1], i2[1])


def _validate_edits(edits: list[Edit], root: str) -> str:
    root_abs = os.path.abspath(root)
    root_real = os.path.realpath(root_abs)

    for edit in edits:
        if edit.error:
            continue

        if not edit.path:
            edit.error = "empty path"
            continue

        if os.path.isabs(edit.path) or _has_parent_component(edit.path):
            edit.error = "path escapes repository"
            continue

        target = os.path.abspath(os.path.join(root_abs, edit.path))
        target_real = os.path.realpath(target)
        if not (target_real == root_real or target_real.startswith(root_real + os.sep)):
            edit.error = "path escapes repository"
            continue

        if edit.kind == "new":
            if os.path.exists(target):
                edit.error = "file already exists"
        elif edit.kind in ("replace", "insert"):
            if not os.path.isfile(target):
                edit.error = "file does not exist"
                continue

            try:
                with open(target, "r", encoding="utf-8", newline="") as f:
                    original_text = f.read()
            except Exception as exc:
                edit.error = f"cannot read file: {exc}"
                continue

            original_lines = original_text.splitlines()
            edit.newline_style = _detect_newline_style(original_text)
            edit.has_final_newline = original_text.endswith(("\n", "\r"))
            edit.original_lines = original_lines

            if edit.kind == "replace":
                a, b = edit.a or 0, edit.b or 0
                if a < 1 or b < a or b > len(original_lines):
                    edit.error = (
                        f"line range {a}-{b} out of bounds "
                        f"(file has {len(original_lines)} lines)"
                    )
                    continue

                if edit.first_text.rstrip() != original_lines[a - 1].rstrip():
                    edit.error = f"FIRST does not match line {a}"
                    continue
            else:  # insert
                a = edit.a or 0
                if a < 0 or a > len(original_lines):
                    edit.error = (
                        f"insert position {a} out of bounds "
                        f"(file has {len(original_lines)} lines)"
                    )
                    continue

                if a == 0:
                    if edit.first_text.rstrip() != "":
                        edit.error = "insert-after 0 must have an empty FIRST"
                        continue
                elif edit.first_text.rstrip() != original_lines[a - 1].rstrip():
                    edit.error = f"FIRST does not match line {a}"
                    continue
        else:
            edit.error = f"unknown edit kind: {edit.kind}"

    valid_grouped: dict[str, list[Edit]] = defaultdict(list)
    for edit in edits:
        if not edit.error:
            valid_grouped[edit.path].append(edit)

    for group in valid_grouped.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if _edit_overlaps(group[i], group[j]):
                    if not group[i].error:
                        group[i].error = "overlaps another edit in same file"
                    if not group[j].error:
                        group[j].error = "overlaps another edit in same file"

    return root_abs


def _apply_valid_edits(edits: list[Edit], root_abs: str, dry_run: bool) -> int:
    os.makedirs(root_abs, exist_ok=True)

    valid_grouped: dict[str, list[Edit]] = defaultdict(list)
    for edit in edits:
        if not edit.error:
            valid_grouped[edit.path].append(edit)

    applied_count = 0

    for path, group in valid_grouped.items():
        target = os.path.abspath(os.path.join(root_abs, path))

        if all(edit.kind == "new" for edit in group):
            edit = group[0]
            content = "\n".join(edit.new_lines)
            if not dry_run:
                os.makedirs(os.path.dirname(target) or root_abs, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
            applied_count += 1
            continue

        try:
            with open(target, "r", encoding="utf-8", newline="") as f:
                original_text = f.read()
        except Exception as exc:
            for edit in group:
                edit.error = f"cannot read file during apply: {exc}"
            continue

        lines = original_text.splitlines()
        newline_style = _detect_newline_style(original_text)
        has_final_newline = original_text.endswith(("\n", "\r"))

        def sort_key(edit: Edit) -> int:
            return edit.a if edit.a is not None else -1

        for edit in sorted(group, key=sort_key, reverse=True):
            if edit.kind == "replace":
                lines[edit.a - 1:edit.b] = edit.new_lines
            elif edit.kind == "insert":
                lines[edit.a:edit.a] = edit.new_lines
            applied_count += 1

        result = newline_style.join(lines)
        if has_final_newline:
            result += newline_style

        if not dry_run:
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(result)

    return applied_count


def _validate_and_apply(
    edits: list[Edit], root: str, dry_run: bool, mode: str
) -> tuple[str, int]:
    root_abs = _validate_edits(edits, root)
    refused_edits = [edit for edit in edits if edit.error]
    refused_count = len(refused_edits)

    if mode == "all-or-nothing" and refused_count:
        applied_count = 0
    else:
        applied_count = _apply_valid_edits(edits, root_abs, dry_run)

    report_lines = []
    report_lines.append(f"Mode: {mode}")
    report_lines.append(f"Applied: {applied_count}")
    report_lines.append(f"Refused: {refused_count}")
    if dry_run:
        report_lines.append("Dry run: yes (no repo files were modified)")

    if refused_edits:
        report_lines.append("Refused edits:")
        for edit in refused_edits:
            reason = edit.error or "refused"
            if edit.path:
                report_lines.append(f"- {edit.path} ({edit.kind}): {reason}")
            else:
                report_lines.append(f"- <malformed> ({edit.kind}): {reason}")
    else:
        report_lines.append("All edits accepted.")

    if mode == "all-or-nothing" and refused_count:
        report_lines.append(
            "All-or-nothing mode: no files were modified because at least one edit was refused."
        )
    elif mode == "partial" and refused_count:
        report_lines.append(
            "Partial mode: accepted edits were applied; refused edits were skipped."
        )

    report = "\n".join(report_lines) + "\n"
    return report, refused_count


def _resolve_apply_mode(cli_mode: str | None) -> str:
    if cli_mode is not None:
        if cli_mode not in APPLY_MODES:
            raise ValueError(
                f"invalid --mode value {cli_mode!r}; "
                f"expected one of {', '.join(APPLY_MODES)}"
            )
        return cli_mode

    env_value = os.environ.get("DSOFFLOAD_APPLY_MODE")
    if env_value is not None:
        env_value = env_value.strip()
        if env_value not in APPLY_MODES:
            raise ValueError(
                f"invalid DSOFFLOAD_APPLY_MODE value {env_value!r}; "
                f"expected one of {', '.join(APPLY_MODES)}"
            )
        return env_value

    return "all-or-nothing"


def cmd_apply(
    jobdir: str, root: str, dry_run: bool = False, mode: str | None = None
) -> int:
    jobdir = os.path.abspath(jobdir)
    root = os.path.abspath(root)
    os.makedirs(jobdir, exist_ok=True)

    report_path = os.path.join(jobdir, "apply_report.txt")

    try:
        apply_mode = _resolve_apply_mode(mode)
    except ValueError as exc:
        report = f"Error: {exc}\n"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        sys.stdout.write(report)
        return 2

    token = _read_token_file(jobdir)

    out_path = os.path.join(jobdir, "out.txt")
    if not os.path.exists(out_path):
        report = "No out.txt found; nothing to apply.\n"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        sys.stdout.write(report)
        return 0

    with open(out_path, "r", encoding="utf-8") as f:
        out_text = f.read()

    section = _extract_edits_section(out_text, token)
    if section is None:
        edits_marker = _section_marker("EDITS", token)
        report = f"No {edits_marker} section found in out.txt; nothing applied.\n"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        sys.stdout.write(report)
        return 2

    edits = _parse_edits(section, token)

    if not edits:
        edits_marker = _section_marker("EDITS", token)
        report = f"No edits found in {edits_marker} section.\n"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        sys.stdout.write(report)
        return 0

    report, refused_count = _validate_and_apply(
        edits, root, dry_run, apply_mode
    )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    sys.stdout.write(report)

    return 0 if refused_count == 0 else 2


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dsoffload")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sp_bundle = subparsers.add_parser("bundle")
    sp_bundle.add_argument("jobdir")
    sp_bundle.add_argument("--task", required=True)
    sp_bundle.add_argument(
        "--token-on-collision", choices=["grow", "fail"], default="grow"
    )
    sp_bundle.add_argument("--max-tries", type=int, default=DEFAULT_TOKEN_MAX_TRIES)
    sp_bundle.add_argument("files", nargs="*")

    sp_run = subparsers.add_parser("run")
    sp_run.add_argument("jobdir")
    sp_run.add_argument("--model", default=DEFAULT_MODEL)

    sp_wait = subparsers.add_parser("wait")
    sp_wait.add_argument("jobdir")
    sp_wait.add_argument("--poll", type=float, default=30.0)
    sp_wait.add_argument("--timeout", type=float, default=None)

    sp_apply = subparsers.add_parser("apply")
    sp_apply.add_argument("jobdir")
    sp_apply.add_argument("--root", required=True)
    sp_apply.add_argument("--dry-run", action="store_true")
    sp_apply.add_argument("--mode", choices=APPLY_MODES, default=None)

    sp_child = subparsers.add_parser("_run_child", help=argparse.SUPPRESS)
    sp_child.add_argument("jobdir")
    sp_child.add_argument("--model", default=DEFAULT_MODEL)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "bundle":
            cmd_bundle(
                args.jobdir,
                args.task,
                args.files,
                token_on_collision=args.token_on_collision,
                max_tries=args.max_tries,
            )
        elif args.command == "run":
            cmd_run(args.jobdir, args.model)
        elif args.command == "wait":
            return cmd_wait(args.jobdir, args.poll, args.timeout)
        elif args.command == "apply":
            return cmd_apply(args.jobdir, args.root, args.dry_run, args.mode)
        elif args.command == "_run_child":
            _run_child_command(args)
    except MarkerCollisionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
