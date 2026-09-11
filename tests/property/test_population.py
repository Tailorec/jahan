import pytest
from pydantic import ValidationError

from simcore.schemas import (
    CategoricalGateResult,
    Community,
    FieldOrigin,
    GateReport,
    OrdinalGateResult,
    PopulationManifest,
    SocialEdge,
    SocialGraph,
    canonical_hash,
)

PERSONA_IDS = ("p-000001", "p-000002", "p-000003", "p-000004")


def categorical(**overrides):
    payload = {
        "kind": "categorical",
        "attribute": "exercise_frequency",
        "attribute_origin": "grounded",
        "chi_square": 3.2,
        "degrees_of_freedom": 4,
        "p_value": 0.52,
        "passed": True,
    }
    payload.update(overrides)
    return payload


def ordinal(**overrides):
    payload = {
        "kind": "ordinal",
        "attribute": "age",
        "attribute_origin": "grounded",
        "ks_statistic": 0.08,
        "ks_similarity": 0.92,
        "passed": True,
    }
    payload.update(overrides)
    return payload


def report_payload(**overrides):
    payload = {
        "results": [categorical(), ordinal()],
        "source_mix": {"gss": 0.7, "synthetic": 0.3},
    }
    payload.update(overrides)
    return payload


def test_gate_results_dispatch_on_kind_alone():
    report = GateReport.model_validate(report_payload())
    categorical_result, ordinal_result = report.results
    assert isinstance(categorical_result, CategoricalGateResult)
    assert isinstance(ordinal_result, OrdinalGateResult)
    assert categorical_result.kind == "categorical"
    assert ordinal_result.kind == "ordinal"


def test_gate_results_carry_no_nullable_twin_fields():
    assert "chi_square" not in OrdinalGateResult.model_fields
    assert "degrees_of_freedom" not in OrdinalGateResult.model_fields
    assert "ks_statistic" not in CategoricalGateResult.model_fields
    assert "ks_similarity" not in CategoricalGateResult.model_fields


def test_ordinal_gate_exposes_statistic_and_similarity_with_matching_direction():
    result = OrdinalGateResult.model_validate(ordinal())
    assert result.ks_statistic == 0.08
    assert result.ks_similarity == pytest.approx(1.0 - result.ks_statistic)
    with pytest.raises(ValidationError, match="one minus"):
        OrdinalGateResult.model_validate(ordinal(ks_statistic=0.08, ks_similarity=0.5))


def test_ordinal_gate_bounds():
    with pytest.raises(ValidationError):
        OrdinalGateResult.model_validate(ordinal(ks_statistic=1.2, ks_similarity=-0.2))


@pytest.mark.parametrize("origin", ["synthesized", "calibrated"])
def test_gate_results_refuse_ungrounded_attributes(origin):
    with pytest.raises(ValidationError, match="grounded"):
        GateReport.model_validate(report_payload(results=[categorical(attribute_origin=origin)]))


def test_gate_report_overall_is_computed_from_results():
    report = GateReport.model_validate(report_payload())
    assert report.overall is True
    failing = report_payload(results=[categorical(passed=False), ordinal()])
    assert GateReport.model_validate(failing).overall is False
    assert "overall" not in GateReport.model_fields


def test_gate_report_source_mix_sums_to_one():
    with pytest.raises(ValidationError, match="sum to one"):
        GateReport.model_validate(report_payload(source_mix={"gss": 0.7, "synthetic": 0.2}))
    with pytest.raises(ValidationError, match="sum to one"):
        GateReport.model_validate(report_payload(source_mix={}))


def test_report_with_only_ordinal_results_validates():
    report = GateReport.model_validate(report_payload(results=[ordinal()]))
    assert report.overall is True


def manifest_payload(**overrides):
    payload = {
        "population_hash": "ab12" * 16,
        "population_seed": 4021,
        "persona_ids": list(PERSONA_IDS),
        "achieved_mix": {"gym_regulars": 0.6, "protein_dieters": 0.4},
    }
    payload.update(overrides)
    return payload


def test_manifest_records_achieved_mix_keyed_by_audience():
    manifest = PopulationManifest.model_validate(manifest_payload())
    assert set(manifest.achieved_mix) == {"gym_regulars", "protein_dieters"}
    with pytest.raises(ValidationError, match="sum to one"):
        PopulationManifest.model_validate(manifest_payload(achieved_mix={"gym_regulars": 0.9}))


def test_manifest_carries_no_stratum_concept():
    field_names = set(PopulationManifest.model_fields)
    assert "stratum" not in field_names
    assert "segment" not in field_names
    assert "strata" not in field_names


def test_social_graph_edges():
    graph = SocialGraph.model_validate(
        {
            "graph_hash": "cd34" * 16,
            "edges": [
                {"u": "p-000001", "v": "p-000002", "weight": 0.8},
                {"u": "p-000002", "v": "p-000003", "weight": 0.25},
            ],
        }
    )
    assert len(graph.edges) == 2
    with pytest.raises(ValidationError, match="itself"):
        SocialEdge(u="p-000001", v="p-000001", weight=0.5)
    with pytest.raises(ValidationError):
        SocialEdge(u="p-000001", v="p-000002", weight=1.5)


def test_community_carries_discovered_members():
    community = Community.model_validate({"community_id": "community-1", "member_ids": list(PERSONA_IDS)})
    assert set(community.member_ids) == set(PERSONA_IDS)
    with pytest.raises(ValidationError):
        Community.model_validate({"community_id": "community-1", "member_ids": []})


def test_communities_do_not_appear_on_any_input_type():
    from simcore import schemas

    input_models = [
        schemas.ProductBrief,
        schemas.BriefPack,
        schemas.CategoryOntology,
        schemas.ConceptCard if hasattr(schemas, "ConceptCard") else None,
        schemas.Scenario if hasattr(schemas, "Scenario") else None,
        schemas.RunConfig if hasattr(schemas, "RunConfig") else None,
    ]
    for model in input_models:
        if model is None:
            continue
        annotations = repr(model.model_fields)
        assert "Community" not in annotations, f"{model.__name__} references a community"


def test_gate_report_and_manifest_round_trip_through_json():
    report = GateReport.model_validate(report_payload())
    assert GateReport.model_validate(report.model_dump(mode="json")) == report
    assert GateReport.model_validate_json(report.model_dump_json()) == report
    manifest = PopulationManifest.model_validate(manifest_payload())
    assert PopulationManifest.model_validate(manifest.model_dump(mode="json")) == manifest


def test_result_order_is_part_of_the_report_hash():
    first = GateReport.model_validate(report_payload())
    flipped = report_payload(results=[ordinal(), categorical()])
    second = GateReport.model_validate(flipped)
    assert canonical_hash(first) != canonical_hash(second)
