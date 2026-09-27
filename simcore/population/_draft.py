"""Drafting from the description: a confirmed category and a reading become a draft.

The category's own attributes come first — reused and locked, or the
cross-survey core for a new category. Each trait is matched among 20
candidates by meaning, with their value counts in view; the server refuses an
attribute it did not offer and a value outside the attribute's list. A trait
matched differently with and without the rest of the description becomes a
question, and no filter is applied until the person answers. Traits become
filters in their audiences, topics become descriptions, and no trait becomes
a requirement. The drafter is checked, not trusted.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

SURVEY_SOURCES = ("stackoverflow", "gss", "prism", "real_human_survey")

PICK_VALUES = (
    "Pick the attribute and value(s) from a persona dataset that capture what the researcher means. You get candidate "
    "attributes, each with its values and how many people hold each value. Choose ONE attribute and the value(s) that "
    "fit the researcher's meaning, copied exactly. Prefer attributes and values many people hold. If nothing fits, use "
    'null. Reply with only JSON: {"id": "<attribute id or null>", "values": ["<value>"]}'
)
PICK_TOPIC = (
    "Pick the one attribute from a persona dataset that best captures a topic the researcher wants to know about. You "
    "get candidate attributes with how many people carry each. Prefer attributes many people carry. If nothing fits, "
    'use null. Reply with only JSON: {"id": "<attribute id or null>"}'
)


@dataclass(frozen=True)
class DraftQuestion:
    """A trait the drafter matched differently with and without context: the
    choices side by side with head counts, and "neither" — no filter applied."""

    phrase: str
    choices: tuple[dict, ...]
    applies_to: tuple[str, ...]

    def to_json(self) -> dict:
        return {"phrase": self.phrase, "choices": [dict(choice) for choice in self.choices], "applies_to": list(self.applies_to)}


@dataclass(frozen=True)
class Draft:
    """Audiences with filters, the questions awaiting answers, what could not
    be found, and each attribute's role: required, defines, describes."""

    audiences: tuple[dict, ...]
    attributes: tuple[dict, ...]
    questions: tuple[DraftQuestion, ...]
    unmatched: tuple[dict, ...]

    def to_json(self) -> dict:
        return {
            "audiences": [dict(audience) for audience in self.audiences],
            "attributes": [dict(attribute) for attribute in self.attributes],
            "questions": [question.to_json() for question in self.questions],
            "unmatched": [dict(item) for item in self.unmatched],
        }


def cross_survey_core(matrix) -> list[str]:
    """The cross-survey core: attributes at least half of every survey source answered."""
    core = []
    for position, attribute in enumerate(matrix.attributes):
        column = matrix.codes[position] != -1
        if all(_share(matrix, column, source) >= 0.5 for source in SURVEY_SOURCES if source in matrix.sources):
            core.append(attribute)
    return core


def _share(matrix, column, source: str) -> float:
    total = matrix.totals.get(source, 0)
    if not total:
        return 0.0
    position = matrix.sources.index(source)
    return float((column & (matrix.row_source == position)).sum()) / total


def _candidates(phrase: str, sources, matrix, codebook, embeddings, limit: int = 20) -> tuple[list[int], str]:
    """20 candidates by meaning — or by words where embeddings are unavailable."""
    if embeddings is not None:
        try:
            from simcore.ports.embeddings import _embed, embed_model, endpoint_base, rank_meaning
            from simcore.population._search import _shares

            vector = _embed([phrase.strip().lower()], embed_model(), endpoint_base() or "")[0]
            norm = float(np.linalg.norm(vector)) or 1.0
            vector = (np.asarray(vector, dtype=np.float32) / norm).tolist()
            _, score = rank_meaning(vector, embeddings, _shares(matrix, tuple(sources)))
            order = [int(i) for i in np.argsort(-score)[:limit] if score[int(i)] > -5]
            return order, "meaning"
        except Exception:
            pass
    from simcore.brief._codebook import word_search

    ordered = word_search(phrase, codebook, limit=limit * 4)
    index_of = {attribute: position for position, attribute in enumerate(matrix.attributes)}
    return [index_of[attribute] for attribute in ordered if attribute in index_of][:limit], "words"


