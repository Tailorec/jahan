"""The wire format: one OpenAI-compatible body, serialized once, sent as exactly those bytes.

The prompt hash a call records is the hash of the bytes on the wire — never of a re-serialization
after the fact. Which model answers, how much attention the endpoint pays and what it charges come
back from the response; this module only states what goes out."""

import hashlib
import json

CHAT_PATH = "/chat/completions"
EMBEDDINGS_PATH = "/embeddings"

# A gateway reports a call's cost either in its usage object or in a response header. The engine reads
# every name it knows and records the first; the study is never made to guess which one its gateway uses.
GATEWAY_COST_HEADERS = ("x-litellm-response-cost", "x-openai-cost", "x-gateway-cost")

CHARACTERS_PER_TOKEN = 4


def chat_body(request, pin, *, seed: int | None = None) -> dict:
    """The request as the endpoint sees it: the pin's name, the rendered messages, the sampling budget,
    and — only where the pin declares the capability — a seed and a strict response schema."""
    body: dict = {
        "model": pin.model_id,
        "messages": [dict(message) for message in request.messages],
        "temperature": request.temp,
        "max_tokens": request.max_tokens,
    }
    if seed is not None:
        body["seed"] = seed
    if request.json_schema is not None and pin.structured_output:
        schema = json.loads(request.json_schema)
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": request.template_id, "strict": True, "schema": schema},
        }
    return body


def embeddings_body(texts, pin) -> dict:
    return {"model": pin.model_id, "input": list(texts)}


def body_bytes(body: dict) -> bytes:
    """The one serialization a request ever gets: sorted keys, no surplus space, utf-8."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def prompt_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def estimate_tokens(text: str) -> int:
    """A pre-send token count from text length: roughly four characters a token, never zero."""
    return max(1, len(text) // CHARACTERS_PER_TOKEN)


def messages_text(messages) -> str:
    return " ".join(message["content"] for message in messages)


def gateway_cost(payload: dict, headers) -> float | None:
    """What the gateway says the call cost, from its usage object or its headers, or nothing at all."""
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    stated = usage.get("cost")
    if isinstance(stated, (int, float)) and not isinstance(stated, bool) and stated >= 0:
        return float(stated)
    for name in GATEWAY_COST_HEADERS:
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value >= 0:
            return value
    return None


def price_table_cost(price, input_tokens: int, output_tokens: int) -> float:
    """What a declared price computes for a call: never an invention, always the study's own arithmetic."""
    return (input_tokens * price.input_per_million + output_tokens * price.output_per_million) / 1_000_000.0
