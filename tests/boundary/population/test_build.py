"""`build`: the whole path, its determinism, and the seams that keep it honest."""

import numpy as np
import pytest

from simcore.population import BuiltPopulation, assess, build
from simcore.population._streams import spawn
from simcore.ports.fake import FakeChat, FakeEmbed
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import (
    BriefPack,
    CommunityThresholds,
    DistributionThresholds,
    FieldOrigin,
    GateFailure,
    GraphParameters,
    Population,
    PopulationParameters,
)
from tests.study_builders import pack_payload

MODEL = "openrouter/camel-ai/persona-8b"


def synthetic(rows: int = 5000, seed: int = 11, *, spend_populated: float = 1.0) -> SyntheticCoresetSource:
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
                "spend_band": AttributeShape(("5_10", "10_20"), populated=spend_populated),
            },
            rows=rows,
        ),
        seed=seed,
    )


def pack() -> BriefPack:
    return BriefPack.model_validate(pack_payload())


def built(count: int = 120, **kwargs) -> BuiltPopulation:
    kwargs.setdefault("inference", FakeChat())
    return build(pack(), count, 4021, coreset=synthetic(), **kwargs)


def test_building_returns_the_validated_population_and_its_embedding_array():
    result = built(120, embed=FakeEmbed(dim=8))
    assert isinstance(result.population, Population)
    assert result.embeddings is not None and result.embeddings.shape == (120, 8)
    assert result.embeddings.dtype == np.float32
    assert [persona.embedding.index for persona in result.population.personas] == list(range(120))
    assert {persona.embedding.dim for persona in result.population.personas} == {8}


def test_the_built_population_validates_against_its_brief_and_ontology():
    population = built().population
    assert population.pack == pack()
    ontology = population.pack.ontology
    for persona in population.personas:
        assert set(persona.conditioning) == set(ontology.conditioning_set)
        assert set(persona.origins) == persona.projected_attributes
        assert set(persona.baseline_beliefs.claim_credence) == {claim.id for claim in population.pack.brief.claims}
    assert Population.model_validate(population.model_dump(mode="json")) == population


def test_the_same_brief_size_and_seed_build_an_identical_population_twice_under_a_deterministic_port():
    first = built()
    second = built()
    assert first.population.population_hash == second.population.population_hash
    assert first.population.model_dump(mode="json") == second.population.model_dump(mode="json")


def test_three_independent_streams_are_spawned_from_the_population_seed():
    seeds = spawn(4021)
    assert len(seeds) == 3 and len(set(seeds)) == 3
    assert spawn(4021) == seeds


def test_changing_one_stages_draw_does_not_shift_anothers():
    base = built()
    different_graph = built(parameters=PopulationParameters(graph=GraphParameters(ring_degree=6)))
    assert base.population.manifest.persona_ids == different_graph.population.manifest.persona_ids
    assert base.population.graph.graph_hash != different_graph.population.graph.graph_hash

    different_communities = built(parameters=PopulationParameters(communities=CommunityThresholds(resolutions=(0.5, 1.0, 1.5))))
    assert base.population.manifest.persona_ids == different_communities.population.manifest.persona_ids
    assert base.population.graph.graph_hash == different_communities.population.graph.graph_hash


def test_a_population_without_embeddings_carries_none_and_the_array_is_never_in_the_contract():
    result = built(100)
    assert result.embeddings is None
    assert all(persona.embedding is None for persona in result.population.personas)
    assert "embeddings" not in result.population.model_dump()
    assert "embedding" not in result.population.model_dump()


class RecordingPatches:
    def __init__(self) -> None:
        self.called = False

    def patches(self, personas):
        self.called = True
        return {}


def test_the_no_op_patch_seam_is_applied_and_changes_nothing():
    recorder = RecordingPatches()
    patched = built(patches=recorder)
    assert recorder.called
    assert patched.population.population_hash == built().population.population_hash


class OnePatch:
    def patches(self, personas):
        return {personas[0].persona_id: {"age": "45_54"}}


def test_a_patch_is_applied_and_marked_calibrated():
    result = built(patches=OnePatch())
    assert result.population.personas[0].origins["age"] is FieldOrigin.CALIBRATED
    assert result.population.personas[0].conditioning["age"] == "45_54"


def starved(rows: int = 4000, seed: int = 11) -> SyntheticCoresetSource:
    """Almost nobody trains, so the gym audience cannot fill; spend_band is sparse, so building would complete it."""
    return SyntheticCoresetSource(
        SyntheticShape(
            {
                "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
                "sex": AttributeShape(("female", "male")),
                "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly"), weights=(0.97, 0.02, 0.01)),
                "diet_protein_focus": AttributeShape(("low", "medium", "high")),
                "spend_band": AttributeShape(("5_10", "10_20"), populated=0.5),
            },
            rows=rows,
        ),
        seed=seed,
    )


def test_a_failing_draw_is_refused_before_any_model_is_called():
    """A starved study once made ten completion calls, built its graph and found its communities before
    being refused on gates its draw had already failed."""
    fake = FakeChat()
    with pytest.raises(GateFailure, match="before any model was called"):
        build(pack(), 1000, 4021, coreset=starved(), inference=fake)
    assert fake.calls == []


def test_assess_and_build_agree_about_the_same_draw():
    assert assess(pack(), 1000, 4021, coreset=starved()).overall is False
    with pytest.raises(GateFailure):
        build(pack(), 1000, 4021, coreset=starved(), inference=FakeChat())


def test_completion_cannot_rescue_a_sparse_attribute_that_fails_its_gate():
    """A failing spend_band gate rejected a fully populated study but vanished from a half-populated one,
    because it was dropped after completion touched spend_band. The verdict now comes first."""
    strict = PopulationParameters(distribution_gates=DistributionThresholds(significance_level=0.999999))
    fake = FakeChat()
    with pytest.raises(GateFailure) as raised:
        build(pack(), 200, 4021, coreset=synthetic(spend_populated=0.5), inference=fake, parameters=strict)
    assert "spend_band" in str(raised.value)
    assert fake.calls == []


def test_a_population_carries_only_gates_true_of_its_own_values():
    result = build(pack(), 200, 4021, coreset=synthetic(spend_populated=0.5), inference=FakeChat())
    population = result.population
    assert population.manifest.synthesized_share > 0.0
    for outcome in population.gate_report.results:
        attribute = getattr(outcome, "attribute", None)
        if attribute is not None:
            assert all(
                persona.origins[attribute] is FieldOrigin.GROUNDED for persona in population.personas if attribute in persona.origins
            )


def test_a_built_population_carries_its_assortativity_beside_its_gates():
    """Assortativity was once returned beside the population and lost the moment it left memory."""
    result = built()
    report = result.population.gate_report
    assert report.assortativity and set(report.assortativity) <= set(result.population.pack.ontology.attribute_domains)
    assert all(-1.0 <= value <= 1.0 for value in report.assortativity.values())
    assert report.audience_assortativity is not None
    assert not hasattr(result, "assortativity")
    stored = Population.model_validate(result.population.model_dump(mode="json"))
    assert stored.gate_report.assortativity == report.assortativity
