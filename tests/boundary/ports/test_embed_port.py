"""Phase 1: the embedding port the real client satisfies.

The port promises vectors in input order with the pinned and served model and the cost
of every batch. The fake and the real client both satisfy it, and population's embedding
step accepts either and builds the same array shape."""

import json

import httpx
import numpy as np

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.ports import EmbedPort
from simcore.ports.fake import FakeEmbed
from simcore.schemas import CostSource, InferenceRole, InferenceRoute, ModelPins
from tests.boundary.inference.test_embeddings import TEXTS, client_for, embed_reply


def test_the_port_returns_vectors_in_order_with_models_and_costs():
    fake = FakeEmbed(dim=8)
    assert isinstance(fake, EmbedPort)
    result = fake.embed(TEXTS)
    assert result.vectors.shape == (len(TEXTS), 8)
    assert result.model_id == fake.model_id == "fake-embed"
    assert result.served_model_id == "fake-embed"
    assert result.costs and all(cost.role is InferenceRole.EMBED for cost in result.costs)
    second = FakeEmbed(dim=8).embed(TEXTS)
    assert np.allclose(result.vectors, second.vectors)


def test_the_fake_stays_deterministic_across_processes():
    import subprocess
    import sys

    code = (
        "from simcore.ports.fake import FakeEmbed;"
        "import json;"
        "fake = FakeEmbed(dim=8);"
        "result = fake.embed(['alpha', 'beta']);"
        "print(json.dumps(result.vectors.tolist()))"
    )
    first = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    second = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert first == second


def test_the_real_client_satisfies_the_port_over_a_scripted_transport():
    recorder_holder = {}

    import tests.boundary.inference.test_embeddings as emb

    recorder = emb.Recorder(emb.embed_reply())
    client, _ = emb.client_for(recorder)
    assert isinstance(client, EmbedPort)
    result = client.embed(TEXTS)
    assert result.vectors.shape == (len(TEXTS), 4)
    assert result.model_id == result.served_model_id == emb.EMBED
    assert result.costs and result.costs[0].role is InferenceRole.EMBED
    assert recorder_holder is not None


def test_population_embedding_accepts_the_real_client_with_the_same_shape():
    from simcore.population import build
    from simcore.ports.fake import FakeChat
    from simcore.ports.synthetic import AttributeShape, SyntheticCoresetSource, SyntheticShape
    from simcore.schemas import BriefPack
    from tests.study_builders import pack_payload
    import tests.boundary.inference.test_embeddings as emb

    shape = SyntheticShape(
        {
            "age": AttributeShape(("18_24", "25_34", "35_44", "45_54")),
            "sex": AttributeShape(("female", "male")),
            "exercise_frequency": AttributeShape(("rarely", "weekly", "3_plus_weekly")),
            "diet_protein_focus": AttributeShape(("low", "medium", "high")),
            "spend_band": AttributeShape(("5_10", "10_20")),
        },
        rows=5000,
    )
    pack = BriefPack.model_validate(pack_payload())

    def build_with(embed, seed=11):
        coreset = SyntheticCoresetSource(shape, seed=seed)
        return build(pack, 20, 4021, coreset=coreset, inference=FakeChat(), embed=embed)

    fake_result = build_with(FakeEmbed(dim=4))
    assert fake_result.embeddings is not None and fake_result.embeddings.shape == (20, 4)

    recorder = emb.Recorder(emb.embed_reply(dim=4))
    client, _ = emb.client_for(recorder, embeddings_batch_size=64)
    real_result = build_with(client)
    assert real_result.embeddings is not None and real_result.embeddings.shape == (20, 4)
