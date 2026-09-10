from hypothesis import given
from hypothesis import strategies as st

from tests.demo_contracts import DemoBrief, DemoRunConfig

word = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)
hex_digest = st.from_regex(r"[0-9a-f]{64}", fullmatch=True)
run_identifier = st.from_regex(r"[0-9a-z]{8,16}", fullmatch=True)
unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@given(
    title=word,
    claims=st.lists(word, min_size=0, max_size=5),
    filters=st.dictionaries(word, word, max_size=4),
    mix=st.dictionaries(word, unit, min_size=1, max_size=4),
    fetched_at=word,
)
def test_demo_brief_round_trips_over_generated_values(title, claims, filters, mix, fetched_at):
    brief = DemoBrief(
        title=title,
        claims=tuple(claims),
        target_filters=filters,
        audience_mix=mix,
        fetched_at=fetched_at,
    )
    assert DemoBrief.model_validate(brief.model_dump(mode="json")) == brief
    assert DemoBrief.model_validate_json(brief.model_dump_json()) == brief


@given(
    run_identifier=run_identifier,
    title=word,
    seeds=st.lists(st.integers(min_value=0, max_value=2**32 - 1), min_size=0, max_size=4),
    population_hash=hex_digest,
    observed_cost=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_demo_run_config_round_trips_over_generated_values(
    run_identifier, title, seeds, population_hash, observed_cost
):
    brief = DemoBrief(
        title=title,
        claims=("claim_one",),
        target_filters={},
        audience_mix={"gym_regulars": 1.0},
        fetched_at="t",
    )
    config = DemoRunConfig(
        run_id=run_identifier,
        brief=brief,
        population_hash=population_hash,
        seeds=tuple(seeds),
        observed_cost=observed_cost,
    )
    assert DemoRunConfig.model_validate(config.model_dump(mode="json")) == config
    assert DemoRunConfig.model_validate_json(config.model_dump_json()) == config
