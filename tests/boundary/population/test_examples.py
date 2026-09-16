"""The two example studies: the offline quickstart and the real-data study, proven by running them."""

import importlib.util
from pathlib import Path

import pytest

from tests.real_corpus import REAL_CACHE, real_corpus

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- the offline quickstart -------------------------------------------------------------------


def test_the_quickstart_runs_offline_and_grades_measured():
    quickstart = _load("beverage_quickstart")
    forecast, report, population = quickstart.run(n=400)
    assert set(report.source_mix) == {"synthetic"}
    assert report.evidence.value == "measured"
    assert forecast.synthesized_fields == 0
    assert len(population.personas) > 0


def test_the_quickstart_reaches_neither_the_adapter_nor_the_network():
    text = (EXAMPLES / "beverage_quickstart.py").read_text()
    for forbidden in ("simcore.ports.hf", "pyarrow", "requests", "urllib", "httpx", "hf_hub_download", "subprocess"):
        assert forbidden not in text


def test_the_quickstart_ontology_is_honest_about_the_synthetic_source():
    quickstart = _load("beverage_quickstart")
    ontology = quickstart.pack().ontology
    shape = quickstart.SHAPE
    # Every conditioning attribute is one the synthetic source actually supplies, so none is invented.
    assert set(ontology.conditioning_set) <= set(shape.attributes)
    assert all(ontology.attribute_domains[attribute] in {"demographic", "psychographic"} or attribute in shape.attributes for attribute in ontology.conditioning_set)


# --- the real-data study ----------------------------------------------------------------------


def test_the_real_study_states_its_download_step():
    script = (EXAMPLES / "ai_code_review.py").read_text()
    assert "hf download" in script
    readme = (EXAMPLES / "README.md").read_text()
    assert "matched 34,373" in readme and "carrying 100,662" in readme


def test_a_missing_cache_is_refused_with_a_fetch_command(tmp_path):
    real = _load("ai_code_review")
    empty = tmp_path / "coreset"
    empty.mkdir()
    (empty / "manifest.json").write_text('{"files": [], "rows": 0}')
    with pytest.raises(Exception, match="hf download"):
        real.coresets(empty)


_real_only = real_corpus


@_real_only
def test_the_real_study_previews_assesses_and_builds_against_cached_shards():
    real = _load("ai_code_review")
    forecast, report, population = real.run(n=1500, cache=REAL_CACHE)
    # Demographic and professional fields are survey answers; part of the attitude fields was inferred by a
    # model, so the report is only as strong as those — it once graded measured by grading whole sources.
    origins = {attribute: tier.value for attribute, tier in report.attribute_origins.items()}
    assert {origins[a] for a in ("age_bracket", "region", "dev_professional_status")} == {"measured"}
    assert origins["att_ai"] == "extracted"
    assert report.evidence.value == "extracted"
    assert set(report.source_mix) == {"stackoverflow"}
    assert report.overall is True
    assert len(population.personas) > 0
