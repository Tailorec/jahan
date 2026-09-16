"""Phase 6: a persistent cache that makes a re-run cheap without making replicates identical.

A hit carries the cache route and bills nothing; a sampled answer belongs to one replicate; a
temperature-zero call may be shared. Changing the served model, the template or any request byte
never serves an old answer, and deleting the cache changes what a run pays, never what it records."""

import json
from pathlib import Path

import httpx
import pytest

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import (
    ChatRequest,
    Completion,
    CostSource,
    FrozenDict,
    InferenceRole,
    InferenceRoute,
    ModelPins,
    SampleKey,
)
from tests.boundary.inference.test_scale import FakeTime, PINS, TIER_A

FALLBACK = "openrouter/qwen/qwen-2.5-7b-instruct"
TEMPLATE_HASHES = {"persona_turn": "ab" * 32}


def priced_answer(model: str = TIER_A) -> bytes:
    return json.dumps(
        {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": f"{model} says yes"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "cost": 0.5},
        }
    ).encode()


def sampled(seed: int, persona: str = "p-1", template_id: str = "persona_turn") -> ChatRequest:
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=(FrozenDict({"role": "user", "content": "how would you rate it?"}),),
        temp=0.7,
        max_tokens=16,
        template_id=template_id,
        sample=SampleKey(world_seed=seed, persona_id=persona, tick=2, seq=0),
    )


def unsampled(index: int = 0) -> ChatRequest:
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=(FrozenDict({"role": "user", "content": f"static question {index}"}),),
        temp=0.0,
        max_tokens=16,
        template_id="persona_turn",
    )


class Endpoint:
    """A scripted gateway: counts every call it actually receives."""

    def __init__(self, body: bytes | None = None) -> None:
        self.calls: list[dict] = []
        self._body = body

    @property
    def sent(self) -> int:
        return len(self.calls)

    def transport(self) -> httpx.MockTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(json.loads(request.content))
            return httpx.Response(200, content=self._body or priced_answer())

        return httpx.MockTransport(handler)


def cached_client(root: Path, endpoint: Endpoint, pins: ModelPins = PINS, *, template_hashes=TEMPLATE_HASHES, **settings) -> InferenceClient:
    time = FakeTime()
    return InferenceClient(
        pins,
        ExecutionSettings(base_url="http://gateway.test/v1", max_concurrency=2, cache_dir=root, **settings),
        transport=endpoint.transport(),
        clock=time.clock,
        sleep=time.sleep,
        template_hashes=template_hashes,
    )


def test_a_rerun_of_the_same_seed_is_served_from_the_cache_at_the_cache_route_and_zero_cost(tmp_path):
    endpoint = Endpoint()
    first = cached_client(tmp_path, endpoint).complete([sampled(4021)])[0]
    assert isinstance(first, Completion) and endpoint.sent == 1
    second = cached_client(tmp_path, endpoint).complete([sampled(4021)])[0]
    assert endpoint.sent == 1  # the second process never reached the gateway
    assert isinstance(second, Completion)
    assert second.text == first.text and second.prompt_hash == first.prompt_hash
    assert second.cost.route is InferenceRoute.CACHE
    assert second.cost.cost == 0.0 and second.cost.cost_source is CostSource.CACHE
    assert second.cost.input_tokens == 10 and second.cost.output_tokens == 3  # it still states what it drew


def test_two_replicate_seeds_never_receive_the_same_cached_sample(tmp_path):
    endpoint = Endpoint()
    a = cached_client(tmp_path, endpoint).complete([sampled(4021)])[0]
    b = cached_client(tmp_path, endpoint).complete([sampled(917731)])[0]
    assert endpoint.sent == 2  # neither draw rode the other's answer
    assert isinstance(a, Completion) and isinstance(b, Completion)
    assert a.cost.route is InferenceRoute.PRIMARY and b.cost.route is InferenceRoute.PRIMARY
    # and the second run of each still misses its sibling's entry
    cached_client(tmp_path, endpoint).complete([sampled(4021)])
    assert endpoint.sent == 2


