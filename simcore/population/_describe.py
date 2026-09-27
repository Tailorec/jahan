"""Describe, then confirm the category — before anything is drafted.

`POST /api/describe` reads the description into a `Reading`: the product,
the groups with the traits that decide membership, traits every group shares,
and topics. The product is matched against existing categories as a closed
choice. The reading is shown before any draft, with a way to rephrase.
Nothing is drafted before the person answers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Phrases with a guess word are topics that matter, never traits — enforced in
# code, because the reader is told and does not always obey.
GUESSES = re.compile(
    r"\b(interested in|interest in|possibly|probably|likely|might|may be|tend to|tends to|could be|would)\b",
    re.I,
)

PARSE_SYSTEM = (
    "A researcher describes who they want to study. Return:\n"
    "- product: what is being tested, in a few words, or null if they do not say;\n"
    "- audiences: the distinct groups of people named, each with a short snake_case name, a share (a number between 0 "
    "and 1) only if the researcher states proportions, and the traits that decide who belongs to it, as short phrases "
    "about the person (e.g. 'has young children', 'retired', 'lives in the US'). Only what the researcher states as "
    "deciding membership is a trait; one idea is one trait (a group described by an age, a place and a job has three "
    "traits);\n"
    "- everyone: traits every group shares;\n"
    "- matters: topics the researcher wants to know about these people but that do not decide who is in a group "
    "(e.g. 'how careful they are with money', 'trust in apps'). Anything the researcher only guesses at ('possibly', "
    "'likely', 'might', 'interested in', 'tend to') is a topic that matters, never a trait.\n"
    "Return only the groups the description itself names — none from these instructions; a description that names no "
    "group returns no audiences. If it names one group, return one audience. Use the researcher's meaning, not their "
    "exact words. "
    'Reply with only JSON: {"product": "", "audiences": [{"name": "", "share": null, "traits": [""]}], "everyone": [""], "matters": [""]}'
)
CATEGORY_SYSTEM = (
    "You decide whether a product belongs to an existing study category. A category groups products similar enough "
    "that studies of them should be compared. You get the product and the existing categories, each as `id: products "
    "studied under it`. Match only if it is the same kind of product. Reply with only JSON: "
    '{"match": "<existing id or null>", "new_id": "<a short snake_case id for a new category>"}'
)


@dataclass(frozen=True)
class Group:
    """One named group with the traits that decide membership."""

    name: str
    share: float | None
    traits: tuple[str, ...]


@dataclass(frozen=True)
class Reading:
    """How the description was read: product, groups, shared traits, topics."""

    product: str | None
    groups: tuple[Group, ...]
    everyone: tuple[str, ...]
    topics: tuple[str, ...]

    def to_json(self) -> dict:
        return {
            "product": self.product,
            "groups": [
                {"name": group.name, "share": group.share, "traits": list(group.traits)}
                for group in self.groups
            ],
            "everyone": list(self.everyone),
            "topics": list(self.topics),
        }


def sanitise(parsed: dict) -> dict:
    """A phrase with a guess word moves from traits to topics, where it
    describes people and excludes nobody — whatever the model returned."""
    matters = [topic for topic in parsed.get("matters") or [] if isinstance(topic, str) and topic.strip()]
    for audience in parsed.get("audiences") or []:
        if isinstance(audience, dict):
            kept = []
            for trait in audience.get("traits") or []:
                (matters if isinstance(trait, str) and GUESSES.search(trait) else kept).append(trait)
            audience["traits"] = kept
    everyone = []
    for trait in parsed.get("everyone") or []:
        (matters if isinstance(trait, str) and GUESSES.search(trait) else everyone).append(trait)
    parsed["everyone"] = everyone
    parsed["matters"] = list(dict.fromkeys(matter for matter in matters if isinstance(matter, str)))
    return parsed


def read_description(chat_json, text: str) -> Reading:
    """Read the description into groups, shared traits and topics."""
    parsed = sanitise(chat_json(PARSE_SYSTEM, text, 700) or {})
    groups = []
    for audience in parsed.get("audiences") or []:
        if not isinstance(audience, dict):
            continue
        share = audience.get("share")
        groups.append(Group(
            name=str(audience.get("name") or "audience"),
            share=share if isinstance(share, (int, float)) and 0 < share <= 1 else None,
            traits=tuple(trait for trait in audience.get("traits") or [] if isinstance(trait, str) and trait.strip()),
        ))
    product = parsed.get("product")
    return Reading(
        product=str(product).strip() or None if product is not None else None,
        groups=tuple(groups),
        everyone=tuple(trait for trait in parsed.get("everyone") or [] if isinstance(trait, str)),
        topics=tuple(topic for topic in parsed.get("matters") or [] if isinstance(topic, str)),
    )


def ontology_versions(folder: Path) -> list[Path]:
    """A category's saved versions, oldest first, ordered as numbers: text order puts 1.0.10 before 1.0.2."""
    return sorted(Path(folder).glob("*.json"), key=lambda path: tuple(int(part) if part.isdigit() else -1 for part in path.stem.split(".")))


