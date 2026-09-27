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
    def label(self, attribute: str) -> str: ...
    def category(self, attribute: str) -> str: ...


_ATTITUDE_WORDS = frozenset({
    "attitude", "att_", "value", "values", "interest", "opinion", "belief",
    "trust", "sentiment", "lean", "religios", "ideolog", "tolerance",
    "satisfaction", "confidence", "worry", "fear", "pride", "empathy",
})

_HABIT_WORDS = frozenset({
    "habit", "frequency", "freq", "uses", "usage", "spending", "saving",
    "budget", "exercise", "cook", "subscription", "smok", "drink", "diet",
    "sleep", "commute", "shop", "travel", "routine", "practice",
})

_MONEY_WORDS = frozenset({
    "income", "money", "wealth", "socioeconomic", "employment", "employ",
    "work", "job", "salary", "wage", "occupation", "profession",
})

_DECIDE_WORDS = frozenset({"decision", "risk", "choice", "style", "closure", "impuls"})

_MEDIA_WORDS = frozenset({"media", "read", "watch", "news", "social", "linguistic", "language", "learn"})


def _haystack(attribute: str, label: str, category: str) -> str:
    return f"{attribute} {label} {category}".lower()


def _has_any(haystack: str, words: frozenset[str]) -> bool:
    return any(word in haystack for word in words)


def measures_of(attribute: str, label: str = "", category: str = "") -> str:
    """What an attribute measures, in the builder's words — taken from its id
    and category, never from a model. An attitude, value or interest is how
    people feel rather than what they do."""
    hay = _haystack(attribute, label, category)
    if _has_any(hay, _ATTITUDE_WORDS):
        return "how people feel rather than what they do"
    if _has_any(hay, _HABIT_WORDS):
        return "what people do regularly"
    return "a fact about the person"


def kind_of(attribute: str, label: str = "", category: str = "") -> str:
    """The ontology table's kind column, in plain words."""
    family = (category.split(":")[0] if ":" in category else category).strip().lower()
    hay = _haystack(attribute, label, category)
    if _has_any(hay, _MONEY_WORDS):
        return "Money & work"
    if _has_any(hay, _DECIDE_WORDS) or family.startswith("risk"):
        return "How they decide"
    if _has_any(hay, _MEDIA_WORDS) or family in {"linguistic", "learning"}:
        return "What they read & watch"
    if family in {"personality", "values & motivation", "worldview", "state"}:
        return "How they think"
    if family in {"behavior", "health", "skills", "developer", "professional", "expertise", "interests"}:
        return "What they do"
    return "Who they are"


def _words(name: str) -> list[str]:
    return [word for word in re.split(r"[^a-z0-9]+", name.lower()) if word]


def _kin(word: str, other: str) -> bool:
    """Two words that are the same word, or one is the other cut short: `freq`/`frequency`."""
    if word == other:
        return True
    short, long = sorted((word, other), key=len)
    return len(short) >= 3 and long.startswith(short)


_SYNONYMS: dict[str, tuple[str, ...]] = {
    "kid": ("child", "children", "parent", "parenthood", "family"),
    "kids": ("child", "children", "parent", "parenthood", "family"),
    "child": ("kid", "kids", "parent", "parenthood"),
    "children": ("kid", "kids", "parent", "parenthood"),
    "parent": ("child", "children", "kid", "kids", "parenthood"),
    "parents": ("child", "children", "kid", "kids", "parenthood"),
    "money": ("income", "wealth", "salary", "economic", "socioeconomic", "spending", "saving"),
    "wealthy": ("wealth", "income", "socioeconomic", "rich", "affluent"),
    "wealth": ("income", "socioeconomic", "money"),
    "income": ("money", "wealth", "salary", "socioeconomic"),
    "salary": ("income", "money", "wage", "wealth"),
    "poor": ("income", "wealth", "socioeconomic"),
    "rich": ("wealth", "income", "socioeconomic"),
    "married": ("marital", "marriage", "spouse"),
    "student": ("education", "school", "life_stage"),
    "students": ("education", "school", "life_stage"),
    "retired": ("retirement", "retire", "life_stage", "employment"),
    "religious": ("religion", "religiosity", "faith"),
    "politics": ("political", "ideology", "lean"),
}


def expand_terms(terms: list[str]) -> list[str]:
    expanded = list(terms)
    for term in terms:
        expanded.extend(_SYNONYMS.get(term, ()))
    return expanded


def word_search(query: str, codebook: CodebookLike, limit: int = 5) -> tuple[str, ...]:
    """Attributes matching `query` by words over ids, labels and categories.

    Terms match when a word of the attribute text starts with the term or the
    term starts with it, so "kids" finds children and "wealthy" finds wealth.
    A small synonym map covers the cases letters alone cannot reach ("kids"
    shares no letters with "children"). Most shared terms first, most similar
    text second.
    """
    terms = [word for word in re.split(r"[^a-z0-9]+", query.lower()) if word]
    if not terms:
        return ()
    wanted = expand_terms(terms)
    ranked: list[tuple[int, float, str]] = []
    for attribute in codebook.attributes:
        label = codebook.label(attribute) if hasattr(codebook, "label") else ""
        category = codebook.category(attribute) if hasattr(codebook, "category") else ""
        text = f"{attribute.replace('_', ' ')} {label} {category}".lower()
        words = [word for word in re.split(r"[^a-z0-9]+", text) if word]
        shared = sum(
            1 for term in wanted
            if any(term in word or word in term or _kin(term, word) for word in words if len(word) > 2)
        )
        if shared:
            similarity = difflib.SequenceMatcher(None, query.lower(), text).ratio()
            ranked.append((-shared, -similarity, attribute))
    return tuple(attribute for *_, attribute in sorted(ranked)[:limit])


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


__all__ = ["expand_terms", "kind_of", "measures_of", "suggest_attributes", "validate_against_codebook", "word_search"]
