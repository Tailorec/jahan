"""Ready for a study: Continue validates and saves, then opens the launch form.

The draft becomes the engine's own artefacts: the category's ontology reused
as it is, a new patch version adding the declared attributes with the
conditioning set unchanged, or a new category at 1.0.0. No version a past
study pinned is ever overwritten — saving refuses an existing version. Every
piece is checked by the engine's own types before anything is written.
"""

from __future__ import annotations


def prepare_launch(category: dict, rows: list[dict], audiences: list[dict], assumptions: list[dict], ontology_lookup, codebook) -> dict:
    """Validate the ontology and audiences with the engine's own types and say
    what saving will do: reuse, a new patch version, or a new category."""
    from simcore.brief._codebook import validate_against_codebook
    from simcore.schemas import Assumption, Audience, CategoryOntology

    if not isinstance(category, dict) or not category.get("id"):
        raise ValueError("confirm the category before continuing")
    category_id = category["id"]
    before = ontology_lookup(category_id) if category.get("mode") == "reuse" else None
    domains = {row["id"]: row.get("domain") or "category_behaviour" for row in rows}
    required = [row["id"] for row in rows if row.get("required")]
    if not required:
        raise ValueError("a category conditions on at least one attribute")
    if before is not None:
        scales_before = {scale["attribute"]: scale for scale in before.get("ordinal_scales") or []}
        scales = [scales_before[attribute] for attribute in domains if attribute in scales_before]
        unchanged = (
            domains == before.get("attribute_domains")
            and set(required) == set(before.get("conditioning_set") or [])
            and {scale["attribute"] for scale in scales} == {scale["attribute"] for scale in before.get("ordinal_scales") or []}
        )
        if unchanged:
            version = before["version"]
            action = "reused"
        else:
            version = _bump(before["version"])
            action = "new_version"
        ontology = {
            "category": category_id,
            "version": version,
            "attribute_domains": domains,
            "conditioning_set": list(before.get("conditioning_set") or []),
            "completion_policy": before.get("completion_policy") or {"completable_domains": ["economic", "media", "decision_rule"]},
            "ordinal_scales": scales,
            "relevance_order": [a for a in (before.get("conditioning_set") or []) if a in domains]
            + [row["id"] for row in rows if row["id"] not in (before.get("conditioning_set") or [])],
            "anchor_sets": before.get("anchor_sets") or {"purchase_intent": "purchase-intent-v1"},
            "targets": before.get("targets"),
            "drafting": None,
        }
        from_version = before["version"]
    else:
        ontology = {
            "category": category_id,
            "version": "1.0.0",
            "attribute_domains": domains,
            "conditioning_set": required,
            "completion_policy": {"completable_domains": ["economic", "media", "decision_rule"]},
            "ordinal_scales": [],
            "relevance_order": required + [row["id"] for row in rows if not row.get("required")],
            "anchor_sets": {"purchase_intent": "purchase-intent-v1"},
            "targets": None,
            "drafting": None,
        }
        action = "new_category"
        from_version = None
    exported_audiences = [
        {"name": audience.get("name") or "audience", "share": audience.get("share"),
         "attribute_filters": {
             attribute: (values[0] if len(values) == 1 else values)
             for attribute, values in (audience.get("filters") or {}).items() if values
         }}
        for audience in audiences
    ]
    exported_assumptions = [
        {"text": assumption.get("text"), "source": assumption.get("source") or "assumed"}
        for assumption in assumptions
    ]
    parsed = CategoryOntology.model_validate(ontology)
    validate_against_codebook(parsed, codebook)
    undeclared = sorted({key for audience in exported_audiences for key in audience["attribute_filters"]} - set(domains))
    if undeclared:
        raise ValueError(f"audiences filter on attributes the ontology does not declare: {undeclared}")
    for audience in exported_audiences:
        Audience.model_validate(audience)
    for assumption in exported_assumptions:
        Assumption.model_validate(assumption)
    return {
        "ontology": parsed.model_dump(mode="json"),
        "audiences": exported_audiences,
        "assumptions": exported_assumptions,
        "action": action,
        "from_version": from_version,
    }


def _bump(version: str) -> str:
    major, minor, patch = (int(part) for part in str(version).split("."))
    return f"{major}.{minor}.{patch + 1}"
