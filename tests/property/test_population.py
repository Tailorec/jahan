import copy

import pytest
from pydantic import ValidationError

from simcore import schemas
from simcore.schemas import (
    CategoricalGateResult,
    Community,
    CommunityThresholds,
    DistributionThresholds,
    GateReference,
    GateReport,
    GraphGateResult,
    GraphParameters,
    GraphThresholds,
    OrdinalGateResult,
    Persona,
    Population,
    PopulationManifest,
    PopulationParameters,
    Relaxation,
    SocialEdge,
    SocialGraph,
    canonical_hash,
)
from tests.study_builders import PERSONA_IDS, beliefs_payload, gate_report_payload, pack_payload, persona_payload, population_payload


def categorical(**overrides):
    return {"kind": "categorical", "attribute": "age", "chi_square": 3.2, "degrees_of_freedom": 4, "p_value": 0.52, **overrides}


def ordinal(**overrides):
    return {"kind": "ordinal", "attribute": "exercise_frequency", "ks_statistic": 0.1, "ks_similarity": 0.9, **overrides}


def graph(**overrides):
    return {"kind": "graph", "check": "clustering", "measured": 0.5, "threshold": 0.3, **overrides}


def relaxation(**overrides):
    return {
        "audience": "gym_regulars",
        "rung": "widen_ordinal",
        "attribute": "exercise_frequency",
        "authored": "3_plus_weekly",
        "applied": "weekly",
        "rows_before": 10,
        "rows_after": 30,
        "share_achieved": 0.8,
        **overrides,
    }


# --- gate results ----------------------------------------------------------------------------


def test_gate_results_dispatch_on_kind_alone():
    first, second = GateReport.model_validate(gate_report_payload()).results
    assert isinstance(first, OrdinalGateResult)
    assert isinstance(second, CategoricalGateResult)


def test_gate_results_carry_no_nullable_twin_fields():
    assert not {"chi_square", "degrees_of_freedom", "p_value"} & set(OrdinalGateResult.model_fields)
    assert not {"ks_statistic", "ks_similarity"} & set(CategoricalGateResult.model_fields)


def test_gate_results_do_not_self_report_attribute_origin():
    for model in (CategoricalGateResult, OrdinalGateResult):
        assert "attribute_origin" not in model.model_fields


@pytest.mark.parametrize(
    ("p_value", "passed"), [(0.52, True), (0.050001, True), (0.05, False), (0.0001, False)], ids=["clear", "just-above", "at-level", "far-below"]
)
def test_categorical_verdict_is_computed_from_the_p_value(p_value, passed):
    assert CategoricalGateResult.model_validate(categorical(p_value=p_value)).passed is passed


@pytest.mark.parametrize(
    ("statistic", "passed"), [(0.1, True), (0.2, True), (0.25, False), (0.9, False)], ids=["clear", "at-threshold", "below", "far-below"]
)
def test_ordinal_verdict_is_computed_from_the_similarity(statistic, passed):
    result = OrdinalGateResult.model_validate(ordinal(ks_statistic=statistic, ks_similarity=1.0 - statistic))
    assert result.passed is passed


def test_thresholds_are_carried_on_the_result_and_decide_the_verdict():
    strict = CategoricalGateResult.model_validate(categorical(p_value=0.08, significance_level=0.1))
    assert (strict.significance_level, strict.passed) == (0.1, False)
    lenient = OrdinalGateResult.model_validate(ordinal(ks_statistic=0.3, ks_similarity=0.7, similarity_threshold=0.6))
    assert lenient.passed is True


@pytest.mark.parametrize(
    "payload",
    [categorical(p_value=0.0001, passed=True), ordinal(ks_statistic=0.9, ks_similarity=0.1, passed=True), categorical(passed=False)],
    ids=["failing-categorical-claimed-passed", "failing-ordinal-claimed-passed", "passing-claimed-failed"],
)
def test_supplied_verdict_contradicting_the_statistic_refused(payload):
    model = CategoricalGateResult if payload["kind"] == "categorical" else OrdinalGateResult
    with pytest.raises(ValidationError, match="computed"):
        model.model_validate(payload)


