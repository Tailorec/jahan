"""The in-memory `EvidencePort`: every test runs against this, so no test touches the network."""

from collections.abc import Mapping


class InMemoryEvidence:
    """A port backed by a mapping of URL to bytes, recording every URL it was asked for.

    A URL mapped to an exception simulates a failure; a URL absent from both simulates a port
    that has nothing for it."""

    def __init__(
        self,
        responses: Mapping[str, bytes] | None = None,
        errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._errors = dict(errors or {})
        self.calls: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self._errors:
            raise self._errors[url]
        try:
            return self._responses[url]
        except KeyError:
            raise LookupError(f"the in-memory port has no response for {url!r}") from None
