"""Which audience a persona belongs to: the first brief audience whose filters it matches.

A persona is counted in exactly one audience mass. Filters overlap in practice — the
representative personas match both example audiences — so the first match in brief order
wins, deterministically. Personas matching nothing are unassigned and contribute to the
action mix and belief movement but to no audience mass.
"""

from collections.abc import Mapping

from simcore.schemas import AttributeFilter, BandRange, CategoryOntology, Exactly, OneOf, Persona


def _band_order(ontology: CategoryOntology) -> dict[str, list[str]]:
    return {scale.attribute: [band.label for band in scale.bands] for scale in ontology.ordinal_scales}


def _matches_value(value: object, predicate: AttributeFilter, bands: list[str] | None) -> bool:
    if isinstance(predicate, Exactly):
        return value == predicate.value
    if isinstance(predicate, OneOf):
        return value in predicate.values
    if isinstance(predicate, BandRange):
        if bands is None or not isinstance(value, str) or value not in bands:
            return False
        try:
            position = bands.index(value)
            return bands.index(predicate.first) <= position <= bands.index(predicate.last)
        except ValueError:
            return False
    return False


def audience_of_persona(
    persona: Persona,
    audiences: tuple,
    ontology: CategoryOntology,
) -> str | None:
    """The first audience whose filters the persona matches on its projected fields, if any."""
    fields: Mapping[str, object] = {**persona.conditioning, **persona.attributes}
    order = _band_order(ontology)
    for audience in audiences:
        matches = True
        for attribute, predicate in audience.attribute_filters.items():
            if attribute not in fields or not _matches_value(fields[attribute], predicate, order.get(attribute)):
                matches = False
                break
        if matches:
            return audience.name
    return None
