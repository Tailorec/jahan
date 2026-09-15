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
    weakest_origin,
)

from ._assess import _gate_results, sample, targets_for
from ._communities import detect
from ._graph import build_graph
from ._project import project
from ._streams import spawn

# The tiers a distribution gate may judge, matching the population's invariant.
_GATEABLE_TIERS = frozenset({FieldOrigin.MEASURED, FieldOrigin.EXTRACTED})


@dataclass(frozen=True)
class BuiltPopulation:
    """A validated population and the embedding array its personas index into when enabled. The array
    travels beside the contract, never inside it; what the graph measured travels inside it, on the report."""

    population: Population
    embeddings: np.ndarray | None = None


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
    sampled = sample(pack, n, population_seed, coreset=coreset, admissible=parameters.admissible_sources)
    distribution, _ = _gate_results(
        pack.ontology, coreset, sampled.references, sampled.rows, parameters.distribution_gates, targets_for(pack, sampled)
    )
    # The verdict is the draw's, and it is enforced before any model is called: completion then cannot
    # touch it, assess() and build() cannot disagree about it, and a doomed study costs nothing.
    _reject_failed(distribution)
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
    kept = _true_of_the_population(distribution, personas)
    report = GateReport(
        results=kept + graph_build.results,
        attribute_origins=_origins_for(kept, personas),
        source_mix=sampled.source_mix,
        achieved_mix=sampled.achieved_mix,
        relaxations=sampled.relaxations,
        assortativity=FrozenDict(graph_build.assortativity),
        audience_assortativity=graph_build.audience_assortativity,
    )
    population = Population(
        pack=pack,
        manifest=manifest,
        personas=personas,
        gate_report=report,
        graph=graph_build.graph,
        communities=communities,
    )
    return BuiltPopulation(population, embeddings)


def _requested_mix(pack) -> FrozenDict:
    shares = pack.brief.audience_shares
    return shares if shares is not None else FrozenDict({})


def _reject_failed(results: Sequence) -> None:
    """Refuse a draw that failed any distribution gate, naming the attributes, before anything is spent."""
    failed = [result.attribute for result in results if not result.passed]
    if failed:
        raise GateFailure(f"the sample failed its distribution gates before any model was called: {failed}")


def _true_of_the_population(results: Sequence, personas: Sequence[Persona]) -> tuple:
    """The draw's gates that may travel with the population it became.

    Every verdict was already enforced on the draw, so this never changes whether a population is built.
    A gate was computed from grounded values; once completion or a patch changes an attribute's values, a
    gate over that attribute would describe the draw rather than the population, and the contract keeps a
    population's gates true of its own values."""
    return tuple(
        result
        for result in results
        if all(
            persona.origins[result.attribute] in _GATEABLE_TIERS
            for persona in personas
            if result.attribute in persona.origins
        )
    )


def _origins_for(results: Sequence, personas: Sequence[Persona]) -> FrozenDict:
    """The weakest tier each gated attribute carries in the population, so the report's grade is a fact
    about the values a reader will see rather than about the draw that preceded a patch or completion."""
    return FrozenDict(
        {
            result.attribute: weakest_origin(
                persona.origins[result.attribute] for persona in personas if result.attribute in persona.origins
            )
            for result in results
        }
    )


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
