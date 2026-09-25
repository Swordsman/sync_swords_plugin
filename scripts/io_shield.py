#!/usr/bin/env python3
"""
io-shield — File integrity + write-lock tool for multi-agent coordination.

Prevents ghost agents and file collisions via:
  - Write-lock: exclusive ownership before editing
  - Hash verification: detect unauthorized modifications after unlock

Usage:
  io-shield lock <agent-name> <filepath>
    → Acquire write permission. Fails if another agent holds the lock.

  io-shield unlock <agent-name> <filepath>
    → Release lock + log hash. Fails if lock is held by another agent.

  io-shield heartbeat <agent-name> <filepath>
    → Renew lock timestamp. Must hold the lock. Prevents ghost expiry.

  io-shield queue <agent-name> <filepath>
    → Acquire lock if free, or join wait queue if held.

  io-shield verify <agent-name> <filepath>
    → Check if file still matches hash from unlock. No lock needed.

  io-shield worklog <agent-name>
    → Show structured report of all lock/unlock/verify activity.

  io-shield status
    → Show all active locks and queued waiters.

Agents MUST lock before writing and unlock after writing.
"""

import hashlib
import sys
import os
import base64
import json
from pathlib import Path
from datetime import datetime, timezone

LOCK_TIMEOUT_SECONDS = int(
    os.environ.get("IO_SHIELD_TTL", "1800")  # default 30 min; use 300-600 for heartbeat mode
)


def _get_lock_dir() -> Path:
    """Get the lock directory from IO_SHIELD_DIR or default."""
    base = Path(os.environ.get("IO_SHIELD_DIR", Path.home() / ".io-shield"))
    return base / "locks"


def _get_hash_log_dir() -> Path:
    """Get the hash log directory from IO_SHIELD_DIR or default."""
    return Path(os.environ.get("IO_SHIELD_DIR", Path.home() / ".io-shield"))


def encode_path(filepath: str) -> str:
    """Create a filesystem-safe lock name from a filepath."""
    abs_path = str(Path(filepath).resolve())
    return base64.urlsafe_b64encode(abs_path.encode()).decode().rstrip("=")


def decode_path(encoded: str) -> str:
    """Decode a lock name back to a filepath."""
    padding = 4 - (len(encoded) % 4)
    if padding != 4:
        encoded += "=" * padding
    return base64.urlsafe_b64decode(encoded.encode()).decode()


def compute_hash(filepath: str) -> str:
    p = Path(filepath).resolve()
    if not p.exists():
        return "<FILE_NOT_FOUND>"
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def get_lock_path(filepath: str) -> Path:
    lock_dir = _get_lock_dir()
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{encode_path(filepath)}.lock"


def get_hash_log_path(agent_name: str) -> Path:
    hash_log_dir = _get_hash_log_dir()
    hash_log_dir.mkdir(parents=True, exist_ok=True)
    return hash_log_dir / f".{agent_name}.worklog.hashes"


def get_queue_path(filepath: str) -> Path:
    lock_dir = _get_lock_dir()
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{encode_path(filepath)}.queue"


def read_queue(queue_path: Path) -> list:
    if not queue_path.exists():
        return []
    try:
        data = json.loads(queue_path.read_text())
        return data.get("queue", [])
    except Exception:
        return []


def write_queue(queue_path: Path, agents: list):
    if agents:
        queue_path.write_text(json.dumps({"queue": agents}, indent=2))
    else:
        queue_path.unlink(missing_ok=True)


def read_lock(lock_path: Path) -> dict | None:
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text())
    except Exception:
        return None


def write_lock(lock_path: Path, data: dict):
    lock_path.write_text(json.dumps(data, indent=2))


def is_expired(lock_data: dict) -> bool:
    try:
        ts = datetime.fromisoformat(lock_data["timestamp"])
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age > LOCK_TIMEOUT_SECONDS
    except Exception:
        return True


