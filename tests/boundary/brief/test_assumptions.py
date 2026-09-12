"""The assumption ledger: what a study takes on faith, gathered rather than stored."""

import yaml

from simcore.brief import assumptions_of, load_brief
from simcore.schemas import Assumption, BriefPack, ClaimSource
from tests.study_builders import load_ontology


def example_payload(example_brief) -> dict:
    return yaml.safe_load(example_brief.read_text())


def test_stated_assumptions_appear_unchanged(example_brief, ontologies):
    pack = load_brief(example_brief, ontologies)
    assert pack.brief.assumptions[0] in assumptions_of(pack)


def test_a_claim_marked_assumed_appears_carrying_its_own_text(example_brief, ontologies):
    pack = load_brief(example_brief, ontologies)
    assumed = [claim for claim in pack.brief.claims if claim.source is ClaimSource.ASSUMED]
    assert assumed
    ledger = assumptions_of(pack)
    for claim in assumed:
        assert Assumption(text=claim.text, source=ClaimSource.ASSUMED) in ledger


def test_a_brief_declaring_no_audiences_assumes_the_whole_population_is_the_target_market(example_brief, authored):
    payload = example_payload(example_brief)
    payload["audiences"] = []
    path, ontology_dir = authored(payload, load_ontology())
    pack = load_brief(path, ontology_dir)
    entries = [item for item in assumptions_of(pack) if "target market" in item.text.lower()]
    assert len(entries) == 1
    assert pack.brief.target_market in entries[0].text
    assert entries[0].source is ClaimSource.ASSUMED


def test_a_brief_declaring_audiences_contributes_no_target_market_entry(example_brief, ontologies):
    pack = load_brief(example_brief, ontologies)
    assert pack.brief.audiences_declared
    assert not [item for item in assumptions_of(pack) if "target market" in item.text.lower()]


def test_the_ledger_is_derived_on_demand_and_stored_nowhere(example_brief, ontologies):
    pack = load_brief(example_brief, ontologies)
    assert assumptions_of(pack) == assumptions_of(pack)
    assert "ledger" not in BriefPack.model_fields
    assert pack.brief.assumptions == load_brief(example_brief, ontologies).brief.assumptions


def test_the_ledger_returns_only_contract_types(example_brief, ontologies):
    pack = load_brief(example_brief, ontologies)
    assert assumptions_of(pack)
    assert all(isinstance(item, Assumption) for item in assumptions_of(pack))
