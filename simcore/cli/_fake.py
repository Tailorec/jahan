"""The `--fake` backend: a synthetic coreset and stub inference, no key, no download, no network.

The synthetic corpus is derived from the study itself: an attribute the ontology scales
takes its bands, one the brief filters takes the literals the filter names, and an
attribute needing neither takes a small fixed vocabulary — any consistent one, since no
filter distinguishes its values and the gates judge the draw against its own design.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from simcore.ports.chat import ChatMessage
from simcore.ports.fake import FakeChat, FakeEmbed
from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
from simcore.schemas import BriefPack, Completion

FAKE_TIER_A = "fake/tier-a-1"
FAKE_TIER_B = "fake/tier-b-1"
FAKE_EMBED = "fake/embed-1"
FAKE_RECSYS_EMBED = "fake/recsys-embed-1"
FAKE_ROWS = 4000


class RoleFakeChat(FakeChat):
    """One stub behind every tier, billing each role's own pin.

    The agent reaches every tier through one chat port, but the trace refuses a
    cost billed to a model the run did not pin for that role — so the stub bills
    what the role pins, exactly as a routed gateway would.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._role_models = {"tier_a": FAKE_TIER_A, "tier_b": FAKE_TIER_B}

    def _one(self, request):
        outcome = super()._one(request)
        if isinstance(outcome, Completion):
            model_id = self._role_models.get(request.role.value, self._model_id)
            cost = outcome.cost.model_copy(update={"model_id": model_id, "served_model_id": model_id})
            return outcome.model_copy(update={"cost": cost})
        return outcome


def fake_pins() -> dict:
    """The model pins a fake study runs under, fixed so two fake runs agree."""
    return {"tier_a": FAKE_TIER_A, "tier_b": FAKE_TIER_B, "embed": FAKE_EMBED, "recsys_embed": FAKE_RECSYS_EMBED}


def synthetic_shape(pack: BriefPack, rows: int = FAKE_ROWS) -> SyntheticShape:
    """The synthetic corpus for `--fake`: every attribute the study can filter or gate on."""
    brief, ontology = pack.brief, pack.ontology
    bands = {scale.attribute: tuple(band.label for band in scale.bands) for scale in ontology.ordinal_scales}
    literals: dict[str, set[str]] = {}
    for audience in brief.audiences:
        for attribute, predicate in audience.attribute_filters.items():
            values: tuple = ()
            if hasattr(predicate, "value"):
                values = (predicate.value,)
            elif hasattr(predicate, "values"):
                values = tuple(predicate.values)
            else:
                values = (predicate.first, predicate.last)
            literals.setdefault(attribute, set()).update(str(value) for value in values)
    attributes = sorted(set(ontology.conditioning_set) | set(literals))
    shape = {}
    for attribute in attributes:
        vocabulary = tuple(dict.fromkeys((*bands.get(attribute, ()), *sorted(literals.get(attribute, ())))))
        if not vocabulary:
            vocabulary = ("group_a", "group_b")
        shape[attribute] = AttributeShape(tuple(vocabulary))
    return SyntheticShape(shape, rows=rows)


def fake_responder(messages: Sequence[ChatMessage], template_id: str) -> str:
    """How a stub persona answers: about the first thing shown, always the same words.

    This is the `--fake` stand-in for a persona, deterministic by construction — no
    number it produces is behaviour, which is exactly what makes two fake runs under
    one seed agree. Probes take the first option; reactions answer about the first
    shown stimulus with a small fixed belief move so the run exercises findings; a
    reflection consolidates with a small further move, which a study only reaches once
    it runs long enough for the cadence to fire.
    """
    user = json.loads(next(message for message in reversed(messages) if message.get("role") == "user")["content"])
    if "questions" in user:
        answers = []
        for question in user["questions"]:
            options = question.get("options", [])
            answers.append(options[0] if options else "(none)")
        return json.dumps({"answers": answers})
    if "shown" in user:
        shown = user["shown"]
        return json.dumps({
            "subject_stimulus_id": shown[0]["stimulus_id"],
            "action": "answer",
            "verbatim": "I would try it after training",
            "belief_deltas": {"dimensions": {"value": 0.05}},
        })
    if "memories" in user:
        return json.dumps({
            "dimensions": {"value": 0.01},
            "claim_credence": {},
            "summary": "Looking back, the protein claim still reads the same to me. Nothing has changed my mind.",
        })
    raise ValueError(f"the stub persona was asked something it has no answer for: {sorted(user)}")


def fake_backend(pack: BriefPack, *, seed: int):
    """The fake inference ports and coreset over the study's own shape."""
    chat = RoleFakeChat(responder=fake_responder, model_id=FAKE_TIER_A)
    embed = FakeEmbed(model_id=FAKE_EMBED)
    coreset = SyntheticCoresetSource(synthetic_shape(pack), seed=seed)
    return chat, embed, coreset
