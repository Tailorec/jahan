"""Phase 4: anchors as frozen versions."""

import json
from pathlib import Path

import pytest

from simcore.elicitation import anchor_hash, load_anchor_version, resolve_anchors

ANCHORS_DIR = Path(__file__).resolve().parents[3] / "anchors"

# Recorded when each family was first pinned: a changed statement is a new version, so any edit
# to these files breaks this test by design.
PINNED_HASHES = {
    "purchase-intent-v1": "7b253b23107a98b43380d3e1632397fad5cb370748641139e09dd2d1b09d516e",
    "satisfaction-v1": "85b7386751157fdab44dd6660c898642e31612c7f4ca94d4012e5efe5eec69ce",
}


def _version(construct: str, version: str = "v1"):
    return load_anchor_version(ANCHORS_DIR / construct / f"{version}.json")


def test_a_version_declares_its_construct_and_version_with_six_sets_of_five():
    for construct in ("purchase_intent", "satisfaction"):
        parsed = _version(construct)
        assert parsed.construct == construct and parsed.version == "v1"
        assert len(parsed.sets) == 6
        assert all(len(anchor_set) == 5 for anchor_set in parsed.sets)


def _raises_on(extra: bool = False):
    import tempfile

    raw = json.loads((ANCHORS_DIR / "purchase_intent" / "v1.json").read_text())
    if extra:
        raw["extra"] = "not allowed"
    else:
        raw["sets"] = raw["sets"][:5]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(raw, handle)
        name = handle.name
    with pytest.raises(ValueError, match="not a frozen version"):
        load_anchor_version(name)


def test_short_versions_are_refused():
    _raises_on(extra=False)


def test_a_version_identity_is_its_content_hash_and_unpinned_or_altered_is_refused():
    pinned = {"purchase-intent-v1": PINNED_HASHES["purchase-intent-v1"]}
    resolved = resolve_anchors("purchase-intent-v1", "purchase_intent", "v1", pinned, ANCHORS_DIR)
    assert anchor_hash(resolved) == PINNED_HASHES["purchase-intent-v1"]
    with pytest.raises(ValueError, match="not pinned"):
        resolve_anchors("someone-else-v9", "purchase_intent", "v1", pinned, ANCHORS_DIR)
    with pytest.raises(ValueError, match="altered"):
        resolve_anchors("purchase-intent-v1", "purchase_intent", "v1", {"purchase-intent-v1": "00" * 32}, ANCHORS_DIR)


def test_both_families_exist_with_varied_wording_across_sets():
    for construct in ("purchase_intent", "satisfaction"):
        parsed = _version(construct)
        assert len(parsed.sets) == 6
        flat = [" ".join(anchor_set).lower() for anchor_set in parsed.sets]
        for first in range(6):
            for second in range(first + 1, 6):
                shared = set(flat[first].split()) & set(flat[second].split())
                overlap = len(shared) / max(len(set(flat[first].split())), 1)
                assert overlap < 0.8, f"{construct} sets {first} and {second} read as paraphrases"
        assert len({tuple(anchor_set) for anchor_set in parsed.sets}) == 6


def test_categories_share_the_purchase_intent_family_and_may_name_another():
    import json as _json

    for category in ("beverage_protein", "software_dev"):
        ontology = _json.loads((Path(__file__).resolve().parents[3] / "ontologies" / category / "1.0.0.json").read_text())
        assert ontology["anchor_sets"]["purchase_intent"] == "purchase-intent-v1"
    from simcore.schemas import CategoryOntology

    ontology = CategoryOntology.model_validate(
        _json.loads((Path(__file__).resolve().parents[3] / "ontologies" / "beverage_protein" / "1.0.0.json").read_text())
    )
    assert ontology.model_copy(update={"anchor_sets": {"purchase_intent": "custom-pi-v2"}}).anchor_sets["purchase_intent"] == "custom-pi-v2"


def test_no_anchor_file_was_modified_after_its_version_was_first_pinned():
    assert anchor_hash(_version("purchase_intent")) == PINNED_HASHES["purchase-intent-v1"]
    assert anchor_hash(_version("satisfaction")) == PINNED_HASHES["satisfaction-v1"]
