"""An ontology checked against the corpus it claims to describe.

The codebook's attributes are what can be studied — bounded by the data rather
than by which files exist. Every name is checked as it is entered: an attribute
the corpus does not carry is refused, naming what the codebook does have that
resembles it. Ordinal scales are built from the codebook's own labels in the
order the codebook states them. A draft may be authored without the corpus
present, but it cannot become a version until it validates against one.
"""

from __future__ import annotations

import difflib
import re
from typing import Protocol

from simcore.schemas import CategoryOntology


class CodebookLike(Protocol):
    """What validation needs of a codebook: its attribute names and their
    vocabularies. A protocol, never a concrete adapter — core imports the
    protocol only, and any corpus-backed codebook answers it."""

    @property
    def attributes(self) -> tuple[str, ...]: ...
    def vocabulary(self, attribute: str) -> tuple[str, ...] | None: ...


def _words(name: str) -> list[str]:
    return [word for word in re.split(r"[^a-z0-9]+", name.lower()) if word]


def _kin(word: str, other: str) -> bool:
    """Two words that are the same word, or one is the other cut short: `freq`/`frequency`."""
    if word == other:
        return True
    short, long = sorted((word, other), key=len)
    return len(short) >= 3 and long.startswith(short)


def suggest_attributes(name: str, codebook: CodebookLike, limit: int = 3) -> tuple[str, ...]:
    """What the codebook has that resembles a name it does not carry.

    The codebook's names are compound (`demo_household_income`), so what a person types
    (`income`) shares a word with the attribute they meant far more often than it shares
    letters: attributes that share words come first, most shared first, and character
    similarity fills what is left. Letters alone suggested `ind_e_commerce` for `income`.
    """
    wanted = _words(name)
    ranked: list[tuple[int, float, int, str]] = []
    for attribute in codebook.attributes:
        shared = sum(1 for word in wanted if any(_kin(word, have) for have in _words(attribute)))
        if shared:
            similarity = difflib.SequenceMatcher(None, name.lower(), attribute.lower()).ratio()
            ranked.append((-shared, -similarity, len(attribute), attribute))
    found = [attribute for *_, attribute in sorted(ranked)][:limit]
    for attribute in difflib.get_close_matches(name, list(codebook.attributes), limit, cutoff=0.6):
        if len(found) >= limit:
            break
        if attribute not in found:
            found.append(attribute)
    return tuple(found)


def validate_against_codebook(ontology: CategoryOntology, codebook: CodebookLike) -> None:
    """Refuse an ontology the corpus cannot back, naming what moved.

    Raises `ValueError` — the web layer renders it as a 422 — so a study can
    never be authored that dies four shards into its first draw.
    """
    carried = set(codebook.attributes)
    unknown = sorted(set(ontology.attribute_domains) - carried)
    if unknown:
        hints = {name: suggest_attributes(name, codebook) for name in unknown}
        rendered = "; ".join(
            f"{name!r} (did you mean {', '.join(repr(s) for s in suggestions)})" if suggestions
            else repr(name)
            for name, suggestions in hints.items()
        )
        raise ValueError(f"the corpus carries no such attribute: {rendered}")
    for scale in ontology.ordinal_scales:
        vocabulary = codebook.vocabulary(scale.attribute)
        if vocabulary is None:  # unreachable once domains are checked, kept for the message
            raise ValueError(f"the corpus carries no such attribute: {scale.attribute!r}")
        labels = [band.label for band in scale.bands]
        outside = sorted(set(labels) - set(vocabulary))
        if outside:
            raise ValueError(
                f"scale for {scale.attribute!r} names values the corpus does not carry: {outside}; "
                f"the codebook holds {list(vocabulary)}"
            )
        # Order is the scale's own business — bands run midpoint-ascending by
        # contract — while the labels must be the codebook's own: an invented
        # band silently breaks the filters and gates that never saw it.
    if ontology.targets is not None:
        for attribute, shares in ontology.targets.marginals.items():
            vocabulary = codebook.vocabulary(attribute) or ()
            outside = sorted(set(shares) - set(vocabulary))
            if outside:
                raise ValueError(
                    f"targets for {attribute!r} name values the corpus does not carry: {outside}"
                )


__all__ = ["suggest_attributes", "validate_against_codebook"]
