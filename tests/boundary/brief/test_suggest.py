"""What the codebook has that resembles a name it does not carry.

The suggestions are the whole of the refusal's usefulness: a researcher who typed `income`
is told which of the corpus's compound names they probably meant. The names below are the
real codebook's, and each expectation is one that character similarity alone got wrong.
"""

import pytest

from simcore.brief._codebook import suggest_attributes

ATTRIBUTES = (
    "age_bracket", "life_stage", "primary_language", "lang_greek", "lang_hebrew",
    "demo_household_income", "att_universal_basic_income", "ind_e_commerce", "ind_media", "filmg_comedy",
    "demo_sexual_orientation", "gender_identity", "tool_blender", "musg_indie",
    "lstyle_exercise_freq", "coding_ai_usage_frequency", "cuis_french",
    "media_diet", "lstyle_diet_type", "health_dietary_restriction",
    "lifex_parenting_journey", "demo_parental_status", "modality_pref",
    "demo_employment_status", "val_fun_enjoyment", "topic_self_improvement",
)


class Codebook:
    attributes = ATTRIBUTES

    def vocabulary(self, attribute):
        return () if attribute in ATTRIBUTES else None


@pytest.mark.parametrize(
    ("typed", "meant"),
    [
        ("age", "age_bracket"),
        ("agee", "age_bracket"),
        ("income", "demo_household_income"),
        ("sex", "demo_sexual_orientation"),
        ("exercise_frequency", "lstyle_exercise_freq"),
        ("diet_protein_focus", "lstyle_diet_type"),
        ("employment", "demo_employment_status"),
        ("gender", "gender_identity"),
        ("agge_bracket", "age_bracket"),
    ],
)
def test_a_name_is_met_with_the_attribute_it_shares_words_with(typed, meant):
    assert meant in suggest_attributes(typed, Codebook())


def test_the_attribute_sharing_the_most_words_comes_first():
    assert suggest_attributes("exercise_frequency", Codebook())[0] == "lstyle_exercise_freq"


def test_a_name_with_nothing_in_common_suggests_nothing_rather_than_noise():
    assert suggest_attributes("zzzz", Codebook()) == ()


def test_suggestions_are_bounded_and_distinct():
    found = suggest_attributes("income", Codebook(), limit=2)
    assert len(found) == 2 and len(set(found)) == 2
