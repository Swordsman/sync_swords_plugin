"""Write verbs: set, update, delete, str_replace, batch. if_version pins a write to a doc version."""

from .transport import call

MAX_BATCH_OPS = 50
BATCH_OPS = ("set", "update", "delete")


def set_doc(url, path: str, data: dict, if_version=None) -> dict:
    """Create or replace a document. Reply: {version, usage?}."""
    return call(url, "set", _pinned({"path": path, "data": _doc_data(data), "replace": True}, if_version))


def update_doc(url, path: str, data: dict, if_version=None) -> dict:
    """Merge data into an existing document (nested objects merge; other values replace)."""
    return call(url, "update", _pinned({"path": path, "data": _doc_data(data)}, if_version))


def delete_doc(url, path: str, if_version=None) -> dict:
    return call(url, "delete", _pinned({"path": path}, if_version))


def str_replace(url, path: str, field: str, old: str, new: str, replace_all=False, if_version=None) -> dict:
    """Swap the unique `old` for `new` inside string field `field` without resending the doc."""
    args = {"path": path, "field": field, "old_str": old, "new_str": new}
    if replace_all:
        args["replace_all"] = True
    return call(url, "str_replace", _pinned(args, if_version))


def write_op(op: str, path: str, data=None, if_version=None) -> dict:
    """One batch entry. op: set | update | delete."""
    if op not in BATCH_OPS:
        raise ValueError(f"batch op must be one of {BATCH_OPS}, not {op!r}")
    entry = {"op": op, "path": path}
    if op != "delete":
        entry["data"] = _doc_data(data)
    if op == "set":
        entry["replace"] = True
    return _pinned(entry, if_version)


def batch(url, ops: list) -> dict:
    """Up to 50 writes in one request, each path at most once. Reply: {results: [{version?}, ...]}.

    ops: write_op() dicts, or (op, path[, data[, if_version]]) tuples.
    """
    entries = [op if isinstance(op, dict) else write_op(*op) for op in ops]
    if not 1 <= len(entries) <= MAX_BATCH_OPS:
        raise ValueError(f"a batch holds 1 to {MAX_BATCH_OPS} writes, not {len(entries)}")
    paths = [entry["path"] for entry in entries]
    if len(set(paths)) != len(paths):
        raise ValueError("a batch writes each document at most once")
    return call(url, "batch", {"ops": entries})


def _doc_data(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"document data must be a JSON object, not {type(data).__name__}")
    return data


def _pinned(args: dict, if_version) -> dict:
    return args if if_version is None else {**args, "ifVersion": if_version}