def _attribute_entry(matrix, codebook, attribute: str, role: str, phrase, required: bool = False, locked: bool = False) -> dict:
    from simcore.brief._codebook import kind_of, measures_of

    return {
        "id": attribute,
        "label": codebook.label(attribute),
        "category": codebook.category(attribute),
        "measures": measures_of(attribute, codebook.label(attribute), codebook.category(attribute)),
        "kind": kind_of(attribute, codebook.label(attribute), codebook.category(attribute)),
        "values": list(codebook.vocabulary(attribute) or ()),
        "required": required,
        "locked": locked,
        "role": role,
        "phrase": phrase,
    }


def resolve(chat_json, phrase: str, sources, want_values: bool, matrix, codebook, embeddings, context: str = "") -> dict:
    """One short phrase → one attribute (and values), chosen by the model among
    20 candidates with counts in view, then checked."""
    from simcore.population._pool import value_counts

    candidate_ids, _ = _candidates(phrase, sources, matrix, codebook, embeddings)
    offered = {matrix.attributes[i] for i in candidate_ids}
    everyone = matrix.pool_mask(tuple(sources), ())
    if want_values:
        lines = []
        for i in candidate_ids:
            attribute = matrix.attributes[i]
            counts = value_counts(matrix, tuple(sources), (), attribute)
            lines.append(f"{attribute}: {codebook.label(attribute)} — " + ", ".join(f"{c['value']} ({c['n']:,})" for c in counts))
    else:
        lines = [
            f"{matrix.attributes[i]}: {codebook.label(matrix.attributes[i])} — "
            f"{int(((everyone) & (matrix.codes[i] != -1)).sum()):,} people"
            for i in candidate_ids
        ]
    framing = f"Whole description: {context}\n\n" if context else ""
    chosen = chat_json(
        PICK_VALUES if want_values else PICK_TOPIC,
        "Candidates:\n" + "\n".join(lines) + f"\n\n{framing}Researcher means: {phrase}",
        200,
    ) or {}
    attribute = chosen.get("id")
    if not attribute:
        return {"phrase": phrase, "missing": "nothing in the corpus fits it"}
    if attribute not in offered or attribute not in matrix.attributes:
        return {"phrase": phrase, "missing": f"the model named {attribute!r}, which it was not offered"}
    position = matrix.attributes.index(attribute)
    result = {
        "phrase": phrase,
        "attribute": attribute,
        "label": codebook.label(attribute),
        "entry": _attribute_entry(matrix, codebook, attribute, "filter", phrase),
        "options": [
            {"id": matrix.attributes[j], "label": codebook.label(matrix.attributes[j]),
             "carried": int((everyone & (matrix.codes[j] != -1)).sum())}
            for j in candidate_ids[:8] if j != position
        ],
    }
    if want_values:
        vocabulary = list(codebook.vocabulary(attribute) or ())
        exact = {str(value).lower(): str(value) for value in vocabulary}
        picked = chosen.get("values") or []
        picked = picked if isinstance(picked, list) else [picked]
        values = [exact[str(value).lower()] for value in picked if str(value).lower() in exact]
        if not values:
            return {"phrase": phrase, "missing": f"the model chose {codebook.label(attribute)} but no value from its list ({picked})"}
        result["values"] = sorted(values, key=vocabulary.index)
        mask = everyone & (matrix.codes[position] != -1)
        codes = {vocabulary.index(value) for value in result["values"]}
        result["n_alone"] = int((mask & np.isin(matrix.codes[position], list(codes))).sum())
    return result


def settle(chat_json, phrase: str, sources, matrix, codebook, embeddings, context: str) -> dict:
    """Match a trait twice — with the whole description and on its own. The
    same attribute both times is applied; two different ones become a question."""
    with_context = resolve(chat_json, phrase, sources, True, matrix, codebook, embeddings, context)
    alone = resolve(chat_json, phrase, sources, True, matrix, codebook, embeddings, "")
    good = [result for result in (with_context, alone) if "attribute" in result]
    if not good:
        return {"phrase": phrase, "missing": with_context.get("missing") or alone.get("missing")}
    if len(good) == 1 or good[0]["attribute"] == good[1]["attribute"]:
        return {**good[0], "agreed": True}
    return {"phrase": phrase, "agreed": False, "choices": good}