def test_ordinal_similarity_must_be_one_minus_statistic():
    with pytest.raises(ValidationError, match="one minus"):
        OrdinalGateResult.model_validate(ordinal(ks_statistic=0.08, ks_similarity=0.5))
    with pytest.raises(ValidationError):
        OrdinalGateResult.model_validate(ordinal(ks_statistic=1.2, ks_similarity=-0.2))


# --- gate report -----------------------------------------------------------------------------


def test_report_overall_is_computed_and_serialized():
    report = GateReport.model_validate(gate_report_payload())
    assert report.overall is True
    assert report.model_dump()["overall"] is True
    failing = gate_report_payload(results=[ordinal(), categorical(p_value=0.01)])
    assert GateReport.model_validate(failing).overall is False


def test_report_round_trips_with_its_computed_verdicts():
    report = GateReport.model_validate(gate_report_payload())
    dumped = report.model_dump(mode="json")
    assert dumped["results"][0]["passed"] is True
    assert GateReport.model_validate(dumped) == report
    assert GateReport.model_validate_json(report.model_dump_json()) == report


def test_report_claiming_a_false_overall_refused():
    with pytest.raises(ValidationError, match="computed"):
        GateReport.model_validate({**gate_report_payload(), "overall": False})


def test_report_without_results_refused():
    with pytest.raises(ValidationError):
        GateReport.model_validate(gate_report_payload(results=[]))


def test_report_with_two_results_for_one_attribute_refused():
    with pytest.raises(ValidationError, match="more than one gate result"):
        GateReport.model_validate(gate_report_payload(results=[categorical(), categorical(p_value=0.01)]))


def test_report_source_mix_sums_to_one():
    with pytest.raises(ValidationError, match="sum to one"):
        GateReport.model_validate(gate_report_payload(source_mix={"gss": 0.7, "synthetic": 0.2}))


def test_gate_report_records_an_achieved_mix_that_sums_to_one():
    recorded = GateReport.model_validate(
        gate_report_payload(achieved_mix={"gym_regulars": 0.6, "protein_dieters": 0.4})
    )
    assert dict(recorded.achieved_mix) == {"gym_regulars": 0.6, "protein_dieters": 0.4}
    with pytest.raises(ValidationError, match="sum to one"):
        GateReport.model_validate(gate_report_payload(achieved_mix={"gym_regulars": 0.6, "protein_dieters": 0.5}))


def test_result_order_is_part_of_the_report_hash():
    first = GateReport.model_validate(gate_report_payload())
    flipped = gate_report_payload(results=list(reversed(gate_report_payload()["results"])))
    assert canonical_hash(first) != canonical_hash(GateReport.model_validate(flipped))


# --- graph gates and relaxations -------------------------------------------------------------


def test_graph_gate_result_names_its_check_and_computes_its_verdict():
    passing = GraphGateResult.model_validate(graph(check="clustering", measured=0.42, threshold=0.30))
    assert (passing.check.value, passing.passed) == ("clustering", True)
    assert GraphGateResult.model_validate(graph(check="connectivity", measured=0.90, threshold=0.98)).passed is False
    with pytest.raises(ValidationError, match="computed"):
        GraphGateResult.model_validate(graph(measured=0.1, passed=True))


@pytest.mark.parametrize("measured", [0.3, 0.29], ids=["at-target", "below"])
def test_graph_gate_threshold_decides_the_verdict(measured):
    assert GraphGateResult.model_validate(graph(measured=measured, threshold=0.3)).passed is (measured >= 0.3)


def test_report_holds_distribution_and_graph_results_and_keys_each_subject_once():
    report = GateReport.model_validate(gate_report_payload(results=[ordinal(), categorical(), graph()]))
    assert report.overall is True
    with pytest.raises(ValidationError, match="more than one gate result"):
        GateReport.model_validate(gate_report_payload(results=[ordinal(), categorical(), graph(), graph(measured=0.1)]))
    collision = gate_report_payload(results=[categorical(attribute="clustering"), graph(check="clustering")])
    assert GateReport.model_validate(collision).overall is True


