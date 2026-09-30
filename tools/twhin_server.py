"""TwHIN-BERT behind an OpenAI-compatible `/v1/embeddings`, for the feed's ranking model.

Vectors are computed exactly as OASIS computes them (`process_recsys_posts.process_batch`): the
tokenizer truncates at 512 tokens, pads the batch, and the vector is the model's `pooler_output`.
It runs outside the engine, behind the gateway, so PyTorch never enters `simcore` (ADR 0021):

    uv run --no-project --with torch --with "transformers<5" \
      --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
      python tools/twhin_server.py --port 8100

The CPU wheel keeps the download near 200 MB; the model weights add about 1.1 GB on first start.

Two things the checkpoint forces. It uses `relative_key` position embeddings, which transformers 5
no longer builds for BERT — it silently drops them and runs a different model — so transformers
stays below 5, as OASIS's own pins imply. And it carries no pooler weights: `pooler_output` passes
through a freshly initialised layer, which upstream re-randomises on every start. Here that layer
is initialised from a fixed seed, so the same text embeds the same way on every start and a
resumed feed ranks as the run it continues did.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from transformers import AutoModel, AutoTokenizer

MODEL = "Twitter/twhin-bert-base"
POOLER_SEED = 0
tokenizer = AutoTokenizer.from_pretrained(MODEL, model_max_length=512)
torch.manual_seed(POOLER_SEED)  # the checkpoint has no pooler: initialise it the same way every start
model = AutoModel.from_pretrained(MODEL).eval()


@torch.no_grad()
def embed(texts: list[str]) -> tuple[list[list[float]], int]:
    """OASIS's `process_batch`: padded, truncated at 512, `pooler_output`."""
    inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
    return model(**inputs).pooler_output.tolist(), int(inputs["attention_mask"].sum())


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path.rstrip("/") not in ("/v1/embeddings", "/embeddings"):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texts = [body["input"]] if isinstance(body["input"], str) else list(body["input"])
        vectors, tokens = embed(texts)
        reply = json.dumps({
            "object": "list",
            "model": body.get("model", MODEL),
            "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    print(f"TwHIN-BERT serving /v1/embeddings on http://{args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
