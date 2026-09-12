"""The production `EvidencePort`: a standard-library HTTP GET that CI never exercises.

Network access is refused for every test by the suite's isolation, so this adapter is dead code
in continuous integration by construction. It is imported by nothing in the package; the command
line is what will select it once it exists."""

from urllib.request import urlopen


class HttpEvidence:
    """Fetch bytes over HTTP through the standard library, following redirects.

    The bytes are returned exactly as received; the caller hashes them and records the URL the
    author cited, which is the provenance rather than the address actually resolved."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def fetch(self, url: str) -> bytes:
        with urlopen(url, timeout=self._timeout) as response:
            return response.read()