def test_a_relaxation_records_the_filter_as_authored_and_as_applied():
    relaxed = Relaxation.model_validate(relaxation())
    assert (relaxed.audience, relaxed.rung.value) == ("gym_regulars", "widen_ordinal")
    assert relaxed.authored.value == "3_plus_weekly"
    assert relaxed.applied.value == "weekly"
    assert Relaxation.model_validate(relaxation(rung="drop_filter", applied=None)).applied is None
    short = Relaxation.model_validate(relaxation(rung="accept_shortfall", attribute=None, authored=None, applied=None))
    assert short.attribute is None


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"rung": "drop_filter"}, "applying nothing"),
        ({"rung": "accept_shortfall"}, "changes no filter"),
        ({"rows_after": 5}, "never shrinks"),
        ({"rung": "widen_ordinal", "applied": None}, "as applied"),
    ],
    ids=["drop-with-applied", "shortfall-with-filter", "shrinking", "widen-without-applied"],
)
def test_a_relaxation_refuses_a_shape_its_rung_does_not_have(overrides, match):
    with pytest.raises(ValidationError, match=match):
        Relaxation.model_validate(relaxation(**overrides))


def test_a_relaxation_caveats_the_sample_without_moving_the_verdict():
    assert GateReport.model_validate(gate_report_payload(relaxations=[relaxation()])).overall is True
    failing = gate_report_payload(results=[categorical(p_value=0.01)], relaxations=[relaxation()])
    assert GateReport.model_validate(failing).overall is False


# --- manifest, graph, communities ------------------------------------------------------------


def manifest(**overrides):
    return {**population_payload()["manifest"], **overrides}


def test_manifest_records_achieved_mix_keyed_by_audience_and_no_stratum():
    parsed = PopulationManifest.model_validate(manifest())
    assert set(parsed.achieved_mix) == {"gym_regulars", "protein_dieters"}
    assert not {"stratum", "strata", "segment"} & set(PopulationManifest.model_fields)
    with pytest.raises(ValidationError, match="sum to one"):
        PopulationManifest.model_validate(manifest(achieved_mix={"gym_regulars": 0.9}))


def test_manifest_refuses_a_persona_sampled_twice():
    with pytest.raises(ValidationError, match="more than once"):
        PopulationManifest.model_validate(manifest(persona_ids=["p-000001", "p-000001"]))


def test_manifest_records_the_requested_mix_beside_the_achieved_mix():
    parsed = PopulationManifest.model_validate(manifest())
    assert parsed.requested_mix == {"gym_regulars": 0.6, "protein_dieters": 0.4}
    assert parsed.achieved_mix == {"gym_regulars": 0.5, "protein_dieters": 0.5}
    with pytest.raises(ValidationError, match="sum to one"):
        PopulationManifest.model_validate(manifest(requested_mix={"gym_regulars": 0.6, "protein_dieters": 0.5}))


def test_manifest_records_completion_provenance_and_the_synthesized_share():
    parsed = PopulationManifest.model_validate(manifest())
    assert parsed.synthesized_share == 0.2
    assert parsed.completion.model_id == "openrouter/camel-ai/persona-8b"
    assert parsed.completion.template_id == "field_completion"
    assert len(parsed.completion.template_hash) == 64


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"completion": None}, "must name the model and template"),
        ({"synthesized_share": 0.0}, "must not name a completion source"),
    ],
    ids=["synthesis-without-producer", "producer-without-synthesis"],
)
def test_manifest_refuses_synthesis_without_a_producer_and_a_producer_without_synthesis(overrides, match):
    with pytest.raises(ValidationError, match=match):
        PopulationManifest.model_validate(manifest(**overrides))


def test_manifest_records_the_parameters_the_population_was_built_with():
    parsed = PopulationManifest.model_validate(manifest())
    assert parsed.parameters.graph.homophily_strength == 0.2
    assert parsed.parameters.communities == CommunityThresholds()


def test_parameters_default_to_the_engines_values_when_a_manifest_states_none():
    stated = manifest()
    stated.pop("parameters")
    assert PopulationManifest.model_validate(stated).parameters == PopulationParameters()


def test_every_default_parameter_is_the_value_the_engine_used_before_it_was_tunable():
    defaults = PopulationParameters()
    assert (defaults.graph.ring_degree, defaults.graph.hub_attachment) == (4, 2)
    assert (defaults.graph_gates.clustering_floor, defaults.graph_gates.connectivity_floor, defaults.graph_gates.hub_tail_floor) == (0.05, 0.98, 1.8)
    assert defaults.graph_gates.assortativity_ceiling == 0.9
    assert (defaults.communities.modularity_floor, defaults.communities.min_communities, defaults.communities.max_communities) == (0.4, 4, 8)
    assert defaults.communities.share_floor == 0.05 and defaults.communities.resolutions == (0.5, 0.75, 1.0, 1.25, 1.5)
    assert (defaults.distribution_gates.significance_level, defaults.distribution_gates.similarity_threshold) == (0.05, 0.80)


