"""lsdb CLI. Exit codes: 0 ok, 1 usage/input error, 2 API error, 3 not in a claude.ai/code session."""

import argparse
import json
import os
import sys

from . import catalog, reads, writes
from .transport import LsdbApiError, LsdbEnvError, LsdbError

ENV_MISSING_MSG = "lsdb: not in a claude.ai/code session; use the ArtifactData tool with out_dir instead"
READ_CMDS = ("get", "list", "query")


class _Parser(argparse.ArgumentParser):
    """Exits 1 on usage errors, keeping exit 2 for API errors."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="lsdb", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def command(name, text, *positionals):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("url", help="artifact URL or id")
        for positional in positionals:
            cmd.add_argument(positional)
        return cmd

    def output_flags(cmd, ids=True):
        group = cmd.add_mutually_exclusive_group()
        group.add_argument("--out", metavar="DIR", help="write each doc's data to DIR/<path>.json; print one line")
        if ids:
            group.add_argument("--ids", action="store_true", help="print doc ids only, one per line")

    output_flags(command("get", "read one document", "path"), ids=False)
    output_flags(command("list", "every document in a collection", "collection"))
    cmd = command("query", "server-side query of a collection", "collection")
    cmd.add_argument("--where", nargs=3, action="append", metavar=("FIELD", "OP", "JSONVALUE"),
                     help="repeatable; OP: == != < <= > >= in not-in array-contains; JSONVALUE is JSON")
    cmd.add_argument("--order-by", metavar="FIELD", help="one page, at most --limit docs")
    cmd.add_argument("--direction", choices=("asc", "desc"))
    cmd.add_argument("--limit", type=int, help="1-1000")
    output_flags(cmd)
    for name in ("set", "update"):
        cmd = command(name, f"{name} a document from JSON", "path")
        source = cmd.add_mutually_exclusive_group(required=True)
        source.add_argument("--data", metavar="JSON")
        source.add_argument("--file", metavar="PATH", help="'-' reads stdin")
        cmd.add_argument("--if-version", type=int, metavar="N")
    command("delete", "delete a document", "path").add_argument("--if-version", type=int, metavar="N")
    cmd = command("str-replace", "replace a unique substring of a string field", "path", "field", "old", "new")
    cmd.add_argument("--all", action="store_true", help="replace every occurrence")
    cmd.add_argument("--if-version", type=int, metavar="N")
    command("batch", "up to 50 writes from a JSON list of {op, path, data?, if_version?}", "file")
    cmd = command("register", "describe a collection in the catalog the store page lists", "collection")
    cmd.add_argument("--description")
    cmd.add_argument("--view", choices=catalog.VIEWS)
    return parser


def _json_arg(raw, what):
    try:
        return json.loads(raw)
    except ValueError:
        raise ValueError(f"{what} is not JSON: {raw!r} (quote strings, e.g. '\"open\"')") from None


def _load_json_file(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def run(args):
    """Execute one parsed command; return its JSON-serializable result."""
    match args.cmd:
        case "get":
            return reads.get(args.url, args.path)
        case "list":
            return reads.list_all(args.url, args.collection)
        case "query":
            if args.direction and not args.order_by:
                raise ValueError("--direction needs --order-by")
            where = [(field, op, _json_arg(raw, f"--where value for {field!r}")) for field, op, raw in args.where or []]
            order_by = (args.order_by, args.direction) if args.order_by else None
            return reads.query(args.url, args.collection, where=where, order_by=order_by, limit=args.limit)
        case "set" | "update":
            data = _json_arg(args.data, "--data") if args.file is None else _load_json_file(args.file)
            writer = writes.set_doc if args.cmd == "set" else writes.update_doc
            return writer(args.url, args.path, data, args.if_version)
        case "delete":
            return writes.delete_doc(args.url, args.path, args.if_version)
        case "str-replace":
            return writes.str_replace(args.url, args.path, args.field, args.old, args.new, args.all, args.if_version)
        case "batch":
            ops = [writes.write_op(op["op"], op["path"], op.get("data"), op.get("if_version"))
                   for op in _load_json_file(args.file)]
            return writes.batch(args.url, ops)
        case "register":
            return catalog.register(args.url, args.collection, args.description, args.view)


def emit(args, result) -> None:
    """Print the result in the mode asked for: full JSON, ids, files + one line, or a compact write summary."""
    if args.cmd not in READ_CMDS:
        print(json.dumps({key: result[key] for key in ("version", "results", "usage") if key in result}))
        return
    docs = _as_docs(args, result)
    if getattr(args, "ids", False):
        print("\n".join(doc["id"] for doc in docs))
    elif args.out:
        prefix = args.path.rsplit("/", 1)[0] if args.cmd == "get" else args.collection
        for doc in docs:
            target = os.path.join(args.out, *prefix.split("/"), doc["id"] + ".json")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(doc.get("data"), handle, indent=2, ensure_ascii=False)
        print(f"lsdb: wrote {len(docs)} doc(s) under {args.out}")
    else:
        print(json.dumps(result, indent=2))


def _as_docs(args, result) -> list:
    if args.cmd != "get":
        return result
    return [{"id": args.path.rsplit("/", 1)[-1], **result}] if result.get("exists") else []


def report_api_error(exc: LsdbApiError) -> None:
    status = "no HTTP reply" if exc.status is None else f"HTTP {exc.status}"
    body = exc.body if isinstance(exc.body, str) else json.dumps(exc.body, indent=2)
    print(f"lsdb: API ERROR ({status}) from the artifact db endpoint\nlsdb: reply body:\n{body}", file=sys.stderr)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        emit(args, run(args))
    except LsdbEnvError as exc:
        print(f"{ENV_MISSING_MSG}\nlsdb: ({exc})", file=sys.stderr)
        return 3
    except LsdbApiError as exc:
        report_api_error(exc)
        return 2
    except (ValueError, KeyError, OSError, LsdbError) as exc:
        print(f"lsdb: error: {exc}", file=sys.stderr)
        return 1
    return 0
