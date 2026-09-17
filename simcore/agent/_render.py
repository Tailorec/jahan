"""Persona rendering: the ontology-selected block, rendered once and reused.

The block renders the persona's projected attributes in the ontology's relevance order —
conditioning first, since the ontology guarantees it leads the order — one attribute per
line in the salvaged MatrAIx phrase style. A category that selects different attributes
produces a different block. Rendering is pure; the cache in front of it renders once per
persona per run and reuses the text across ticks.
"""

from __future__ import annotations

from simcore.schemas import CategoryOntology, Persona, canonical_hash

from ._prompt import hash_text


def selected_attributes(persona: Persona, ontology: CategoryOntology) -> list[tuple[str, object]]:
    """The persona's projected attributes the ontology declares, in relevance order."""
    projected = {**persona.conditioning, **persona.attributes}
    return [(name, projected[name]) for name in ontology.relevance_order if name in projected]


def render_block(persona: Persona, ontology: CategoryOntology) -> str:
    """The persona block for one ontology: selected attributes, most relevant first."""
    lines = ["You are the following person:"]
    for name, value in selected_attributes(persona, ontology):
        lines.append(f"- {name}: {value}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


class PersonaBlockCache:
    """Rendered blocks keyed by persona and ontology, so a long horizon reuses them.

    The cache is held by the runner and passed into `turns`; the agent itself stores
    nothing. `renders` counts fresh renders, which is what the reuse test asserts on.
    """

    def __init__(self) -> None:
        self._blocks: dict[tuple[str, str], str] = {}
        self.renders = 0

    def block_for(self, persona: Persona, ontology: CategoryOntology) -> tuple[str, str]:
        key = (persona.persona_id, canonical_hash(ontology))
        cached = self._blocks.get(key)
        if cached is None:
            cached = render_block(persona, ontology)
            self._blocks[key] = cached
            self.renders += 1
        return cached, hash_text(cached)