@pytest.mark.parametrize(
    ("model", "overrides", "match"),
    [
        (GraphParameters, {"ring_degree": 3}, "degree is even"),
        (GraphParameters, {"homophily_strength": 1.5}, "homophily_strength"),
        (GraphParameters, {"hub_attachment": 0}, "hub_attachment"),
        (GraphThresholds, {"hub_tail_floor": 1.0}, "hub_tail_floor"),
        (CommunityThresholds, {"min_communities": 9, "max_communities": 8}, "cannot both hold"),
        (CommunityThresholds, {"min_communities": 6, "share_floor": 0.2}, "no partition could ever qualify"),
        (CommunityThresholds, {"resolutions": (1.0, 0.5)}, "ascending order"),
        (CommunityThresholds, {"resolutions": (0.5, 0.5)}, "each once"),
        (CommunityThresholds, {"resolutions": ()}, "resolutions"),
        (DistributionThresholds, {"significance_level": 1.0}, "significance_level"),
        (GraphThresholds, {"assortativity_ceiling": 0.0}, "assortativity_ceiling"),
    ],
    ids=["odd-ring", "homophily-out-of-range", "no-hub-attachment", "hub-floor-judging-nothing", "min-over-max",
         "floor-unreachable", "resolutions-descending", "resolution-repeated", "no-resolutions", "significance-certain",
         "ceiling-judging-nothing"],
)
def test_a_tuned_parameter_that_could_never_mean_anything_is_refused(model, overrides, match):
    with pytest.raises(ValidationError, match=match):
        model.model_validate(overrides)


def test_tuned_parameters_round_trip():
    tuned = PopulationParameters.model_validate({"graph": {"homophily_strength": 0.6, "ring_degree": 6}, "communities": {"resolutions": [0.4, 1.2]}})
    assert PopulationParameters.model_validate_json(tuned.model_dump_json()) == tuned


def test_social_edges_refuse_self_loops_and_out_of_range_weights():
    with pytest.raises(ValidationError, match="itself"):
        SocialEdge(u="p-000001", v="p-000001", weight=0.5)
    with pytest.raises(ValidationError):
        SocialEdge(u="p-000001", v="p-000002", weight=1.5)


@pytest.mark.parametrize("reverse", [False, True], ids=["same-direction", "reversed"])
def test_social_graph_refuses_a_tie_declared_twice(reverse):
    second = {"u": "p-000002", "v": "p-000001"} if reverse else {"u": "p-000001", "v": "p-000002"}
    with pytest.raises(ValidationError, match="more than once"):
        SocialGraph.model_validate(
            {"edges": [{"u": "p-000001", "v": "p-000002", "weight": 0.8}, {**second, "weight": 0.1}]}
        )


def test_community_requires_members():
    with pytest.raises(ValidationError):
        Community.model_validate({"community_id": "community-1", "member_ids": []})


def test_communities_do_not_appear_on_any_input_type():
    for model in (schemas.ProductBrief, schemas.BriefPack, schemas.CategoryOntology, schemas.Variant,
                  schemas.Scenario, schemas.SweepGrid, schemas.SweepPlan, schemas.RunConfig):
        assert "Community" not in repr(model.model_fields), f"{model.__name__} references a community"


# --- population ------------------------------------------------------------------------------


def build(**overrides) -> Population:
    return Population.model_validate(population_payload(**overrides))


def personas_with(index: int, **persona_overrides):
    personas = [persona_payload(i) for i in range(len(PERSONA_IDS))]
    personas[index] = persona_payload(index, **persona_overrides)
    return personas


def test_population_validates_and_round_trips():
    population = build()
    assert population.gate_report.overall is True
    assert Population.model_validate(population.model_dump(mode="json")) == population
    assert Population.model_validate_json(population.model_dump_json()) == population


