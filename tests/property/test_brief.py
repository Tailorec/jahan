import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    BriefPack,
    CategoryOntology,
    ClaimId,
    ClaimSource,
    Competitor,
    OrdinalScale,
    PersonaFieldDomain,
    Price,
    ProductBrief,
    canonical_hash,
)

ONTOLOGY = {
    "category": "beverage_protein",
    "version": "1.0.0",
    "attribute_domains": {
        "age": "demographic",
        "exercise_frequency": "category_behaviour",
        "diet_protein_focus": "psychographic",
    },
    "conditioning_set": ["age", "exercise_frequency"],
    "completion_policy": {"completable_domains": ["economic", "decision_rule", "media"]},
    "ordinal_scales": [
        {
            "attribute": "exercise_frequency",
            "bands": [
                {"label": "rarely", "midpoint": 0.25},
                {"label": "weekly", "midpoint": 1.0},
                {"label": "3_plus_weekly", "midpoint": 4.0},
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
        "ontology_version": "1.0.0",
    }
    payload.update(overrides)
    return payload


def ontology_payload(**overrides):
    payload = copy.deepcopy(ONTOLOGY)
    payload.update(overrides)
    return payload


# --- brief ---------------------------------------------------------------------------------


def test_minimal_brief_validates():
    brief = ProductBrief.model_validate(brief_payload())
    assert brief.price.currency == "USD"
    assert brief.ontology_version == "1.0.0"
    assert brief.audiences_declared is False


def test_brief_names_its_ontology_rather_than_embedding_one():
    with pytest.raises(ValidationError, match="ontology"):
        ProductBrief.model_validate(brief_payload(ontology=ONTOLOGY))
    payload = brief_payload()
    del payload["ontology_version"]
    with pytest.raises(ValidationError, match="ontology_version"):
        ProductBrief.model_validate(payload)


def test_unknown_key_refused_at_top_level_and_nested():
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(brief_payload(unexpected_key=True))
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(brief_payload(claims=[{"text": "x", "source": "assumed", "extra": 1}]))


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


@pytest.mark.parametrize(
    ("ids", "match"),
    [(["C1", "C1"], "duplicated"), (["C1", "C3"], "contiguous"), (["C2", "C1"], "contiguous")],
    ids=["duplicate", "gap", "out-of-order"],
)
def test_bad_explicit_claim_ids_refused(ids, match):
    claims = [{"id": claim_id, "text": f"claim {n}", "source": "assumed"} for n, claim_id in enumerate(ids)]
    with pytest.raises(ValidationError, match=match):
        ProductBrief.model_validate(brief_payload(claims=claims))


def test_partially_assigned_claim_ids_refused():
    payload = brief_payload(
        claims=[
            {"id": "C1", "text": "first", "source": "user_asserted"},
            {"text": "second", "source": "assumed"},
        ]
    )
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(payload)


def test_blank_claim_ids_refused_rather_than_renumbered():
    payload = brief_payload(
        claims=[{"id": "", "text": "first", "source": "user_asserted"}, {"id": "", "text": "second", "source": "assumed"}]
    )
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(payload)


def test_reordering_claims_moves_brief_hash():
    first = ProductBrief.model_validate(brief_payload())
    swapped = brief_payload()
    swapped["claims"] = [swapped["claims"][1], swapped["claims"][0]]
    assert canonical_hash(first) != canonical_hash(ProductBrief.model_validate(swapped))


def test_reformatting_whitespace_does_not_move_brief_hash():
    first = ProductBrief.model_validate(brief_payload())
    second = ProductBrief.model_validate(
        brief_payload(
            product={
                "name": "  Protein water ",
                "category": " beverage_protein ",
                "description": "  Clear protein-infused water  ",
            },
            claims=[{"text": " 20g protein with zero sugar ", "source": "user_asserted"}]
            + brief_payload()["claims"][1:],
        )
    )
    assert canonical_hash(first) == canonical_hash(second)


@pytest.mark.parametrize("amount", [0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_price_refuses_non_positive_or_non_finite_amount(amount):
    with pytest.raises(ValidationError):
        Price(amount=amount, currency="USD")


@pytest.mark.parametrize("currency", ["usd", "USDX", "DOLLAR", ""])
def test_price_refuses_malformed_currency(currency):
    with pytest.raises(ValidationError):
        Price(amount=2.49, currency=currency)


def test_competitor_claims_are_optional_text():
    assert Competitor(name="Electrolyte water").claims == ()
    assert Competitor(name="Clear whey shooter", claims=["25g protein"]).claims == ("25g protein",)
    with pytest.raises(ValidationError):
        Competitor(name="Clear whey shooter", claims=["   "])


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
    audience = {"name": "gym_regulars", "attribute_filters": {}}
    with pytest.raises(ValidationError, match="duplicated"):
        ProductBrief.model_validate(brief_payload(audiences=[audience, audience]))


def test_audience_filter_keys_must_be_attribute_identifiers():
    with pytest.raises(ValidationError):
        ProductBrief.model_validate(
            brief_payload(audiences=[{"name": "gym_regulars", "attribute_filters": {"exercise frequency": "weekly"}}])
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


# --- ontology ------------------------------------------------------------------------------


def test_ontology_declares_conditioning_set_completion_policy_and_scales():
    ontology = CategoryOntology.model_validate(ontology_payload())
    assert ontology.conditioning_set == {"age", "exercise_frequency"}
    assert ontology.attribute_domains["exercise_frequency"] is PersonaFieldDomain.CATEGORY_BEHAVIOUR
    assert [band.label for band in ontology.ordinal_scales[0].bands] == ["rarely", "weekly", "3_plus_weekly"]


@pytest.mark.parametrize("domain", [PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC])
def test_completion_policy_refuses_demographic_and_psychographic(domain):
    with pytest.raises(ValidationError, match="never synthesized"):
        CategoryOntology.model_validate(
            ontology_payload(completion_policy={"completable_domains": ["economic", domain.value]})
        )


def test_conditioning_set_must_be_non_empty():
    with pytest.raises(ValidationError):
        CategoryOntology.model_validate(ontology_payload(conditioning_set=[]))


@pytest.mark.parametrize("field", ["conditioning_set", "ordinal_scales"])
def test_attributes_the_ontology_uses_must_declare_a_domain(field):
    domains = dict(ONTOLOGY["attribute_domains"])
    del domains["exercise_frequency"]
    payload = ontology_payload(attribute_domains=domains)
    if field == "conditioning_set":
        payload["ordinal_scales"] = []
    else:
        payload["conditioning_set"] = ["age"]
    with pytest.raises(ValidationError, match="no declared domain"):
        CategoryOntology.model_validate(payload)


def test_attribute_domain_must_be_a_known_domain():
    with pytest.raises(ValidationError):
        CategoryOntology.model_validate(ontology_payload(attribute_domains={**ONTOLOGY["attribute_domains"], "age": "behavioural"}))


def test_ordinal_scale_accepts_real_unit_midpoints():
    scale = OrdinalScale.model_validate(
        {"attribute": "age_band", "bands": [{"label": "18-24", "midpoint": 21}, {"label": "25-34", "midpoint": 29.5}]}
    )
    assert [band.midpoint for band in scale.bands] == [21.0, 29.5]


@pytest.mark.parametrize(
    ("bands", "match"),
    [
        ([{"label": "weekly", "midpoint": 1.0}], "two bands"),
        ([{"label": "weekly", "midpoint": 1.0}, {"label": "rarely", "midpoint": 0.25}], "ascending"),
        ([{"label": "weekly", "midpoint": 1.0}, {"label": "weekly", "midpoint": 4.0}], "duplicated"),
    ],
    ids=["single-band", "descending", "duplicate-label"],
)
def test_ambiguous_ordinal_scale_refused(bands, match):
    with pytest.raises(ValidationError, match=match):
        OrdinalScale.model_validate({"attribute": "exercise_frequency", "bands": bands})


def test_one_ordinal_scale_per_attribute():
    scale = ONTOLOGY["ordinal_scales"][0]
    with pytest.raises(ValidationError, match="more than one ordinal scale"):
        CategoryOntology.model_validate(ontology_payload(ordinal_scales=[scale, scale]))


# --- brief pack ----------------------------------------------------------------------------


def pack(brief=None, ontology=None) -> BriefPack:
    return BriefPack.model_validate({"brief": brief or brief_payload(), "ontology": ontology or ontology_payload()})


def test_pack_joins_a_brief_with_the_ontology_it_names():
    packed = pack()
    assert packed.ontology.version == packed.brief.ontology_version
    assert packed.ontology.category == packed.brief.product.category


@pytest.mark.parametrize(
    "ontology_override", [{"version": "2.0.0"}, {"category": "snack_bar"}], ids=["other-version", "other-category"]
)
def test_pack_refuses_an_ontology_the_brief_does_not_name(ontology_override):
    with pytest.raises(ValidationError, match="read against ontology"):
        pack(ontology=ontology_payload(**ontology_override))


def test_pack_refuses_audience_filter_on_undeclared_attribute():
    brief = brief_payload(audiences=[{"name": "gym_regulars", "attribute_filters": {"exercise_frequncy": "weekly"}}])
    with pytest.raises(ValidationError, match="does not declare"):
        pack(brief=brief)


def test_pack_refuses_audience_filter_value_outside_ordinal_bands():
    brief = brief_payload(audiences=[{"name": "gym_regulars", "attribute_filters": {"exercise_frequency": "daily"}}])
    with pytest.raises(ValidationError, match="not one of its bands"):
        pack(brief=brief)


def test_pack_accepts_free_values_on_non_ordinal_attributes():
    brief = brief_payload(audiences=[{"name": "protein_dieters", "attribute_filters": {"diet_protein_focus": "high"}}])
    assert pack(brief=brief).brief.audiences[0].name == "protein_dieters"


def test_ontology_edits_move_the_ontology_hash_not_the_brief_hash():
    before, after = pack(), pack(ontology=ontology_payload(conditioning_set=["age"]))
    assert canonical_hash(before.brief) == canonical_hash(after.brief)
    assert canonical_hash(before.ontology) != canonical_hash(after.ontology)


# --- generated -----------------------------------------------------------------------------

word = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)
money = st.floats(0.01, 1_000.0, allow_nan=False, allow_infinity=False)


@given(
    product_name=word,
    claim_pairs=st.lists(st.tuples(word, st.sampled_from([source.value for source in ClaimSource])), min_size=1, max_size=4),
    price_amount=money,
    audience_names=st.lists(word, unique=True, max_size=3),
    assumption_texts=st.lists(word, max_size=3),
    competitor_claims=st.lists(word, max_size=3),
)
def test_pack_round_trips_over_generated_values(
    product_name, claim_pairs, price_amount, audience_names, assumption_texts, competitor_claims
):
    brief = brief_payload(
        product={"name": product_name, "category": "beverage_protein", "description": "description"},
        price={"amount": price_amount, "currency": "USD"},
        claims=[{"text": text, "source": source} for text, source in claim_pairs],
        competitors=[{"name": "rival", "claims": competitor_claims}],
        audiences=[{"name": name, "attribute_filters": {"diet_protein_focus": name}} for name in audience_names],
        assumptions=[{"text": text, "source": "assumed"} for text in assumption_texts],
    )
    packed = pack(brief=brief)
    assert BriefPack.model_validate(packed.model_dump(mode="json")) == packed
    assert BriefPack.model_validate_json(packed.model_dump_json()) == packed
