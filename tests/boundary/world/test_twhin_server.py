"""The TwHIN-BERT server returns `pooler_output`, truncated at 512 tokens, as OASIS computes it.

Needs torch, transformers and the model weights, none of which the engine depends on; without
them it is skipped, and says so.
"""

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
    pytest.skip("TwHIN server check needs torch and transformers (tools/twhin_server.py)", allow_module_level=True)


def test_the_server_returns_upstreams_pooler_output_truncated_at_512():
    import torch
    from transformers import AutoModel, AutoTokenizer

    spec = importlib.util.spec_from_file_location("twhin_server", Path(__file__).resolve().parents[3] / "tools" / "twhin_server.py")
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    texts = ["protein water after training", "word " * 2000]
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/v1/embeddings",
            data=json.dumps({"model": "twhin-bert-base", "input": texts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        served = [item["embedding"] for item in json.loads(urlopen(request).read())["data"]]
    finally:
        server.shutdown()
    tokenizer = AutoTokenizer.from_pretrained("Twitter/twhin-bert-base", model_max_length=512)
    model = AutoModel.from_pretrained("Twitter/twhin-bert-base").eval()
    with torch.no_grad():
        inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
        assert inputs["input_ids"].shape[1] == 512
        expected = model(**inputs).pooler_output
    assert torch.allclose(torch.tensor(served), expected, atol=1e-5)
