"""The interface can ask how populated an attribute is before an audience is built on it."""

import json
import time
from pathlib import Path

from tests.boundary.ports.test_index_catalog import fake_cache
from tests.boundary.web.test_launch_any_study import _client


def _until_settled(client, retry=False, timeout=60.0):
    deadline = time.time() + timeout
    while True:
        body = client.get("/api/corpus/coverage" + ("?retry=true" if retry else "")).json()
        if body["state"] != "building" or time.time() > deadline:
            return body
        time.sleep(0.05)


def test_coverage_is_counted_in_the_background_and_then_served(tmp_path):
    cache = fake_cache(tmp_path)
    client = _client(tmp_path, corpus_dir=cache)
    body = _until_settled(client)
    assert body["state"] == "ready" and body["available"] is True
    assert body["totals"] == {"gss": 1, "stackoverflow": 2, "synthetic": 1, "wiki": 1}
    age = body["attributes"]["age_bracket"]
    assert age["recorded"] == {"present": 4, "total": 4, "share": 1.0}
    assert age["by_source"]["stackoverflow"]["share"] == 1.0
    assert set(body["attributes"]) >= {"age_bracket", "region", "sex"}


def test_a_second_ask_is_answered_from_the_saved_count(tmp_path):
    cache = fake_cache(tmp_path)
    client = _client(tmp_path, corpus_dir=cache)
    first = _until_settled(client)
    again = client.get("/api/corpus/coverage").json()
    assert again == first, "a saved count is served at once, not recounted"


def test_coverage_names_no_filesystem_path(tmp_path):
    cache = fake_cache(tmp_path)
    text = json.dumps(_until_settled(_client(tmp_path, corpus_dir=cache)))
    assert str(tmp_path) not in text and ".parquet" not in text


def test_no_corpus_is_a_statement_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "nothing-here"))
    body = _client(tmp_path, corpus_dir=tmp_path / "absent").get("/api/corpus/coverage")
    assert body.status_code == 200 and body.json() == {"available": False, "state": "no_corpus"}


def test_a_corpus_with_no_cached_shard_says_so(tmp_path):
    cache = fake_cache(tmp_path)
    for shard in (cache / "data").glob("*.parquet"):
        shard.unlink()
    body = _client(tmp_path, corpus_dir=cache).get("/api/corpus/coverage").json()
    assert body == {"available": False, "state": "no_shards"}


def test_a_count_that_fails_says_why_and_can_be_asked_again(tmp_path):
    cache = fake_cache(tmp_path)
    shard = cache / "data" / "persona-1m-0000.parquet"
    original = shard.read_bytes()
    shard.write_bytes(original + b"corrupt")
    client = _client(tmp_path, corpus_dir=cache)
    body = _until_settled(client)
    assert body["state"] == "failed" and "does not match" in body["detail"]
    assert str(tmp_path) not in json.dumps(body) and ".parquet" not in json.dumps(body)

    shard.write_bytes(original)
    assert _until_settled(client, retry=True)["state"] == "ready"
