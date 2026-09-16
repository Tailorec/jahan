"""Phase 9: the completed attitude is sampled by the engine from the model's distribution, under the
population's seed, at a recorded completion temperature (ADR 0024)."""

import json

from simcore.population._project import COMPLETION_BATCH_SIZE, project
from simcore.ports.fake import FakeChat
from simcore.schemas import FieldOrigin, Population
from tests.boundary.population.test_projection import rows_of, synthetic, pack
from tests.study_builders import population_payload


class BatchRecorder:
    """Wraps the fake and counts how many batch calls projection makes, and how large they are."""

    def __init__(self, inner: FakeChat) -> None:
        self._inner = inner
        self.calls: list[int] = []

    def complete(self, requests):
        self.calls.append(len(requests))
        return self._inner.complete(requests)


def distribution_responder(weighted):
    def answer(messages, template_id) -> str:
        request = json.loads(messages[-1]["content"])
        return json.dumps({persona["persona_id"]: weighted for persona in request["personas"]}, sort_keys=True)

    return answer


def completed(personas, attribute="spend_band"):
    return [persona for persona in personas if persona.origins.get(attribute) is FieldOrigin.SYNTHESIZED]


def test_projection_submits_its_completion_batches_in_one_batch_call():
    source = synthetic(rows=400, spend_populated=0.0)
    brief = pack()
    recorder = BatchRecorder(FakeChat())
    rows = rows_of(source, brief)
    project(brief, rows, source, inference=recorder, population_seed=4021)
    expected_batches = -(-len(rows) // COMPLETION_BATCH_SIZE)  # one attribute's worth of batches, all of them together
    assert len(recorder.calls) == 1  # every batch rides one call, whoever needs completing
    assert recorder.calls[0] == expected_batches


def test_the_same_seed_and_distributions_reproduce_the_sample_and_the_distribution_is_recorded():
    source = synthetic(rows=200, spend_populated=0.0)
    brief = pack()
    rows = rows_of(source, brief)
    fake = FakeChat(distribution_responder([0.5, 0.5]))
    first = project(brief, rows, source, inference=fake, population_seed=4021)
    second = project(brief, rows, source, inference=FakeChat(distribution_responder([0.5, 0.5])), population_seed=4021)
    assert [p.attributes.get("spend_band") for p in first.personas] == [p.attributes.get("spend_band") for p in second.personas]
    done = completed(first.personas)
    assert done
    for persona in done:
        recorded = persona.completed_distributions["spend_band"]
        assert recorded.values == ("5_10", "10_20")
        assert recorded.probabilities == (0.5, 0.5)


def test_a_different_population_seed_samples_differently_from_the_same_distributions():
    source = synthetic(rows=200, spend_populated=0.0)
    brief = pack()
    rows = rows_of(source, brief)
    one = project(brief, rows, source, inference=FakeChat(distribution_responder([0.5, 0.5])), population_seed=4021)
    other = project(brief, rows, source, inference=FakeChat(distribution_responder([0.5, 0.5])), population_seed=917731)
    values_one = [persona.attributes["spend_band"] for persona in completed(one.personas)]
    values_other = [persona.attributes["spend_band"] for persona in completed(other.personas)]
    assert values_one != values_other  # a fair coin flips differently under a different seed
    assert len(set(values_one)) == 2 and len(set(values_other)) == 2  # and both seeds see both values


def test_completion_temperature_is_a_recorded_parameter_and_widening_it_widens_the_sample():
    source = synthetic(rows=400, spend_populated=0.0)
    brief = pack()
    rows = rows_of(source, brief)
    peaked = [0.98, 0.02]
    cold = project(brief, rows, source, inference=FakeChat(distribution_responder(peaked)), population_seed=4021, completion_temperature=1.0)
    hot = project(brief, rows, source, inference=FakeChat(distribution_responder(peaked)), population_seed=4021, completion_temperature=10.0)

    def off_mode(personas):
        values = [persona.attributes["spend_band"] for persona in completed(personas)]
        return sum(1 for value in values if value != "5_10") / len(values)

    assert off_mode(cold.personas) < 0.10 < off_mode(hot.personas)
    # the recorded distribution is the one it was drawn from: shaped by the temperature
    hot_recorded = completed(hot.personas)[0].completed_distributions["spend_band"]
    assert abs(hot_recorded.probabilities[1] - 0.4) < 0.15  # 0.02 ** (1/10) flattens towards a half
    assert cold.personas is not hot.personas


def test_a_population_survives_the_round_trip_carrying_its_completion_distributions():
    from simcore.population import build

    source = synthetic(rows=40, spend_populated=0.0)
    built = build(pack(), 40, 4021, coreset=source, inference=FakeChat(distribution_responder([0.5, 0.5])))
    dumped = built.population.model_dump_json()
    restored = Population.model_validate_json(dumped)
    assert restored == built.population
    done = [persona for persona in restored.personas if persona.origins.get("spend_band") is FieldOrigin.SYNTHESIZED]
    assert done and all(persona.completed_distributions["spend_band"].probabilities == (0.5, 0.5) for persona in done)


def test_a_distribution_that_misses_the_vocabulary_leaves_the_field_uncompleted():
    source = synthetic(rows=40, spend_populated=0.0)
    brief = pack()
    rows = rows_of(source, brief)

    def one_short(messages, template_id) -> str:
        request = json.loads(messages[-1]["content"])
        return json.dumps({persona["persona_id"]: [1.0] for persona in request["personas"]}, sort_keys=True)

    projection = project(brief, rows, source, inference=FakeChat(one_short, model_id="stub/only-1.0"), population_seed=4021)
    assert completed(projection.personas) == []
    assert projection.completion is None and projection.synthesized_share == 0.0


def test_through_the_real_client_one_malformed_persona_never_costs_its_batch_the_others():
    """Projection's tests ran on the fake, which never applies the client's schema validation. Through the
    real client, a schema requiring every persona's exact vector failed a batch of twenty-five for one bad
    answer: none of ninety fields was completed, and four calls became sixteen."""
    import httpx

    from simcore.inference import ExecutionSettings, InferenceClient
    from simcore.schemas import ModelPins

    model = "openrouter/camel-ai/persona-8b"
    sent = {"calls": 0}

    async def handler(request):
        sent["calls"] += 1
        body = json.loads(request.content)
        ask = next(json.loads(m["content"]) for m in body["messages"] if m["role"] == "user" and m["content"].startswith("{"))
        width = len(ask["values"])
        answer = {persona["persona_id"]: [1.0 / width] * width for persona in ask["personas"]}
        answer[ask["personas"][0]["persona_id"]] = [1.0]  # one persona per call answers with the wrong length
        payload = {"model": model, "choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 9, "completion_tokens": 9}}
        return httpx.Response(200, content=json.dumps(payload).encode())

    async def no_sleep(_seconds):
        return None

    client = InferenceClient(
        ModelPins.model_validate({"tier_a": model, "tier_b": "b/b", "embed": "e/e"}),
        ExecutionSettings(max_retries=0),
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )
    brief, source = pack(), synthetic()
    rows = rows_of(source, brief)
    missing = sum(1 for row in rows if "spend_band" not in row.values)
    projection = project(brief, rows, source, inference=client, population_seed=4021)
    done = len(completed(projection.personas))
    batches = -(-missing // COMPLETION_BATCH_SIZE)
    assert done == missing - batches  # exactly the one malformed persona per batch goes uncompleted
    assert sent["calls"] == 2 * batches  # one call per batch, one strict retry for its one leftover
