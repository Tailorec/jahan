"""Throwaway models exercising the phase-1 machinery end to end.

Deliberately narrow: real domain models arrive in phases 2-7 and this module
is then deleted. It exists so the base configuration, validation, canonical
hashing, fixture pinning and the dependency guard are proven together before
any real type is written against them.
"""

from typing import Any, ClassVar

from simcore.schemas import (
    FrozenDict,
    HashDigest,
    NonEmptyStr,
    NonNegativeInt,
    RunId,
    SimBaseModel,
    UnitInterval,
)


class DemoBrief(SimBaseModel):
    _hash_exclude_: ClassVar[frozenset[str]] = frozenset({"fetched_at"})

    title: NonEmptyStr
    claims: tuple[NonEmptyStr, ...]
    target_filters: FrozenDict[str, str]
    audience_mix: FrozenDict[str, UnitInterval]
    fetched_at: str


class DemoPolicy(SimBaseModel):
    completable: frozenset[NonEmptyStr]


class DemoRunConfig(SimBaseModel):
    _hash_exclude_: ClassVar[frozenset[str]] = frozenset({"observed_cost"})
    _hash_version_: ClassVar[bool] = True

    run_id: RunId
    brief: DemoBrief
    population_hash: HashDigest
    seeds: tuple[NonNegativeInt, ...]
    observed_cost: float


def make_brief_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Protein water",
        "claims": ("clear hydration", "zero sugar", "20g protein"),
        "target_filters": {"age_band": "25_40", "region": "urban"},
        "audience_mix": {"gym_regulars": 0.6, "dieters": 0.4},
        "fetched_at": "2026-09-11T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_run_config_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "run20260911a",
        "brief": make_brief_payload(),
        "population_hash": "ab12" * 16,
        "seeds": (4021, 917731),
        "observed_cost": 12.5,
    }
    payload.update(overrides)
    return payload
