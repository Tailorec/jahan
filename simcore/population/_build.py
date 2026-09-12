"""`build`: the whole path — eligibility, sampling, relaxation, gating, projection, patching, embedding,
the graph and communities — returning one validated population beside its optional embedding array.

Every randomised stage draws from its own stream spawned from the one population seed, so no two stages
correlate and none is left unseeded. Determinism is promised under a deterministic inference port; against
a live model the completed fields make a rebuild a different population, so a study is built once and
carried (ADR 0015)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from simcore.ports import ChatPort, CoresetSource, EmbedPort, NullPatchSource, PersonaPatchSource
from simcore.schemas import (
    AttributeId,
    AttributeValue,
    BriefPack,
    EmbeddingRef,
    FieldOrigin,
    FrozenDict,
    GateFailure,
    GateReport,
    Persona,
    Population,
    PopulationManifest,
    PopulationParameters,
    derive_population_hash,
)

from ._assess import _gate_results, sample
from ._communities import detect
from ._graph import build_graph
from ._project import project
from ._streams import spawn


@dataclass(frozen=True)
class BuiltPopulation:
    """A validated population, the embedding array its personas index into when enabled, and how much
    attributes shaped its structure. The array travels beside the contract, never inside it."""

    population: Population
    embeddings: np.ndarray | None = None
    assortativity: Mapping[AttributeId, float] | None = None


def build(
    pack: BriefPack,
    n: int,
    population_seed: int,
    *,
    coreset: CoresetSource,
    inference: ChatPort,
    patches: PersonaPatchSource | None = None,
    embed: EmbedPort | None = None,
    parameters: PopulationParameters = PopulationParameters(),
) -> BuiltPopulation:
    """The population `pack` sampling `n` personas produces, validated against the brief and ontology."""
    sampled = sample(pack, n, population_seed, coreset=coreset)
    distribution = _gate_results(
        pack.ontology, coreset, sampled.references, sampled.rows, parameters.distribution_gates
    )
    projection = project(pack, sampled.rows, coreset, inference=inference)
    personas = _patch(projection.personas, patches if patches is not None else NullPatchSource())
    embeddings = None
    if embed is not None:
        personas, embeddings = _embed(personas, embed, pack)

    _, rewiring, communities_seed = spawn(population_seed)
    audience_of = {f"p-{row_id}": audience for audience, row_id in sampled.drawn if audience is not None}
    graph_build = build_graph(
        pack,
        personas,
        population_seed=rewiring,
        parameters=parameters.graph,
        thresholds=parameters.graph_gates,
        audience_of=audience_of or None,
    )
    communities = detect(
        personas, graph_build.graph, population_seed=communities_seed, thresholds=parameters.communities
    )

    manifest = PopulationManifest(
        population_hash=derive_population_hash(pack, population_seed, personas, graph_build.graph, communities),
        graph_hash=graph_build.graph.graph_hash,
        population_seed=population_seed,
        persona_ids=tuple(persona.persona_id for persona in personas),
        requested_mix=_requested_mix(pack),
        achieved_mix=sampled.achieved_mix,
        parameters=parameters,
        synthesized_share=projection.synthesized_share,
        completion=projection.completion,
    )
    report = GateReport(
        results=_grounded_results(distribution, personas) + graph_build.results,
        source_mix=sampled.source_mix,
        achieved_mix=sampled.achieved_mix,
        relaxations=sampled.relaxations,
    )
    if not report.overall:
        failed = [
            getattr(result, "attribute", None) or getattr(result, "check", None).value
            for result in report.results
            if not result.passed
        ]
        raise GateFailure(f"the built population failed its gates: {failed}")
    population = Population(
        pack=pack,
        manifest=manifest,
        personas=personas,
        gate_report=report,
        graph=graph_build.graph,
        communities=communities,
    )
    return BuiltPopulation(population, embeddings, graph_build.assortativity)


def _requested_mix(pack) -> FrozenDict:
    shares = pack.brief.audience_shares
    return shares if shares is not None else FrozenDict({})


def _grounded_results(results: Sequence, personas: Sequence[Persona]) -> tuple:
    """The distribution gates the built population may still carry: an attribute completion touched is no
    longer wholly grounded, and a gate on it would judge synthesized values against the design they were
    chosen to match."""
    grounded = tuple(
        result
        for result in results
        if all(
            persona.origins[result.attribute] is FieldOrigin.GROUNDED
            for persona in personas
            if result.attribute in persona.origins
        )
    )
    if not grounded:
        raise GateFailure("no gated attribute stayed grounded across the built population")
    return grounded


def _patch(personas: Sequence[Persona], patches: PersonaPatchSource) -> tuple[Persona, ...]:
    """Apply externally-derived corrections; a corrected field is `calibrated`, never `synthesized`."""
    corrections = patches.patches(personas)
    if not corrections:
        return tuple(personas)
    patched = []
    for persona in personas:
        updates = corrections.get(persona.persona_id)
        if not updates:
            patched.append(persona)
            continue
        conditioning = dict(persona.conditioning)
        attributes = dict(persona.attributes)
        origins = dict(persona.origins)
        for attribute, value in updates.items():
            (conditioning if attribute in conditioning else attributes)[attribute] = value
            origins[attribute] = FieldOrigin.CALIBRATED
        patched.append(
            persona.model_copy(
                update={
                    "conditioning": FrozenDict(conditioning),
                    "attributes": FrozenDict(attributes),
                    "origins": FrozenDict(origins),
                }
            )
        )
    return tuple(patched)


def _embed(personas: Sequence[Persona], embed: EmbedPort, pack) -> tuple[tuple[Persona, ...], np.ndarray]:
    """One embedding call for the population, and a positional reference on each persona."""
    texts = [_persona_text(persona, pack.ontology) for persona in personas]
    vectors = np.asarray(embed.embed(texts), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(personas):
        raise GateFailure(
            f"the embedding port returned shape {vectors.shape}; expected one vector per persona for "
            f"{len(personas)} personas"
        )
    references = tuple(
        EmbeddingRef(model_id=embed.model_id, dim=int(vectors.shape[1]), index=index) for index in range(len(personas))
    )
    embedded = tuple(persona.model_copy(update={"embedding": reference}) for persona, reference in zip(personas, references))
    return embedded, vectors


def _persona_text(persona: Persona, ontology) -> str:
    fields: dict[AttributeId, AttributeValue] = {**persona.conditioning, **persona.attributes}
    return "; ".join(f"{attribute}={fields[attribute]}" for attribute in ontology.relevance_order if attribute in fields)
