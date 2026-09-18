"""Hand-built finding sets for the report boundary tests: no network, no model, no trace."""

from simcore.report import ReportPack
from simcore.schemas import BriefPack, RunConfig, TrustStatement
from tests.study_builders import digest_payload, pack_payload, population_manifest_payload, run_config_payload, scenario_payload, ulid

EVIDENCE = [f"ev-{ulid(1)}", f"ev-{ulid(2)}"]
BASELINE = scenario_payload()
PREMIUM = scenario_payload(
    variant={"variant_id": "v2premium", "name": "Premium", "description": "At a higher price"},
    price={"amount": 2.99, "currency": "USD"},
)


def finding_payload(**overrides):
    payload = {
        "finding_id": "f-objection-01",
        "kind": "objection",
        "statement": "aftertaste is the recurring objection among gym regulars",
        "evidence_trace_ids": EVIDENCE,
        "disconfirming_test": "run 20 blind taste tests; if fewer than 30% mention aftertaste, the finding is wrong",
        "confidence": "medium",
    }
    payload.update(overrides)
    return payload


def pack(**overrides):
    config = run_config_payload(scenarios=[BASELINE, PREMIUM])
    config["population_hash"] = population_manifest_payload()["population_hash"]
    payload = {
        "config": RunConfig.model_validate(config),
        "trust": TrustStatement.model_validate(
            {"level": "uncalibrated", "caveats": ["the engine has never been benchmarked against human purchase intent"]}
        ),
        "brief_pack": BriefPack.model_validate(pack_payload()),
        "validation": "run a blind taste test with 200 category buyers before launch",
        "engine_commit": "0a35555",
    }
    payload.update(overrides)
    return ReportPack(**payload)


def digests():
    return [digest_payload(BASELINE), digest_payload(PREMIUM)]
