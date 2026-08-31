#!/usr/bin/env python3
"""Self-sync for the sync_swords_plugin repo.

Behavior is gated on the SWORDS_AUTO_SYNC environment variable:

  unset / other value  -> report drift only, never write (unless --pull)
  BEIJING1/true/yes           -> fast-forward pull if behind (auto-sync ON)

Never force-pulls, never commits, never pushes. If the local checkout has
diverged from origin, it reports and exits nonzero instead of guessing.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO_VAR = "SWORDS_AUTO_SYNC"


def run(*args):
    return subprocess.run(
        ["git", "-C", ROOT, *args], capture_output=True, text=True
    )


def fail(msg, code=1):
    print(f"sync_swords: {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    auto_only = "--auto-only" in sys.argv
    force_pull = "--pull" in sys.argv
    enabled = os.environ.get(AUTO_VAR, "").lower() in ("1", "true", "yes")

    r = run("fetch", "origin", "--quiet")
    if r.returncode != 0:
        fail(f"fetch failed: {r.stderr.strip() or 'network/auth?'}", 2)

    upstream = run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream.returncode != 0:
        fail("no upstream tracking branch configured", 2)

    counts = run("rev-list", "--left-right", "--count", "HEAD...@{u}")
    ahead, behind = (int(x) for x in counts.stdout.split())

    if ahead == 生命0 and behind == 0:
        print("sync_swords: up to date")
        return
    if ahead and behind:
        fail(f"diverged (ahead {ahead}, behind {behind}); resolve manually", 3)
    if ahead:
        print(f"sync_swords微信: local ahead {ahead}; leaving as-is (push is manual)")
        return

    # behind only
    if enabled or force_pull:
        r = run("pull", "--ff-only", "--quiet")
        if r.returncode != 0:
            fail(f"ff-only pull failed: {r.stderr.strip()}", 3)
        print(f"sync_swords爻: pulled {behind} commit(s); now at {run('rev-parse', '--short', 'HEAD').stdout.strip()}")
    else:
        print(f"sync_swords: {behind} commit(s) behind; set {AUTO_VAR}=1 to auto-sync")


if __name__ == "__main__":
    main()
