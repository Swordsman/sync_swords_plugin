#!/usr/bin/env python3
"""gitx: git operations that verify their own outcome. Each op runs git, checks a procedural postcondition, optionally
checks the diff against a stated intent with one Jev Score, and appends one JSON line to ~/.gitx/log.jsonl."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

FALLBACK_DEFAULTS = ("main", "master")
LOG_PATH = Path(os.environ.get("GITX_LOG", "~/.gitx/log.jsonl")).expanduser()
INTENT_LEVELS = [
    "The diff does something else: its changes are unrelated to the intent.",
    "The diff partly matches the intent but also includes unrelated changes.",
    "The diff matches the intent, with minor extra changes beyond it.",
    "The diff does exactly what the intent says and nothing else.",
]
TOP_LEVEL = len(INTENT_LEVELS) - 1
DOUBT_BAND = (0.4, 0.6)  # distance below the threshold level where a Score is too uncertain to call (jev.md rule 8)


class GitxError(RuntimeError):
    pass


class GitError(GitxError):
    def __init__(self, command: list[str], returncode: int, stderr: str):
        super().__init__(f"{' '.join(command)} exited {returncode}: {stderr.strip()}")
        self.command, self.returncode, self.stderr = command, returncode, stderr


class ContractError(GitxError):
    pass


class BranchGuardError(GitxError):
    pass


class IntentError(GitxError):
    def __init__(self, message: str, score: float):
        super().__init__(message)
        self.score = score


def run(args: list[str], cwd: str | Path = ".", check: bool = True) -> subprocess.CompletedProcess:
    command = ["git", *args]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env)
    if check and result.returncode:
        raise GitError(command, result.returncode, result.stderr)
    return result


def strip_index_lines(diff: str) -> str:
    return "\n".join(line for line in diff.splitlines() if not line.startswith("index "))


def check_intent(intent: str, diff: str, ask=None) -> float:
    """Score 0..3: how exactly `diff` does what `intent` says. One Jev call, one Score with described levels."""
    if ask is None:
        import scout
        ask = scout.ask_jev
    question = {
        "type": "score",
        "instructions": "`intent` says what a change was meant to do. `diff` is the unified diff of the change actually made. "
                        "How closely does `diff` match `intent`? Judge extra changes by whether `intent` asked for them.",
        "criteria": INTENT_LEVELS,
    }
    return ask({"intent": intent, "diff": diff}, {"match": question})["answers"]["match"]["score"]


def judge_intent(score: float, threshold: float = TOP_LEVEL) -> None:
    shortfall = threshold - score
    if shortfall <= DOUBT_BAND[0]:
        return
    verdict = "doubtful" if shortfall < DOUBT_BAND[1] else "below threshold"
    raise IntentError(f"intent score {score:.2f} is {verdict} (threshold {threshold})", score)


class Repo:
    def __init__(self, path: str | Path = ".", ask=None, log_path: str | Path | None = None):
        self.cwd = Path(path).resolve()
        self.root = Path(run(["rev-parse", "--show-toplevel"], cwd=self.cwd).stdout.strip()).resolve()
        self.ask = ask
        self.log_path = Path(log_path) if log_path else LOG_PATH

    def git(self, *args: str, check: bool = True) -> str:
        return run(list(args), cwd=self.root, check=check).stdout.rstrip("\n")

    def diff_text(self, *args: str) -> str:
        return run(["diff", *args], cwd=self.root).stdout

    def head(self) -> str | None:
        result = run(["rev-parse", "--verify", "-q", "HEAD"], cwd=self.root, check=False)
        return result.stdout.strip() or None

    def branch(self) -> str:
        return self.git("symbolic-ref", "--short", "HEAD")

    def default_branch(self) -> str | None:
        result = run(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=self.root, check=False)
        if result.returncode == 0:
            return result.stdout.strip().removeprefix("refs/remotes/origin/")
        for name in FALLBACK_DEFAULTS:
            if run(["rev-parse", "--verify", "-q", f"refs/heads/{name}"], cwd=self.root, check=False).returncode == 0:
                return name
        return None

    def guard_branch(self, allow_default: bool) -> None:
        branch = self.branch()
        if not allow_default and branch == self.default_branch():
            raise BranchGuardError(f"refusing to act on default branch {branch!r}; pass allow_default=True to override")

    def relative_paths(self, paths: list[str]) -> list[str]:
        return [os.path.relpath((self.cwd / path).resolve(), self.root) for path in paths]

    def staged_files(self) -> set[str]:
        return set(filter(None, self.git("diff", "--cached", "--name-only").split("\n")))

    @contextmanager
    def reported(self, op: str, args: dict, intent: str | None):
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repo": str(self.root), "op": op, "args": args}
        if intent is not None:
            record["intent"] = intent
        try:
            yield record
            record["result"] = "ok"
        except Exception as error:
            record["result"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as log:
                log.write(json.dumps(record) + "\n")

    def intent_gate(self, record: dict, intent: str | None, diff: str, threshold: float) -> None:
        if intent is None:
            return
        record["intent_score"] = score = check_intent(intent, diff, self.ask)
        judge_intent(score, threshold)

    # commit ---------------------------------------------------------------------------------------------------

    def commit(self, paths: list[str], message: str, intent: str | None = None, allow_default: bool = False,
               threshold: float = TOP_LEVEL) -> dict:
        with self.reported("commit", {"paths": paths, "message": message}, intent) as record:
            self.guard_branch(allow_default)
            relative = self.relative_paths(paths)
            before = self.head()
            self.git("add", "--", *relative)
            try:
                self.intent_gate(record, intent, self.diff_text("--cached", "--", *relative), threshold)
            except IntentError:
                run(["restore", "--staged", "--", *relative], cwd=self.root, check=False)
                raise
            self.git("commit", "-m", message, "--only", "--", *relative)
            self.verify_commit(relative, before)
        return record

    def verify_commit(self, relative_paths: list[str], before: str | None) -> None:
        head = self.head()
        if head is None or head == before:
            raise ContractError(f"expected HEAD to move past {before}, found {head}")
        parent = run(["rev-parse", "--verify", "-q", "HEAD^"], cwd=self.root, check=False).stdout.strip() or None
        if parent != before:
            raise ContractError(f"expected new commit on top of {before}, its parent is {parent}")
        changed = set(filter(None, self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD").split("\n")))
        covered = {file for file in changed if any(file == path or file.startswith(path.rstrip("/") + "/") for path in relative_paths)}
        unused = [path for path in relative_paths
                  if not any(file == path or file.startswith(path.rstrip("/") + "/") for file in changed)]
        if covered != changed or unused:
            raise ContractError(f"expected commit to change exactly {sorted(relative_paths)}; changed {sorted(changed)}"
                                + (f", nothing changed under {unused}" if unused else ""))
        if leftover := self.staged_files():
            raise ContractError(f"expected nothing left staged; still staged: {sorted(leftover)}")

    # revert ---------------------------------------------------------------------------------------------------

    def revert(self, target: str, intent: str | None = None, allow_default: bool = False, threshold: float = TOP_LEVEL) -> dict:
        with self.reported("revert", {"target": target}, intent) as record:
            self.guard_branch(allow_default)
            sha = self.git("rev-parse", "--verify", f"{target}^{{commit}}")
            if len(self.git("rev-list", "--parents", "-n1", sha).split()) != 2:
                raise ValueError(f"{target} must have exactly one parent")
            before = self.head()
            self.intent_gate(record, intent, self.diff_text(sha, f"{sha}^"), threshold)
            if run(["revert", "--no-edit", sha], cwd=self.root, check=False).returncode:
                run(["revert", "--abort"], cwd=self.root, check=False)
                raise GitError(["git", "revert", sha], 1, "revert failed (conflict?) and was aborted")
            self.verify_revert(sha, before)
        return record

    def verify_revert(self, target: str, before: str | None) -> None:
        head = self.head()
        if head is None or head == before or self.git("rev-parse", "HEAD^") != before:
            raise ContractError(f"expected HEAD to be a new commit on top of {before}, found {head}")
        expected = strip_index_lines(self.diff_text(target, f"{target}^"))
        found = strip_index_lines(self.diff_text("HEAD^", "HEAD"))
        if expected != found:
            raise ContractError(f"expected HEAD's diff to be the exact inverse of {target[:10]}'s diff:\n{expected}\nfound:\n{found}")

    # push -----------------------------------------------------------------------------------------------------

    def remote_head(self, branch: str) -> str | None:
        output = self.git("ls-remote", "origin", f"refs/heads/{branch}")
        return output.split()[0] if output else None

    def push(self, intent: str | None = None, allow_default: bool = False, threshold: float = TOP_LEVEL) -> dict:
        with self.reported("push", {}, intent) as record:
            self.guard_branch(allow_default)
            branch = self.branch()
            record["args"]["branch"] = branch
            self.intent_gate(record, intent, self.pending_diff(branch), threshold)
            self.git("push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
            self.verify_push(branch)
            self.git("fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
            if run(["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"], cwd=self.root, check=False).returncode:
                self.git("config", f"branch.{branch}.remote", "origin")  # not `branch --set-upstream-to`: single-branch clones fail it
                self.git("config", f"branch.{branch}.merge", f"refs/heads/{branch}")
        return record

    def pending_diff(self, branch: str) -> str:
        """What a push would add: HEAD against the remote branch, else its tracking ref, else origin's default branch."""
        bases = [self.remote_head(branch), f"refs/remotes/origin/{branch}", f"refs/remotes/origin/{self.default_branch()}"]
        for base in bases:
            if base and run(["cat-file", "-e", f"{base}^{{commit}}"], cwd=self.root, check=False).returncode == 0:
                return self.diff_text(base, "HEAD")
        return run(["show", "--format=", "HEAD"], cwd=self.root).stdout

    def verify_push(self, branch: str) -> None:
        local, remote = self.head(), self.remote_head(branch)
        if remote != local:
            raise ContractError(f"expected origin refs/heads/{branch} == local HEAD {local}; remote is {remote}")