@pytest.mark.parametrize(
    "conditioning",
    [{"age": "25_34", "sex": "female"}, {"age": "25_34", "sex": "female", "exercise_frequency": "weekly", "region": "urban"}],
    ids=["narrower-than-category", "wider-than-category"],
)
def test_persona_conditioned_on_other_than_the_categorys_set_refused(conditioning):
    origins = {name: "measured" for name in conditioning} | {"diet_protein_focus": "measured", "spend_band": "synthesized"}
    with pytest.raises(ValidationError, match="must be conditioned on exactly"):
        build(personas=personas_with(1, conditioning=conditioning, origins=origins))


def test_persona_projecting_an_undeclared_attribute_refused():
    attributes = {"diet_protein_focus": "high", "spend_band": "5_10", "hair_color": "brown"}
    origins = {**persona_payload()["origins"], "hair_color": "measured"}
    with pytest.raises(ValidationError, match="does not declare"):
        build(personas=personas_with(0, attributes=attributes, origins=origins))


@pytest.mark.parametrize("attribute", ["age", "diet_protein_focus"], ids=["demographic", "psychographic"])
def test_synthesized_demographic_or_psychographic_refused_by_the_ontologys_domains(attribute):
    origins = {**persona_payload()["origins"], attribute: "synthesized"}
    with pytest.raises(ValidationError, match="synthesized demographic or psychographic"):
        build(personas=personas_with(3, origins=origins), gate_report=gate_report_payload(results=[ordinal()]))


def test_calibrated_demographic_allowed():
    origins = {**persona_payload()["origins"], "age": "calibrated"}
    population = build(personas=personas_with(2, origins=origins), gate_report=gate_report_payload(results=[ordinal()]))
    assert population.personas[2].origins["age"].value == "calibrated"


@pytest.mark.parametrize(
    "persona_ids", [list(reversed(PERSONA_IDS)), PERSONA_IDS[:3] + ["p-000009"]], ids=["reordered", "different-persona"]
)
def test_personas_must_be_exactly_the_manifest(persona_ids):
    with pytest.raises(ValidationError, match="manifest"):
        build(manifest={**population_payload()["manifest"], "persona_ids": persona_ids})


def embedded_personas() -> list[dict]:
    return [
        persona_payload(index, embedding={"model_id": "text-embedding-3-small", "dim": 1536, "index": index})
        for index in range(len(PERSONA_IDS))
    ]


def test_personas_sharing_an_embedding_position_refused():
    personas = embedded_personas()
    personas[1] = persona_payload(1, embedding={"model_id": "text-embedding-3-small", "dim": 1536, "index": 0})
    with pytest.raises(ValidationError, match="share embedding positions"):
        build(personas=personas)


def test_personas_embedded_by_different_models_refused():
    personas = embedded_personas()
    personas[1] = persona_payload(1, embedding={"model_id": "voyage-3", "dim": 1024, "index": 1})
    with pytest.raises(ValidationError, match="more than one model"):
        build(personas=personas)


def test_a_population_whose_personas_omit_embeddings_validates():
    assert build().personas[0].embedding is None


def test_achieved_mix_must_report_every_declared_audience():
    with pytest.raises(ValidationError, match="every declared audience"):
        build(manifest={**population_payload()["manifest"], "achieved_mix": {"gym_regulars": 1.0}})


def test_brief_without_audiences_accepts_derived_audience_names():
    manifest = {**population_payload()["manifest"], "population_hash": "00" * 32, "achieved_mix": {"women_25_34": 0.5, "men_25_34": 0.5}}
    payload = population_payload(pack=pack_payload(audiences=[]), manifest=manifest)
    assert set(Population.model_validate(payload).manifest.achieved_mix) == {"women_25_34", "men_25_34"}


def test_source_mix_must_match_the_personas():
    with pytest.raises(ValidationError, match="does not match the personas"):
        build(gate_report=gate_report_payload(source_mix={"gss": 0.75, "synthetic": 0.25}))


@pytest.mark.parametrize(
    ("result", "match"),
    [
        (categorical(attribute="region"), "does not declare"),
        (categorical(attribute="exercise_frequency"), "must be ordinal"),
        (ordinal(attribute="age", ks_statistic=0.1, ks_similarity=0.9), "must be categorical"),
        (categorical(attribute="spend_band"), "measured or extracted"),
    ],
    ids=["undeclared", "categorical-on-scaled", "ordinal-on-unscaled", "synthesized"],
)
def test_gates_run_only_on_declared_gateable_attributes_of_the_right_kind(result, match):
    with pytest.raises(ValidationError, match=match):
        build(gate_report=gate_report_payload(results=[result]))


