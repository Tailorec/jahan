"""Whether a pinned embedding model answers at the configured endpoint, before a study relies on it."""

import httpx

from ._settings import ExecutionSettings


def probe_embeddings(model: str, settings: ExecutionSettings | None = None) -> str | None:
    """None when `model` returns a vector for one short text at the endpoint, else why not.

    The feed's ranking model (TwHIN-BERT) is served locally beside the gateway; a feed study that
    launches without it fails on its first tick, so the interface asks first. The key stays here.
    """
    settings = settings or ExecutionSettings.from_environment()
    headers = {"content-type": "application/json"}
    if settings.api_key:
        headers["authorization"] = f"Bearer {settings.api_key}"
    try:
        response = httpx.post(
            f"{settings.base_url.rstrip('/')}/embeddings",
            json={"model": model, "input": ["probe"]},
            headers=headers,
            timeout=min(settings.timeout_s, 30.0),
        )
    except httpx.HTTPError as error:
        return f"the endpoint could not be reached: {error}"
    if response.status_code >= 400:
        return f"the endpoint refused {model} ({response.status_code}): {response.text[:300]}"
    try:
        data = response.json()["data"]
        assert data and data[0]["embedding"]
    except (ValueError, KeyError, IndexError, TypeError, AssertionError):
        return f"the endpoint answered for {model} without a vector"
    return None
