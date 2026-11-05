"""Read verbs: get, list, query (with cursor following)."""

from .transport import LsdbError, call

MAX_LIMIT = 1000
# The server takes the word operators; the symbols are accepted and mapped.
OP_WORDS = {"==": "eq", "!=": "ne", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte"}
SERVER_OPS = ("eq", "ne", "in", "not-in", "lt", "lte", "gt", "gte", "array-contains")


def get(url, path: str) -> dict:
    """One document ("collection/doc"). Reply: {exists, data, version, updatedAt, ...}."""
    return call(url, "get", {"path": path})


def list_docs(url, collection: str, cursor=None) -> dict:
    """One page of a collection. Reply: {docs: [{id, data, version, updatedAt}], nextCursor?}."""
    return call(url, "list", {"collection": collection, **({"cursor": cursor} if cursor else {})})


def list_all(url, collection: str) -> list:
    """Every document in a collection, following nextCursor to the last page."""
    return _collect(lambda cursor: list_docs(url, collection, cursor))


def query(url, collection: str, where=None, order_by=None, limit=None) -> list:
    """Server-side query; returns the matching docs.

    where:    up to 10 (field, op, value) triples; op is a SERVER_OPS word or an OP_WORDS symbol.
    order_by: a field, or (field, "asc"|"desc"). An ordered query returns ONE page, so at most
              `limit` docs (1000 when limit is None).
    limit:    1-1000. Unordered queries follow nextCursor until `limit` docs or the last page.
    """
    args = _query_args(collection, where, order_by, limit)
    if order_by is not None:
        return call(url, "query", args).get("docs", [])
    return _collect(lambda cursor: call(url, "query", {**args, **({"cursor": cursor} if cursor else {})}), limit)


def _collect(fetch_page, limit=None) -> list:
    docs, cursor, seen = [], None, set()
    while True:
        page = fetch_page(cursor)
        docs.extend(page.get("docs", []))
        cursor = page.get("nextCursor")
        if not cursor or (limit is not None and len(docs) >= limit):
            return docs[:limit]
        if cursor in seen:
            raise LsdbError("pagination did not advance: the server repeated a cursor")
        seen.add(cursor)


def _query_args(collection, where, order_by, limit) -> dict:
    args = {"collection": collection}
    if where:
        args["where"] = [_where_clause(*clause) for clause in where]
    if order_by is not None:
        args["orderBy"] = _order_by(order_by)
    if limit is not None:
        args["limit"] = _check_limit(limit)
    elif order_by is not None:
        args["limit"] = MAX_LIMIT
    return args


def _where_clause(field: str, op: str, value) -> dict:
    word = OP_WORDS.get(op, op)
    if word not in SERVER_OPS:
        raise ValueError(f"unknown where operator {op!r}; use one of: {' '.join(SERVER_OPS + tuple(OP_WORDS))}")
    return {"field": field, "op": word, "value": value}


def _order_by(order_by) -> dict:
    field, direction = (order_by, None) if isinstance(order_by, str) else tuple(order_by)
    if direction not in (None, "asc", "desc"):
        raise ValueError(f"order direction must be 'asc' or 'desc', not {direction!r}")
    return {"field": field, **({"direction": direction} if direction else {})}


def _check_limit(limit) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}, not {limit!r}")
    return limit