def draft(chat_json, text: str, reading, category: dict, sources, matrix, codebook, embeddings, ontology_lookup) -> Draft:
    """A confirmed category and a reading become audiences and an ontology draft."""
    attributes: list[dict] = []
    if category.get("mode") == "reuse":
        ontology = ontology_lookup(category["id"])
        if ontology is None:
            raise ValueError(f"no saved ontology for category {category['id']!r}")
        for attribute in ontology.get("relevance_order") or ontology.get("attribute_domains") or {}:
            entry = _attribute_entry(matrix, codebook, attribute, "category", None,
                                     required=attribute in (ontology.get("conditioning_set") or []), locked=True)
            entry["domain"] = ontology["attribute_domains"][attribute]
            attributes.append(entry)
    else:
        for attribute in cross_survey_core(matrix):
            attributes.append(_attribute_entry(matrix, codebook, attribute, "core", None, required=True))
    known = {entry["id"] for entry in attributes}

    everyone = [trait for trait in reading.everyone if isinstance(trait, str) and trait.strip()]
    matters = [topic for topic in reading.topics if isinstance(topic, str) and topic.strip()]
    groups = [group for group in reading.groups]
    traits = sorted({trait for group in groups for trait in group.traits} | set(everyone))
    with ThreadPoolExecutor(max_workers=6) as workers:
        settled = dict(zip(traits, workers.map(lambda t: settle(chat_json, t, sources, matrix, codebook, embeddings, text), traits)))
        topics = list(workers.map(lambda t: resolve(chat_json, t, sources, False, matrix, codebook, embeddings), matters))

    built = []
    for group in groups:
        filters: dict[str, list[str]] = {}
        phrases: dict[str, str] = {}
        options: dict[str, list[dict]] = {}
        unsure: list[dict] = []
        for trait in [*group.traits, *everyone]:
            result = settled.get(trait, {})
            if result.get("agreed"):
                attribute = result["attribute"]
                vocabulary = list(codebook.vocabulary(attribute) or ())
                filters[attribute] = sorted({*filters.get(attribute, []), *result["values"]}, key=vocabulary.index)
                phrases[attribute] = trait
                options[attribute] = result.get("options", [])
            elif result.get("agreed") is False and all(item["phrase"] != trait for item in unsure):
                unsure.append({"phrase": trait, "choices": [
                    {"attribute": choice["attribute"], "label": choice["label"], "values": choice["values"],
                     "n_alone": choice["n_alone"], "options": choice.get("options", [])}
                    for choice in result["choices"]
                ]})
        built.append({"name": group.name, "share": group.share, "filters": filters,
                      "phrases": phrases, "options": options, "unsure": unsure, "descriptions": []})
    if built and all(audience["share"] is None for audience in built):
        for audience in built:
            audience["share"] = round(1 / len(built), 4)

    # Declared, never required: a trait every group shares is a filter in each
    # audience, not a requirement (ADR 0047).
    used = [attribute for audience in built for attribute in audience["filters"]]
    for attribute in dict.fromkeys(used):
        if attribute not in known:
            phrase = next((audience["phrases"][attribute] for audience in built if attribute in audience["phrases"]), None)
            attributes.append(_attribute_entry(matrix, codebook, attribute, "filter", phrase))
            known.add(attribute)
    for topic in topics:
        if "attribute" in topic and topic["attribute"] not in known:
            attributes.append(_attribute_entry(matrix, codebook, topic["attribute"], "matters", topic["phrase"]))
            known.add(topic["attribute"])

    by_phrase: dict[str, dict] = {}
    for audience in built:
        for item in audience["unsure"]:
            entry = by_phrase.setdefault(item["phrase"], {"phrase": item["phrase"], "choices": item["choices"], "applies_to": []})
            entry["applies_to"].append(audience["name"])
    questions = tuple(
        DraftQuestion(phrase=item["phrase"], choices=tuple(item["choices"]), applies_to=tuple(item["applies_to"]))
        for item in by_phrase.values()
    )
    unmatched = tuple(
        {"phrase": result["phrase"], "missing": result["missing"]}
        for result in [*settled.values(), *topics] if "missing" in result
    )
    return Draft(audiences=tuple(built), attributes=tuple(attributes), questions=questions, unmatched=unmatched)
