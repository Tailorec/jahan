"""Refusing the wrong resume: one trace never holds two experiments.

Resume compares the run's inputs against the registry entry — brief,
ontology, population, graph, scenario, pins and engine version — and refuses
when any moved, naming the one that did. A forced resume proceeds, is
recorded in the registry, and marks the results as spanning versions.
"""

from __future__ import annotations

from simcore.schemas import BriefPack, Population, RunConfig, canonical_hash
from simcore.schemas.errors import SimError


class ResumeRefused(SimError):
    """Resume refused: the named input moved from the recorded value."""

    def __init__(self, name: str, recorded: str, presented: str) -> None:
        super().__init__(f"resume refused: {name} moved from {recorded} to {presented}")
        self.name = name
        self.recorded = recorded
        self.presented = presented


def check_resume_inputs(
    config: RunConfig,
    pack: BriefPack,
    population: Population,
    engine_version: str,
    recorded_config: RunConfig,
    recorded_engine_version: str,
) -> None:
    """Raise `ResumeRefused` naming the first input that moved, if any."""
    brief = canonical_hash(pack.brief)
    if brief != recorded_config.brief_hash or config.brief_hash != recorded_config.brief_hash:
        raise ResumeRefused("brief", recorded_config.brief_hash, config.brief_hash)
    ontology = canonical_hash(pack.ontology)
    if ontology != recorded_config.ontology_hash or config.ontology_hash != recorded_config.ontology_hash:
        raise ResumeRefused("ontology", recorded_config.ontology_hash, config.ontology_hash)
    if population.manifest.graph_hash != recorded_config.graph_hash:
        raise ResumeRefused(
            "graph", str(recorded_config.graph_hash), str(population.manifest.graph_hash)
        )
    if population.manifest.population_hash != recorded_config.population_hash:
        raise ResumeRefused(
            "population", recorded_config.population_hash, population.manifest.population_hash
        )
    recorded_scenarios = sorted(canonical_hash(s) for s in recorded_config.scenarios)
    presented_scenarios = sorted(canonical_hash(s) for s in config.scenarios)
    if recorded_scenarios != presented_scenarios:
        raise ResumeRefused("scenario", ",".join(recorded_scenarios), ",".join(presented_scenarios))
    if canonical_hash(config.pins) != canonical_hash(recorded_config.pins):
        raise ResumeRefused("pins", canonical_hash(recorded_config.pins), canonical_hash(config.pins))
    if engine_version != recorded_engine_version:
        raise ResumeRefused("engine_version", recorded_engine_version, engine_version)