def list_categories(ontology_root: Path | None, runs_root: Path | None, codebook) -> list[dict]:
    """Existing categories a description may reuse: each one's latest ontology,
    offered only when the codebook carries every attribute it names. Each names
    the products studied in it, read from the briefs its studies ran on."""
    import yaml

    products: dict[str, list[str]] = {}
    if runs_root is not None and Path(runs_root).is_dir():
        for path in sorted(Path(runs_root).glob("*/brief.yaml")):
            try:
                brief = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            product = brief.get("product") if isinstance(brief, dict) else None
            if isinstance(product, dict) and product.get("category"):
                named = products.setdefault(str(product["category"]), [])
                if str(product.get("name") or "") not in named:
                    named.append(str(product.get("name") or ""))
    carried = set(codebook.attributes)
    found = []
    root = Path(ontology_root) if ontology_root is not None else None
    if root is not None and root.is_dir():
        for folder in sorted(child for child in root.iterdir() if child.is_dir()):
            versions = ontology_versions(folder)
            if not versions:
                continue
            data = json.loads(versions[-1].read_text(encoding="utf-8"))
            attributes = list(data.get("relevance_order") or data.get("attribute_domains") or {})
            if attributes and all(attribute in carried for attribute in attributes):
                found.append({
                    "id": data["category"],
                    "version": data["version"],
                    "products": products.get(data["category"], []),
                })
    return found


def match_category(chat_json, product: str | None, categories: list[dict]) -> tuple[dict | None, str]:
    """Match the product against existing categories — a closed choice. The
    model can name an existing category or none; anything else is refused."""
    by_id = {category["id"]: category for category in categories}
    match = None
    new_id = _slug(product or "my_category")
    if product:
        listing = "\n".join(
            f"{category['id']}: {', '.join(p for p in category['products'] if p) or category['id'].replace('_', ' ')}"
            for category in categories
        )
        try:
            verdict = chat_json(CATEGORY_SYSTEM, f"Existing categories:\n{listing}\n\nProduct: {product}", 120) or {}
        except Exception:
            verdict = {}
        if verdict.get("match") in by_id:
            match = by_id[verdict["match"]]
        new_id = _slug(verdict.get("new_id") or product)
    while new_id in by_id:
        new_id = f"{new_id}_2"
    return match, new_id


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")[:48] or "my_category"


def describe(chat_json, text: str, ontology_root, runs_root, codebook) -> dict:
    """Read the description and say which category it seems to belong to."""
    reading = read_description(chat_json, text)
    categories = list_categories(ontology_root, runs_root, codebook)
    match, new_id = match_category(chat_json, reading.product, categories)
    return {
        "reading": reading.to_json(),
        "product": reading.product,
        "match": match,
        "new_id": new_id,
        "categories": categories,
    }