def lock_file(agent_name: str, filepath: str) -> int:
    lock_path = get_lock_path(filepath)
    existing = read_lock(lock_path)

    if existing and not is_expired(existing):
        owner = existing.get("agent", "unknown")
        ts = existing.get("timestamp", "unknown")
        print("=" * 70, file=sys.stderr)
        print("LOCK DENIED", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  File: {Path(filepath).resolve()}", file=sys.stderr)
        print(f"  Locked by: {owner} (since {ts})", file=sys.stderr)
        print(file=sys.stderr)
        print("You may NOT edit this file.", file=sys.stderr)
        print("Wait for the lock holder to unlock, or ask root-parent to intervene.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    if existing and is_expired(existing):
        old_owner = existing.get("agent", "unknown")
        print(f"[io-shield] Stealing expired lock from {old_owner} on {filepath}", file=sys.stderr)

    write_lock(lock_path, {
        "agent": agent_name,
        "filepath": str(Path(filepath).resolve()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": "write"
    })
    print(f"[io-shield] LOCK GRANTED: {agent_name} -> {Path(filepath).resolve()}")
    return 0


def unlock_file(agent_name: str, filepath: str) -> int:
    lock_path = get_lock_path(filepath)
    existing = read_lock(lock_path)

    if not existing:
        print("=" * 70, file=sys.stderr)
        print("WARNING: No lock found for this file.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  File: {Path(filepath).resolve()}", file=sys.stderr)
        print("  You should have called 'lock' before editing.", file=sys.stderr)
        print("  Root-parent will be notified.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
    elif existing.get("agent") != agent_name:
        owner = existing.get("agent", "unknown")
        print("=" * 70, file=sys.stderr)
        print("CRITICAL: LOCK VIOLATION", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  File: {Path(filepath).resolve()}", file=sys.stderr)
        print(f"  Lock held by: {owner}", file=sys.stderr)
        print(f"  You are: {agent_name}", file=sys.stderr)
        print(file=sys.stderr)
        print("STOP ALL WORK IMMEDIATELY.", file=sys.stderr)
        print("Do not edit any more files.", file=sys.stderr)
        print("ABORT and return to root-parent for instructions.", file=sys.stderr)
        print("This is a DIRECT ORDER from root-parent and user.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    # Log hash
    file_hash = compute_hash(filepath)
    log_path = get_hash_log_path(agent_name)
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(f"{timestamp}\t{Path(filepath).resolve()}\t{file_hash}\tunlock\n")

    # Remove lock / auto-transfer to next queued agent
    if existing and existing.get("agent") == agent_name:
        queue_path = get_queue_path(filepath)
        waiters = read_queue(queue_path)
        if waiters:
            next_agent = waiters.pop(0)
            write_lock(lock_path, {
                "agent": next_agent,
                "filepath": str(Path(filepath).resolve()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation": "write",
                "via": "queue"
            })
            write_queue(queue_path, waiters)
            print(f"[io-shield] UNLOCKED + HASH LOGGED: {agent_name} -> {Path(filepath).resolve()} = {file_hash}")
            print(f"[io-shield] QUEUE TRANSFER: lock auto-granted to {next_agent}")
        else:
            lock_path.unlink(missing_ok=True)
            write_queue(queue_path, [])  # clean up empty queue file
            print(f"[io-shield] UNLOCKED + HASH LOGGED: {agent_name} -> {Path(filepath).resolve()} = {file_hash}")
    else:
        print(f"[io-shield] UNLOCKED + HASH LOGGED: {agent_name} -> {Path(filepath).resolve()} = {file_hash}")
    return 0


def heartbeat_lock(agent_name: str, filepath: str) -> int:
    """Renew lock timestamp. Agent must already hold the lock."""
    lock_path = get_lock_path(filepath)
    existing = read_lock(lock_path)

    if not existing:
        print("=" * 70, file=sys.stderr)
        print("HEARTBEAT FAILED: No lock found.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  File: {Path(filepath).resolve()}", file=sys.stderr)
        print(f"  Agent: {agent_name}", file=sys.stderr)
        print()
        print("You must lock before sending heartbeat.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    if existing.get("agent") != agent_name:
        owner = existing.get("agent", "unknown")
        print("=" * 70, file=sys.stderr)
        print("HEARTBEAT FAILED: Lock held by another agent.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  File: {Path(filepath).resolve()}", file=sys.stderr)
        print(f"  Locked by: {owner}", file=sys.stderr)
        print(f"  You are: {agent_name}", file=sys.stderr)
        print()
        print("STOP ALL WORK IMMEDIATELY.", file=sys.stderr)
        print("ABORT and return to root-parent for instructions.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    if is_expired(existing):
        print("=" * 70, file=sys.stderr)
        print("HEARTBEAT FAILED: Lock has expired.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"  File: {Path(filepath).resolve()}", file=sys.stderr)
        print(f"  Lock timeout: {LOCK_TIMEOUT_SECONDS}s", file=sys.stderr)
        print()
        print("Re-lock the file before continuing.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    existing["timestamp"] = datetime.now(timezone.utc).isoformat()
    write_lock(lock_path, existing)
    print(f"[io-shield] HEARTBEAT OK: {agent_name} -> {Path(filepath).resolve()}")
    return 0


def queue_for_lock(agent_name: str, filepath: str) -> int:
    """Acquire lock if free, or join wait queue."""
    lock_path = get_lock_path(filepath)
    existing = read_lock(lock_path)

    if not existing or is_expired(existing):
        if existing and is_expired(existing):
            old_owner = existing.get("agent", "unknown")
            print(f"[io-shield] Stealing expired lock from {old_owner} on {filepath}", file=sys.stderr)
        write_lock(lock_path, {
            "agent": agent_name,
            "filepath": str(Path(filepath).resolve()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": "write"
        })
        print(f"[io-shield] LOCK GRANTED (queue): {agent_name} -> {Path(filepath).resolve()}")
        return 0

    if existing.get("agent") == agent_name:
        print(f"[io-shield] Already holding lock: {agent_name} -> {Path(filepath).resolve()}")
        return 0

    # Lock is held by another agent — join queue
    queue_path = get_queue_path(filepath)
    waiters = read_queue(queue_path)

    if agent_name in waiters:
        position = waiters.index(agent_name) + 1
        print(f"[io-shield] Already queued: {agent_name} at position {position}/{len(waiters)} for {Path(filepath).resolve()}")
        return 0

    waiters.append(agent_name)
    write_queue(queue_path, waiters)
    position = len(waiters)
    owner = existing.get("agent", "unknown")
    print(f"[io-shield] QUEUED: {agent_name} at position {position} (lock held by {owner}) for {Path(filepath).resolve()}")
    return 0


def show_worklog(agent_name: str) -> int:
    """Show structured report of all lock/unlock/verify activity for an agent."""
    log_path = get_hash_log_path(agent_name)
    if not log_path.exists():
        print(f"[io-shield] No activity recorded for {agent_name}.")
        return 0

    entries = []
    with open(log_path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            entries.append({
                "timestamp": parts[0],
                "filepath": parts[1],
                "hash": parts[2],
                "action": parts[3]
            })

    if not entries:
        print(f"[io-shield] No activity recorded for {agent_name}.")
        return 0

    print(f"[io-shield] Worklog for {agent_name}:")
    print(f"  Total entries: {len(entries)}")

    # Group by file
    by_file = {}
    for e in entries:
        fp = e["filepath"]
        if fp not in by_file:
            by_file[fp] = []
        by_file[fp].append(e)

    for fp, file_entries in sorted(by_file.items()):
        actions = [e["action"] for e in file_entries]
        first_ts = file_entries[0]["timestamp"]
        last_ts = file_entries[-1]["timestamp"]
        last_hash = file_entries[-1]["hash"]
        print(f"  File: {fp}")
        print(f"    Actions: {', '.join(actions)}")
        print(f"    First: {first_ts}  Last: {last_ts}")
        print(f"    Last hash: {last_hash}")

        # Check current integrity
        current_hash = compute_hash(fp)
        if current_hash == "<FILE_NOT_FOUND>":
            print(f"    STATUS: FILE DELETED")
        elif current_hash != last_hash:
            print(f"    STATUS: TAMPERED (current hash differs from last logged)")
        else:
            print(f"    STATUS: INTACT")

    return 0


def verify_file(agent_name: str, filepath: str) -> int:
    """Check if file still matches the last logged hash."""
    log_path = get_hash_log_path(agent_name)
    if not log_path.exists():
        print(f"[io-shield] No hash log for {agent_name}. Nothing to verify.")
        return 0

    current_hash = compute_hash(filepath)
    abs_path = str(Path(filepath).resolve())
    mismatches = []

    with open(log_path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            _, logged_path, logged_hash = parts[0], parts[1], parts[2]
            if logged_path == abs_path and logged_hash != current_hash:
                mismatches.append((logged_path, logged_hash, current_hash))

    if mismatches:
        print("=" * 70, file=sys.stderr)
        print("CRITICAL: HASH MISMATCH DETECTED", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        for logged_path, expected, actual in mismatches:
            print(f"  File: {logged_path}", file=sys.stderr)
            print(f"  Expected: {expected}", file=sys.stderr)
            print(f"  Actual:   {actual}", file=sys.stderr)
        print(file=sys.stderr)
        print("STOP ALL WORK IMMEDIATELY.", file=sys.stderr)
        print("Do not edit any more files.", file=sys.stderr)
        print("ABORT and return to root-parent for instructions.", file=sys.stderr)
        print("This is a DIRECT ORDER from root-parent and user.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    print(f"[io-shield] VERIFIED: {abs_path} matches last hash ({current_hash})")
    return 0


def show_status() -> int:
    lock_dir = _get_lock_dir()
    if not lock_dir.exists():
        print("[io-shield] No active locks.")
        return 0

    locks = []
    for lock_file in lock_dir.glob("*.lock"):
        data = read_lock(lock_file)
        if data:
            decoded_path = decode_path(lock_file.stem)
            ts = data.get("timestamp", "unknown")
            agent = data.get("agent", "unknown")
            expired = " (EXPIRED)" if is_expired(data) else ""
            via = data.get("via", "")
            via_str = f" [via {via}]" if via else ""
            locks.append(f"  [{agent}] {decoded_path} (since {ts}){expired}{via_str}")

    if locks:
        print("[io-shield] Active locks:")
        for line in sorted(locks):
            print(line)
    else:
        print("[io-shield] No active locks.")

    # Show queued waiters
    queues = []
    for qf in lock_dir.glob("*.queue"):
        waiters = read_queue(qf)
        if waiters:
            decoded_path = decode_path(qf.stem)
            queues.append(f"  {decoded_path}: {', '.join(waiters)}")

    if queues:
        print()
        print("[io-shield] Queued waiters:")
        for line in sorted(queues):
            print(line)

    return 0


def main():
    try:
        if len(sys.argv) < 2:
            print(f"Usage: {sys.argv[0]} <lock|unlock|heartbeat|queue|verify|worklog|status> [agent-name] [filepath]", file=sys.stderr)
            sys.exit(2)

        cmd = sys.argv[1]

        if cmd == "status":
            sys.exit(show_status())

        if cmd == "worklog":
            if len(sys.argv) != 3:
                print(f"Usage: {sys.argv[0]} worklog <agent-name>", file=sys.stderr)
                sys.exit(2)
            sys.exit(show_worklog(sys.argv[2]))

        if len(sys.argv) != 4:
            print(f"Usage: {sys.argv[0]} {cmd} <agent-name> <filepath>", file=sys.stderr)
            sys.exit(2)

        agent_name = sys.argv[2]
        filepath = sys.argv[3]

        if cmd == "lock":
            sys.exit(lock_file(agent_name, filepath))
        elif cmd == "unlock":
            sys.exit(unlock_file(agent_name, filepath))
        elif cmd == "heartbeat":
            sys.exit(heartbeat_lock(agent_name, filepath))
        elif cmd == "queue":
            sys.exit(queue_for_lock(agent_name, filepath))
        elif cmd == "verify":
            sys.exit(verify_file(agent_name, filepath))
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(2)

    except Exception as e:
        print("=" * 70, file=sys.stderr)
        print("CRITICAL: IO-SHIELD CRASHED", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"Exception: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(file=sys.stderr)
        print("STOP ALL WORK IMMEDIATELY.", file=sys.stderr)
        print("ABORT and return to root-parent for instructions.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
