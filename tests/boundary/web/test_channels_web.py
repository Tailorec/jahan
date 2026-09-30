"""M15 phase 7: the interface launches any channel combination, and the engine says what waves cost.

The page derives nothing (ADR 0045): the wave ticks and the answers they take come from the
engine, and whether the feed's ranking model answers is asked of the engine, which holds the key.
"""

import json as json_module

import httpx

from tests.boundary.web.test_launch_any_study import REAL, _client, _flag, endpoint, launched  # noqa: F401


def test_the_engine_lists_the_waves_and_the_answers_they_take(tmp_path):
    client = _client(tmp_path)
    body = client.post("/api/waves", json={"survey_every": 2, "horizon": 7, "n": 40, "replicates": 2}).json()
    assert body == {"ticks": [0, 2, 4, 6], "answers": 40 * 4 * 2}
    assert client.post("/api/waves", json={"survey_every": 0, "horizon": 7, "n": 40}).status_code == 422


def test_a_real_feed_study_names_its_ranking_model_and_it_travels_to_the_command(tmp_path, endpoint, launched):
    client = _client(tmp_path)
    refused = client.post("/api/runs", json={**REAL, "channels": ["social_feed"]})
    assert refused.status_code == 422 and "recsys_embed_model" in refused.text
    started = client.post("/api/runs", json={**REAL, "channels": ["social_feed", "wom"], "recsys_embed_model": "twhin-bert-base"})
    assert started.status_code == 202, started.text
    (argv,) = launched
    assert _flag(argv, "--recsys-embed-model") == "twhin-bert-base"
    assert _flag(argv, "--channels") == "social_feed,wom"


def test_a_forum_study_needs_no_ranking_model(tmp_path, endpoint, launched):
    started = _client(tmp_path).post("/api/runs", json={**REAL, "channels": ["forum"]})
    assert started.status_code == 202, started.text
    assert "--recsys-embed-model" not in launched[0]


def test_the_ranking_model_check_says_whether_it_answers_and_never_shows_the_key(tmp_path, monkeypatch):
    seen: list[dict] = []

    def post(url, *, json, headers, timeout):
        seen.append({"url": url, "model": json["model"], "auth": headers.get("authorization")})
        request = httpx.Request("POST", url)
        if json["model"] == "twhin-bert-base":
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}, request=request)
        return httpx.Response(400, json={"error": "no such model"}, request=request)

    monkeypatch.setattr("simcore.inference._probe.httpx.post", post)
    monkeypatch.setenv("SIMCORE_INFERENCE_BASE_URL", "http://gateway.test:4000/v1")
    monkeypatch.setenv("SIMCORE_INFERENCE_API_KEY", "sk-secret")
    client = _client(tmp_path)
    good = client.post("/api/recsys/check", json={"model": "twhin-bert-base"}).json()
    bad = client.post("/api/recsys/check", json={"model": "nothing-here"}).json()
    assert good == {"model": "twhin-bert-base", "reachable": True, "detail": None}
    assert bad["reachable"] is False and "nothing-here" in bad["detail"]
    assert "sk-secret" not in json_module.dumps([good, bad])
    assert seen[0] == {"url": "http://gateway.test:4000/v1/embeddings", "model": "twhin-bert-base", "auth": "Bearer sk-secret"}


def test_without_an_endpoint_the_check_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMCORE_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    body = _client(tmp_path).post("/api/recsys/check", json={"model": "twhin-bert-base"}).json()
    assert body["reachable"] is False and "no inference endpoint" in body["detail"]