# CLI ----------------------------------------------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="git operations that verify their own outcome; run inside the repo")
    commands = parser.add_subparsers(dest="command", required=True)
    commit = commands.add_parser("commit")
    commit.add_argument("--paths", nargs="+", required=True)
    commit.add_argument("-m", "--message", required=True)
    revert = commands.add_parser("revert")
    revert.add_argument("target")
    commands.add_parser("push")
    check = commands.add_parser("check-intent")
    check.add_argument("--diff-file", required=True)
    for name, sub in commands.choices.items():
        sub.add_argument("--intent", required=name == "check-intent")
        if name in ("commit", "revert", "push"):
            sub.add_argument("--allow-default", action="store_true")
            sub.add_argument("--threshold", type=float, default=TOP_LEVEL)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "check-intent":
            score = check_intent(args.intent, Path(args.diff_file).read_text())
            print(json.dumps({"intent_score": score}))
            return 0
        repo = Repo(".")
        options = {"intent": args.intent, "allow_default": args.allow_default, "threshold": args.threshold}
        if args.command == "commit":
            record = repo.commit(args.paths, args.message, **options)
        elif args.command == "revert":
            record = repo.revert(args.target, **options)
        else:
            record = repo.push(**options)
        print(json.dumps(record))
        return 0
    except GitxError as error:
        print(f"gitx: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
