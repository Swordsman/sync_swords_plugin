"""Blob tests: offline against an in-memory fake db, plus a live round-trip when LSDB_TEST_URL is set."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import lsdb  # noqa: E402
from lsdb import blobs, catalog, reads, writes  # noqa: E402

URL = "https://claude.ai/artifact/5BYbd8nH9PUvdUkDqbxLpS"


class FakeDb:
    def __init__(self):
        self.docs, self.requests = {}, []

    def call(self, url, verb, args):
        self.requests.append((verb, len(json.dumps(args))))
        if verb == "batch":
            assert len(args["ops"]) <= 50
            for op in args["ops"]:
                assert len(json.dumps(op.get("data", {}), ensure_ascii=False).encode()) < 262144
                self.docs.pop(op["path"]) if op["op"] == "delete" else self.docs.update({op["path"]: op["data"]})
            return {}
        if verb == "set":
            self.docs[args["path"]] = args["data"]
            return {"version": 1}
        if verb == "update":
            self.docs.setdefault(args["path"], {}).update(args["data"])
            return {}
        if verb == "delete":
            self.docs.pop(args["path"], None)
            return {}
        if verb == "get":
            doc = self.docs.get(args["path"])
            return {"exists": doc is not None, "data": doc}
        if verb == "list":
            prefix = args["collection"] + "/"
            return {"docs": [{"id": p[len(prefix):], "data": d} for p, d in sorted(self.docs.items())
                             if p.startswith(prefix) and "/" not in p[len(prefix):]]}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    for module in (blobs, writes, catalog, reads):
        monkeypatch.setattr(module, "call", fake.call)
    return fake


TEXTS = ["", "short", "line\n" * 120_000, "\x01\x02\"\\" * 60_000, "日本語" * 70_000, "😀" * 50_000]


@pytest.mark.parametrize("text", TEXTS)
def test_split_parts_fit_and_rejoin(text):
    pieces = list(blobs.split_text(text))
    assert "".join(pieces) == text
    assert all(len(json.dumps({"text": p}, ensure_ascii=False).encode()) < 262144 for p in pieces)
    assert all(len(json.dumps(p)) <= blobs.PART_BYTES for p in pieces)


@pytest.mark.parametrize("text", TEXTS)
def test_round_trip(db, text):
    blobs.put_blob(URL, "k", text, meta={"a": 1})
    assert blobs.get_blob(URL, "k") == text
    assert db.docs["blobs/k"]["meta"] == {"a": 1}


def test_requests_respect_limits_and_manifest_is_last(db):
    blobs.put_blob(URL, "k", "x" * 3_000_000)
    assert max(size for verb, size in db.requests if verb == "batch") < 1 << 20
    writes_order = [p for p in db.docs]
    assert writes_order.index("blobs/k") > writes_order.index("blobs/k/parts/0000")


def test_shrinking_leaves_no_stale_parts(db):
    blobs.put_blob(URL, "k", "x" * 1_000_000)
    assert any(p.endswith("0004") for p in db.docs)
    blobs.put_blob(URL, "k", "tiny")
    assert [p for p in db.docs if "/parts/" in p] == ["blobs/k/parts/0000"]
    assert blobs.get_blob(URL, "k") == "tiny"


def test_corruption_and_missing_raise(db):
    blobs.put_blob(URL, "k", "x" * 500_000)
    db.docs["blobs/k/parts/0001"]["text"] = "y"
    with pytest.raises(lsdb.LsdbError, match="sha256"):
        blobs.get_blob(URL, "k")
    del db.docs["blobs/k/parts/0001"]
    with pytest.raises(lsdb.LsdbError, match="missing"):
        blobs.get_blob(URL, "k")
    with pytest.raises(KeyError):
        blobs.get_blob(URL, "nope")


def test_delete_removes_everything_and_bad_keys_rejected(db):
    blobs.put_blob(URL, "k", "x" * 500_000)
    blobs.delete_blob(URL, "k")
    assert not [p for p in db.docs if p.startswith("blobs/k")]
    for bad in ("a/b", "", ".x", "a b"):
        with pytest.raises(ValueError):
            blobs.put_blob(URL, bad, "t")


@pytest.mark.skipif(not os.environ.get("LSDB_TEST_URL"), reason="set LSDB_TEST_URL to a store artifact")
def test_live_blob_round_trip_and_shrink():
    url, key = os.environ["LSDB_TEST_URL"], "lsdb-test-blob"
    text = "".join(f"line {n} é日 \"q\"\n" for n in range(60_000))[:1_000_000]
    try:
        manifest = lsdb.put_blob(url, key, text, meta={"t": "live"})
        assert manifest["parts"] > 4
        assert lsdb.get_blob(url, key) == text
        lsdb.put_blob(url, key, "small")
        assert lsdb.get_blob(url, key) == "small"
        assert len(lsdb.list_all(url, f"blobs/{key}/parts")) == 1
        assert lsdb.get(url, "catalog/blobs")["exists"]
    finally:
        lsdb.delete_blob(url, key)
    assert lsdb.get(url, f"blobs/{key}")["exists"] is False
    assert lsdb.list_all(url, f"blobs/{key}/parts") == []