def test_a_gate_may_run_on_an_extracted_attribute():
    personas = [
        persona_payload(
            index,
            origins={**persona_payload(index)["origins"], "spend_band": "extracted"},
            completed_distributions={},
        )
        for index in range(len(PERSONA_IDS))
    ]
    population = build(
        personas=personas,
        gate_report=gate_report_payload(
            results=[ordinal(), categorical(attribute="spend_band")],
            attribute_origins={"exercise_frequency": "measured", "spend_band": "extracted"},
        ),
    )
    assert population.personas[0].origins["spend_band"] is schemas.FieldOrigin.EXTRACTED


def test_gate_on_an_attribute_no_persona_carries_refused():
    personas = [persona_payload(i, attributes={"spend_band": "5_10"},
                                origins={"age": "measured", "sex": "measured", "exercise_frequency": "measured", "spend_band": "synthesized"})
                for i in range(len(PERSONA_IDS))]
    with pytest.raises(ValidationError, match="no persona carries"):
        build(personas=personas, gate_report=gate_report_payload(results=[categorical(attribute="diet_protein_focus")]))


def test_graph_tying_a_persona_outside_the_population_refused():
    graph = copy.deepcopy(population_payload()["graph"])
    graph["edges"].append({"u": "p-000004", "v": "p-000099", "weight": 0.3})
    with pytest.raises(ValidationError, match="outside the population"):
        build(graph=graph)


def test_population_with_a_graph_refuses_an_isolated_persona():
    graph = {"edges": [{"u": "p-000001", "v": "p-000002", "weight": 0.8},
                       {"u": "p-000002", "v": "p-000003", "weight": 0.2}]}
    with pytest.raises(ValidationError, match="isolated"):
        build(graph=graph, communities=[])


def test_communities_require_a_graph():
    with pytest.raises(ValidationError, match="require one"):
        build(graph=None)


def test_population_without_graph_or_communities_is_valid():
    assert build(graph=None, communities=[]).communities == ()


@pytest.mark.parametrize(
    "communities",
    [
        [{"community_id": "community-1", "member_ids": ["p-000001", "p-000002", "p-000003"]},
         {"community_id": "community-2", "member_ids": ["p-000003", "p-000004"]}],
        [{"community_id": "community-1", "member_ids": ["p-000001", "p-000002"]},
         {"community_id": "community-2", "member_ids": ["p-000003"]}],
        [{"community_id": "community-1", "member_ids": ["p-000001", "p-000002"]},
         {"community_id": "community-2", "member_ids": ["p-000003", "p-000004", "p-000099"]}],
    ],
    ids=["overlapping", "persona-unplaced", "outsider"],
)
def test_communities_must_partition_the_population(communities):
    with pytest.raises(ValidationError, match="partition"):
        build(communities=communities)


def test_community_ids_must_be_unique():
    communities = [{"community_id": "community-1", "member_ids": ["p-000001", "p-000002"]},
                   {"community_id": "community-1", "member_ids": ["p-000003", "p-000004"]}]
    with pytest.raises(ValidationError, match="community ids repeated"):
        build(communities=communities)


def test_persona_domain_labels_cannot_be_smuggled_in():
    with pytest.raises(ValidationError, match="attribute_domains"):
        Persona.model_validate({**persona_payload(), "attribute_domains": {"age": "economic"}})


@pytest.mark.parametrize(
    "credence",
    [{"C1": 0.8, "C2": 0.3}, {"C1": 0.8, "C2": 0.3, "C3": 0.5, "C4": 0.1}],
    ids=["missing-a-claim", "claim-the-brief-does-not-make"],
)
def test_baseline_beliefs_must_credit_exactly_the_briefs_claims(credence):
    with pytest.raises(ValidationError, match="baseline credence"):
        build(personas=personas_with(2, baseline_beliefs=beliefs_payload(claim_credence=credence)))


# --- derived identity -------------------------------------------------------------------------


def test_population_hash_is_derived_and_the_manifest_must_state_it():
    population = build()
    assert population.population_hash == population.manifest.population_hash
    assert "population_hash" in Population.model_computed_fields
    stale = {**population_payload()["manifest"], "population_hash": "ab" * 32}
    with pytest.raises(ValidationError, match="manifest states population hash"):
        Population.model_validate(population_payload(manifest=stale))


