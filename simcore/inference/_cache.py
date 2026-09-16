"""The persistent cache that makes a re-run cheap without making replicates identical.

An entry is keyed by everything that decides an answer: the pinned model and the identifiers it accepts,
the template's id and hash, the exact request bytes, and — for any call above temperature zero — a
sample key of replicate seed, persona and tick (ADR 0025). A temperature-zero call answers the same for
every replicate and may be shared; a sampled answer belongs to one draw. A hit is recorded as the cache
route and bills nothing. Replay reads the trace, never this cache: nothing in the read path of a world
consults an entry that was written by a different execution."""

import hashlib
import json
from pathlib import Path

from simcore.schemas import ChatRequest, ModelPin


class SampleCache:
    """JSON entries under a directory in the user cache — outside every repository, disposable at any
    time: deleting it changes what a re-run pays, never what it records."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def key(
        self,
        request: ChatRequest,
        pin: ModelPin,
        request_bytes: bytes,
        *,
        template_hash: str | None,
    ) -> str:
        material: dict = {
            "model_id": pin.model_id,
            "serves": sorted(pin.serves),
            "structured_output": pin.structured_output,
            "template_id": request.template_id,
            "template_hash": template_hash,
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        }
        # A call above temperature zero is a draw of one replicate: its sample key joins the identity,
        # so two seeds can never be handed the same answer. A temperature-zero call has one true answer
        # and stays shareable (ADR 0025).
        if request.temp > 0.0 and request.sample is not None:
            sample = request.sample
            material["sample"] = {
                "world_seed": sample.world_seed,
                "persona_id": sample.persona_id,
                "tick": sample.tick,
                "seq": sample.seq,
            }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        try:
            entry = json.loads(self._path(key).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        return entry if isinstance(entry, dict) else None

    def put(self, key: str, entry: dict) -> None:
        path = self._path(key)
        temporary = path.with_suffix(".tmp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(entry, sort_keys=True))
        temporary.replace(path)  # atomic: a reader sees a whole entry or none
