"""The catalog: a `catalog` collection listing the store's collections, so a page can show what's there.

Each write registers its doc's collection once per process (one extra request the first time).
register() sets a description and a view hint the page renders by: json, text, table.
"""

from datetime import datetime, timezone

from .transport import LsdbApiError, call

CATALOG = "catalog"
VIEWS = ("json", "text", "table")
AUTO = True  # set lsdb.catalog.AUTO = False to stop automatic registration
_seen = set()


def catalog_id(collection: str) -> str:
    """Doc ids can't hold '/', so nested collection paths use '~' (projects/p1/maps -> projects~p1~maps)."""
    return collection.replace("/", "~")


def collection_of(path: str) -> str:
    return path.rsplit("/", 1)[0]


def register(url, collection: str, description=None, view=None, **extra) -> dict:
    """Create or merge the catalog entry for `collection`; returns the write reply."""
    if view is not None and view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}, not {view!r}")
    fields = {"path": collection, "updatedAt": _now(), **extra}
    fields |= {key: value for key, value in (("description", description), ("view", view)) if value is not None}
    _seen.add((url, collection))
    return _upsert(url, f"{CATALOG}/{catalog_id(collection)}", fields)


def note_write(url, path: str) -> None:
    """Called after every successful write: registers the doc's collection the first time it's seen."""
    collection = collection_of(path)
    if AUTO and collection != CATALOG and (url, collection) not in _seen:
        _seen.add((url, collection))
        _upsert(url, f"{CATALOG}/{catalog_id(collection)}", {"path": collection, "updatedAt": _now()})


def _upsert(url, path: str, fields: dict) -> dict:
    """Merge into an existing doc; create it when absent (update refuses missing docs)."""
    try:
        return call(url, "update", {"path": path, "data": fields})
    except LsdbApiError as exc:
        if exc.status not in (400, 404):  # the endpoint answers 404 not-found for a missing doc
            raise
        return call(url, "set", {"path": path, "data": fields, "replace": True})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
