"""Offline tests for lsdb, plus one live round-trip that runs only when LSDB_TEST_URL names a store."""

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import lsdb  # noqa: E402
from lsdb import cli, reads, transport  # noqa: E402

URL = "https://claude.ai/artifact/5BYbd8nH9PUvdUkDqbxLpS"


def test_artifact_uuid_forms():
    known = "0f3c2a4e-1b2c-4d5e-8f90-1234567890ab"
    assert lsdb.artifact_uuid(f"https://claude.ai/code/artifact/{known.upper()}") == known
    assert uuid.UUID(lsdb.artifact_uuid(URL))
    with pytest.raises(ValueError):
        lsdb.artifact_uuid("https://claude.ai/chat/abc")


def test_query_args_map_symbols_and_default_limit():
    args = reads._query_args("c", [("n", ">=", 2)], ("n", "desc"), None)
    assert args == {"collection": "c", "where": [{"field": "n", "op": "gte", "value": 2}],
                    "orderBy": {"field": "n", "direction": "desc"}, "limit": 1000}
    with pytest.raises(ValueError):
        reads._where_clause("n", "~", 1)


def test_batch_validation():
    assert lsdb.write_op("set", "c/a", {"x": 1}) == {"op": "set", "path": "c/a", "data": {"x": 1}, "replace": True}
    with pytest.raises(ValueError):
        lsdb.batch(URL, [("delete", "c/a"), ("delete", "c/a")])
    with pytest.raises(ValueError):
        lsdb.batch(URL, [("delete", f"c/{n}") for n in range(51)])


def test_exit_codes(monkeypatch, capsys):
    monkeypatch.delenv(transport.SDK_URL_ENV, raising=False)
    assert cli.main(["get", URL, "c/a"]) == 3
    assert "ArtifactData" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stop:
        cli.main(["bogus"])
    assert stop.value.code == 1


def _flaky(statuses, calls):
    def fake(url, body, token):
        calls.append(1)
        status = statuses[len(calls) - 1]
        if status != 200:
            raise transport.LsdbApiError(status, "x")
        return 200, b"{}"
    return fake


@pytest.mark.parametrize("statuses, attempts, ok", [
    ([503, None, 200], 3, True), ([429, 429, 429], 3, False), ([400], 1, False)])
def test_retry(monkeypatch, statuses, attempts, ok):
    calls = []
    monkeypatch.setattr(transport, "_post_once", _flaky(statuses, calls))
    if ok:
        assert transport.post("u", b"", "t", sleep=lambda s: None) == (200, b"{}")
    else:
        with pytest.raises(transport.LsdbApiError):
            transport.post("u", b"", "t", sleep=lambda s: None)
    assert len(calls) == attempts


def test_out_writes_files_and_one_line(monkeypatch, tmp_path, capsys):
    docs = [{"id": "a", "data": {"x": 1}}, {"id": "b", "data": {"x": 2}}]
    monkeypatch.setattr(reads, "list_all", lambda url, collection: docs)
    assert cli.main(["list", URL, "p/q/r", "--out", str(tmp_path)]) == 0
    assert capsys.readouterr().out.count("\n") == 1
    assert json.loads((tmp_path / "p" / "q" / "r" / "b.json").read_text()) == {"x": 2}


@pytest.mark.skipif(not os.environ.get("LSDB_TEST_URL"), reason="set LSDB_TEST_URL to a store artifact")
def test_live_round_trip():
    url, path = os.environ["LSDB_TEST_URL"], "lsdb-test/doc"
    version = lsdb.set_doc(url, path, {"text": "hello world", "n": 1})["version"]
    lsdb.update_doc(url, path, {"n": 2}, if_version=version)
    lsdb.str_replace(url, path, "text", "o", "0", replace_all=True)
    assert lsdb.get(url, path)["data"] == {"text": "hell0 w0rld", "n": 2}
    assert [d["id"] for d in lsdb.query(url, "lsdb-test", where=[("n", "==", 2)])] == ["doc"]
    lsdb.batch(url, [("set", "lsdb-test/b", {"n": 3}), ("delete", path)])
    assert [d["id"] for d in lsdb.list_all(url, "lsdb-test")] == ["b"]
    lsdb.delete_doc(url, "lsdb-test/b")
    assert lsdb.list_all(url, "lsdb-test") == []
