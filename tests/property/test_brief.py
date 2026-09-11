from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

import pytest

from simcore.schemas import (
    ClaimId,
    ClaimSource,
    PersonaFieldDomain,
    Price,
    ProductBrief,
    canonical_hash,
)

ONTOLOGY = {
    "category": "beverage_protein",
    "version": "1.0.0",
    "conditioning_set": ["age", "exercise_frequency"],
    "completion_policy": {"completable_domains": ["economic", "decision_rule", "media"]},
    "ordinal_scales": [
        {
            "attribute": "exercise_frequency",
            "bands": [
                {"label": "rarely", "midpoint": 0.1},
                {"label": "weekly", "midpoint": 0.5},
                {"label": "daily", "midpoint": 0.9},
            ],
        }
    ],
}

EVIDENCE = {
    "url": "https://example.com/study",
    "fetched_at": "2026-09-01T00:00:00Z",
    "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}


def brief_payload(**overrides):
    payload = {
        "product": {
            "name": "Protein water",
            "category": "beverage_protein",
            "description": "Clear protein-infused water",
        },
        "price": {"amount": 2.49, "currency": "USD"},
        "claims": [
            {"text": "20g protein with zero sugar", "source": "user_asserted"},
            {"text": "Hydrates like water, not milk", "source": "assumed"},
        ],
        "target_market": "US urban adults who train regularly",
        "ontology": ONTOLOGY,
    }
    payload.update(overrides)
    return payload


def test_minimal_brief_validates():
    brief = ProductBrief.model_validate(brief_payload())
    assert brief.price.currency == "USD"
    assert brief.audiences_declared is False


def test_unknown_key_refused():
    for path, extra in (("top", {"unexpected_key": True}), ("claim", {"claims": [{"text": "x", "source": "assumed", "extra": 1}]})):
        payload = brief_payload()
        if path == "top":
            payload.update(extra)
        else:
            payload["claims"] = extra["claims"] + payload["claims"][1:]
        with pytest.raises(ValidationError):
            ProductBrief.model_validate(payload)


def test_claim_ids_assigned_automatically_and_contiguous():
    brief = ProductBrief.model_validate(brief_payload())
    assert [claim.id for claim in brief.claims] == ["C1", "C2"]

    three = brief_payload()
    three["claims"] = three["claims"] + [{"text": "third", "source": "public_source"}]
    assert [claim.id for claim in ProductBrief.model_validate(three).claims] == ["C1", "C2", "C3"]


def test_explicit_contiguous_ids_accepted():
    payload = brief_payload(
        claims=[
            {"id": "C1", "text": "first", "source": "user_asserted"},
            {"id": "C2", "text": "second", "source": "assumed"},
        ]
    )
    assert [claim.id for claim in ProductBrief.model_validate(payload).claims] == ["C1", "C2"]


def test_duplicate_claim_ids_refused():
    payload = brief_payload(
        claims=[
            {"id": "C1", "text": "first", "source": "user_asserted"},
            {"id": "C1", "text": "second", "source": "assumed"},
        ]
    )
    with pytest.raises(ValidationError, match="duplicated"):
        ProductBrief.model_validate(payload)


def test_non_contiguous_claim_ids_refused():
    payload = brief_payload(
        claims=[
            {"id": "C1", "text": "first", "source": "user_asserted"},
            {"id": "C3", "text": "second", "source": "assumed"},
        ]
    )
    with pytest.raises(ValidationError, match="contiguous"):
        ProductBrief.model_validate(payload)


def test_out_of_order_claim_ids_refused():
    payload = brief_payload(
        claims=[
            {"id": "C2", "text": "first", "source": "user_asserted"},
            {"id": "C1", "text": "second", "source": "assumed"},
        ]
    )
    with pytest.raises(ValidationError, match="contiguous"):
        ProductBrief.model_validate(payload)


def test_partially_assigned_claim_ids_refused():
    payload = brief_payload(
        claims=[
            {"id": "C1", "text": "first", "source": "user_asserted"},
            {"text": "second", "source": "assumed"},
        ]
    )
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(payload)


def test_reordering_claims_moves_brief_hash():
    first = ProductBrief.model_validate(brief_payload())
    swapped = brief_payload()
    swapped["claims"] = [swapped["claims"][1], swapped["claims"][0]]
    second = ProductBrief.model_validate(swapped)
    assert canonical_hash(first) != canonical_hash(second)


def test_reformatting_whitespace_does_not_move_brief_hash():
    first = ProductBrief.model_validate(brief_payload())
    second = ProductBrief.model_validate(
        brief_payload(
            product={
                "name": "  Protein water ",
                "category": " beverage_protein ",
                "description": "  Clear protein-infused water  ",
            },
            claims=[{"text": " 20g protein with zero sugar ", "source": "user_asserted"}] + brief_payload()["claims"][1:],
        )
    )
    assert canonical_hash(first) == canonical_hash(second)


@pytest.mark.parametrize("amount", [0.0, -1.0])
def test_price_refuses_non_positive_amount(amount):
    with pytest.raises(ValidationError):
        Price(amount=amount, currency="USD")


@pytest.mark.parametrize("currency", ["usd", "USDX", "DOLLAR", ""])
def test_price_refuses_malformed_currency(currency):
    with pytest.raises(ValidationError):
        Price(amount=2.49, currency=currency)


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
def test_price_refuses_non_finite_amount(amount):
    with pytest.raises(ValidationError):
        Price(amount=amount, currency="USD")


def test_audiences_are_declared_and_referenceable_by_name():
    brief = ProductBrief.model_validate(
        brief_payload(
            audiences=[
                {"name": "gym_regulars", "attribute_filters": {"exercise_frequency": "3_plus_weekly"}},
                {"name": "protein_dieters", "attribute_filters": {"diet_protein_focus": "high"}},
            ]
        )
    )
    assert brief.audiences_declared is True
    weights = {audience.name: 0.5 for audience in brief.audiences}
    assert weights == {"gym_regulars": 0.5, "protein_dieters": 0.5}


def test_duplicate_audience_names_refused():
    payload = brief_payload(
        audiences=[
            {"name": "gym_regulars", "attribute_filters": {}},
            {"name": "gym_regulars", "attribute_filters": {}},
        ]
    )
    with pytest.raises(ValidationError, match="duplicated"):
        ProductBrief.model_validate(payload)


def test_completion_policy_refuses_demographic_and_psychographic():
    for domain in (PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC):
        with pytest.raises(ValidationError, match="never synthesized"):
            ProductBrief.model_validate(
                brief_payload(
                    ontology={
                        **ONTOLOGY,
                        "completion_policy": {"completable_domains": ["economic", domain.value]},
                    }
                )
            )


def test_conditioning_set_must_be_non_empty():
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(brief_payload(ontology={**ONTOLOGY, "conditioning_set": []}))


def test_ordinal_scale_bands_must_be_ascending():
    with pytest.raises(ValidationError, match="ascending"):
        ProductBrief.model_validate(
            brief_payload(
                ontology={
                    **ONTOLOGY,
                    "ordinal_scales": [
                        {
                            "attribute": "exercise_frequency",
                            "bands": [
                                {"label": "weekly", "midpoint": 0.5},
                                {"label": "rarely", "midpoint": 0.1},
                            ],
                        }
                    ],
                }
            )
        )


def test_ordinal_scale_needs_two_bands():
    with pytest.raises(ValidationError, match="two bands"):
        ProductBrief.model_validate(
            brief_payload(
                ontology={
                    **ONTOLOGY,
                    "ordinal_scales": [
                        {"attribute": "exercise_frequency", "bands": [{"label": "weekly", "midpoint": 0.5}]}
                    ],
                }
            )
        )


def test_ontology_category_must_match_product_category():
    with pytest.raises(ValidationError, match="category"):
        ProductBrief.model_validate(
            brief_payload(ontology={**ONTOLOGY, "category": "snack_bar"})
        )


def test_claim_id_format():
    claim_id = TypeAdapter(ClaimId)
    assert claim_id.validate_python("C1") == "C1"
    assert claim_id.validate_python("C12") == "C12"
    for bad in ("C0", "C01", "claim_1", "c1", ""):
        with pytest.raises(ValidationError):
            claim_id.validate_python(bad)


def test_evidence_is_optional_and_typed_when_present():
    brief = ProductBrief.model_validate(
        brief_payload(
            claims=[
                {"text": "clinically tested hydration", "source": "public_source", "evidence": EVIDENCE},
                {"text": "no evidence claim", "source": "assumed"},
            ]
        )
    )
    evidenced, bare = brief.claims
    assert evidenced.evidence.fetched_at.year == 2026
    assert evidenced.evidence.fetched_at.tzinfo is not None
    assert len(evidenced.evidence.content_hash) == 64
    assert bare.evidence is None


def test_evidence_refuses_content_hash_that_is_not_sha256_hex():
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(
            brief_payload(claims=[{"text": "claim", "source": "public_source", "evidence": {**EVIDENCE, "content_hash": "deadbeef"}}])
        )


def test_evidence_fetch_time_must_carry_a_timezone():
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(
            brief_payload(
                claims=[{"text": "claim", "source": "public_source", "evidence": {**EVIDENCE, "fetched_at": "2026-09-01T00:00:00"}}]
            )
        )


def evidenced_brief(fetched_at: str) -> ProductBrief:
    return ProductBrief.model_validate(
        brief_payload(claims=[{"text": "claim", "source": "public_source", "evidence": {**EVIDENCE, "fetched_at": fetched_at}}])
    )


def test_refetching_unchanged_evidence_does_not_move_brief_hash():
    assert canonical_hash(evidenced_brief("2026-09-01T00:00:00Z")) == canonical_hash(evidenced_brief("2026-09-02T09:30:00Z"))


def test_changed_evidence_content_moves_brief_hash():
    changed = brief_payload(
        claims=[{"text": "claim", "source": "public_source", "evidence": {**EVIDENCE, "content_hash": "ab" * 32}}]
    )
    assert canonical_hash(evidenced_brief("2026-09-01T00:00:00Z")) != canonical_hash(ProductBrief.model_validate(changed))


def test_every_claim_source_value_is_usable_in_a_brief():
    for source in ClaimSource:
        payload = brief_payload(claims=[{"text": "claim", "source": source.value}])
        assert ProductBrief.model_validate(payload).claims[0].source is source


word = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)
unit = st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False)
money = st.floats(0.01, 1_000.0, allow_nan=False, allow_infinity=False)


@given(
    product_name=word,
    claim_pairs=st.lists(
        st.tuples(word, st.sampled_from([source.value for source in ClaimSource])), min_size=1, max_size=4
    ),
    price_amount=money,
    audience_names=st.lists(word, unique=True, max_size=3),
    assumption_texts=st.lists(word, max_size=3),
)
def test_brief_round_trips_over_generated_values(product_name, claim_pairs, price_amount, audience_names, assumption_texts):
    payload = {
        "product": {"name": product_name, "category": "beverage_protein", "description": "description"},
        "price": {"amount": price_amount, "currency": "USD"},
        "claims": [{"text": text, "source": source} for text, source in claim_pairs],
        "target_market": "target_market",
        "audiences": [{"name": name, "attribute_filters": {}} for name in audience_names],
        "assumptions": [{"text": text, "source": "assumed"} for text in assumption_texts],
        "ontology": ONTOLOGY,
    }
    brief = ProductBrief.model_validate(payload)
    assert ProductBrief.model_validate(brief.model_dump(mode="json")) == brief
    assert ProductBrief.model_validate_json(brief.model_dump_json()) == brief