def test_different_populations_never_share_a_hash():
    changed = build(personas=personas_with(0, attributes={"diet_protein_focus": "low", "spend_band": "5_10"}))
    assert changed.population_hash != build().population_hash
    assert build().population_hash == build().population_hash


def test_graph_hash_is_derived_from_ties_regardless_of_order_or_direction():
    edges = population_payload()["graph"]["edges"]
    forward = SocialGraph.model_validate({"edges": edges})
    flipped = SocialGraph.model_validate({"edges": [{"u": e["v"], "v": e["u"], "weight": e["weight"]} for e in reversed(edges)]})
    assert forward.graph_hash == flipped.graph_hash
    reweighted = SocialGraph.model_validate({"edges": [{**edges[0], "weight": 0.1}, *edges[1:]]})
    assert reweighted.graph_hash != forward.graph_hash
    with pytest.raises(ValidationError, match="computed"):
        SocialGraph.model_validate({"edges": edges, "graph_hash": "cd" * 32})


def test_manifest_graph_hash_must_be_this_populations_graph():
    stale = {**population_payload()["manifest"], "graph_hash": "cd" * 32}
    with pytest.raises(ValidationError, match="manifest states graph hash"):
        Population.model_validate(population_payload(manifest=stale))
    without_graph = {**population_payload()["manifest"], "population_hash": "00" * 32, "graph_hash": None}
    assert build(graph=None, communities=[], manifest=without_graph).manifest.graph_hash is None


def test_unvalidated_graph_construction_takes_edge_models_not_mappings():
    edges = population_payload()["graph"]["edges"]
    with pytest.raises(TypeError, match="takes models, not mappings"):
        SocialGraph.model_construct(edges=tuple(edges))
    built = SocialGraph.model_construct(edges=tuple(SocialEdge.model_validate(edge) for edge in edges))
    assert built.graph_hash == SocialGraph.model_validate({"edges": edges}).graph_hash


def test_a_population_records_assortativity_only_for_attributes_its_ontology_declares():
    data = population_payload()
    data["gate_report"]["assortativity"] = {"exercise_frequency": 0.12}
    data["gate_report"]["audience_assortativity"] = 0.2
    parsed = Population.model_validate(data)
    assert parsed.gate_report.assortativity["exercise_frequency"] == 0.12
    data["gate_report"]["assortativity"] = {"favourite_colour": 0.1}
    with pytest.raises(ValidationError, match="does not declare"):
        Population.model_validate(data)


def test_assortativity_is_refused_on_a_population_without_a_graph():
    data = population_payload(graph=None, communities=[])
    data["gate_report"]["assortativity"] = {"exercise_frequency": 0.12}
    with pytest.raises(ValidationError, match="measured on the social graph"):
        Population.model_validate(data)


@pytest.mark.parametrize("value", [1.5, -1.5], ids=["above-one", "below-minus-one"])
def test_assortativity_lies_between_minus_one_and_one(value):
    with pytest.raises(ValidationError):
        GateReport.model_validate({**gate_report_payload(), "assortativity": {"exercise_frequency": value}})


def test_a_distribution_gate_records_what_it_was_judged_against_and_defaults_to_the_design():
    assert CategoricalGateResult.model_validate(categorical()).reference is GateReference.DESIGN
    assert OrdinalGateResult.model_validate(ordinal(reference="category_targets")).reference is GateReference.CATEGORY_TARGETS


@pytest.mark.parametrize(
    ("references", "claim"),
    [(["category_targets", "category_targets"], "category_targets"), (["category_targets", "design"], "design"), (["design", "design"], "design")],
    ids=["every-gate-on-targets", "one-gate-on-the-design", "every-gate-on-the-design"],
)
def test_a_report_claims_only_what_its_weakest_distribution_gate_claims(references, claim):
    results = [ordinal(reference=references[0]), categorical(reference=references[1]), graph()]
    assert GateReport.model_validate(gate_report_payload(results=results)).reference.value == claim


def test_a_report_cannot_state_a_stronger_claim_than_its_gates_support():
    with pytest.raises(ValidationError, match="computed"):
        GateReport.model_validate({**gate_report_payload(), "reference": "category_targets"})