def test_a_temperature_zero_call_is_shared_across_replicates(tmp_path):
    endpoint = Endpoint()
    first = cached_client(tmp_path, endpoint)
    second = cached_client(tmp_path, endpoint)
    a = first.complete([unsampled()])[0]
    b = second.complete([unsampled()])[0]
    assert isinstance(a, Completion) and isinstance(b, Completion)
    assert endpoint.sent == 1
    assert b.cost.route is InferenceRoute.CACHE and b.cost.cost == 0.0


def test_a_changed_served_model_template_or_request_byte_never_serves_an_old_answer(tmp_path):
    endpoint = Endpoint()
    client = cached_client(tmp_path, endpoint)
    client.complete([unsampled(0)])
    assert endpoint.sent == 1
    client.complete([unsampled(1)])  # different request bytes
    assert endpoint.sent == 2
    aliased = ModelPins.model_validate(
        {"tier_a": {"model_id": TIER_A, "serves": [TIER_A, "substituted/quant"]}, "tier_b": PINS.tier_b, "embed": PINS.embed}
    )
    # a pin whose accepted served identifiers moved keys elsewhere: the old answer is not offered
    cached_client(tmp_path, endpoint, pins=aliased).complete([unsampled(0)])
    assert endpoint.sent == 3
    # a template whose hash moved does too — same id, same bytes, stale content
    moved = cached_client(tmp_path, endpoint, template_hashes={"persona_turn": "cd" * 32})
    moved.complete([unsampled(0)])
    assert endpoint.sent == 4
    client.complete([unsampled(0)])  # unchanged pin, template and request: still a hit
    assert endpoint.sent == 4


def test_the_cache_survives_a_new_process_and_lives_outside_the_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMCORE_CACHE_DIR", str(tmp_path))
    settings = ExecutionSettings.from_environment(dict(**dict(__import__("os").environ)))
    root = Path(settings.cache_dir)
    assert tmp_path in root.parents or root == tmp_path / "simcore" / "inference"
    endpoint = Endpoint()
    cached_client(root, endpoint).complete([sampled(7)])
    fresh = InferenceClient(
        PINS,
        ExecutionSettings(base_url="http://gateway.test/v1", cache_dir=root),
        transport=endpoint.transport(),
        template_hashes=TEMPLATE_HASHES,
    )
    outcome = fresh.complete([sampled(7)])[0]
    assert isinstance(outcome, Completion) and outcome.cost.route is InferenceRoute.CACHE
    assert endpoint.sent == 1
    assert root.is_absolute() and Path.cwd() not in root.parents  # never inside the repository


def test_deleting_the_cache_changes_cost_and_never_changes_a_result(tmp_path):
    endpoint = Endpoint()
    root = tmp_path / "cache"
    warm = cached_client(root, endpoint).complete([unsampled(0)])[0]
    import shutil

    shutil.rmtree(root)
    assert cached_client(root, endpoint).stats is not None
    again_endpoint = Endpoint()
    cold = cached_client(root, again_endpoint).complete([unsampled(0)])[0]
    assert cold.text == warm.text and cold.prompt_hash == warm.prompt_hash
    assert warm.cost.route is InferenceRoute.PRIMARY and cold.cost.route is InferenceRoute.PRIMARY
    # with the cache present the second run pays nothing; without it, it pays again in full
    warm_again = cached_client(root, Endpoint()).complete([unsampled(0)])[0]
    assert warm_again.cost.route is InferenceRoute.CACHE and warm_again.cost.cost == 0.0
    assert cold.cost.cost == 0.5


def test_a_baseline_rerun_of_the_same_seeds_hits_the_cache_at_least_thirty_percent(tmp_path):
    endpoint = Endpoint()
    requests = [unsampled(index) for index in range(200)]
    warm = cached_client(tmp_path, endpoint)
    warm.complete(requests)
    assert endpoint.sent == 200
    replay = cached_client(tmp_path, endpoint)
    outcomes = replay.complete(requests)
    hits = sum(1 for outcome in outcomes if outcome.cost.cache_hit)
    assert hits / len(outcomes) >= 0.30  # and a seed-for-seed replay should be total: it is 1.0
    assert hits == 200
