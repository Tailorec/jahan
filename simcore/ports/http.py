"""The production `EvidencePort`: a standard-library HTTP GET that CI never exercises.

Network access is refused for every test by the suite's isolation, so this adapter is dead code
in continuous integration by construction. It is imported by nothing in the package; the command
line is what will select it once it exists."""

from urllib.parse import urlsplit
from urllib.request import urlopen

# A port bounds what the engine can reach. urlopen serves whatever opener matches a scheme —
# file:// and ftp:// among them — so a cited url could otherwise read the local filesystem.
FETCHABLE_SCHEMES = frozenset({"http", "https"})

# Evidence is a document a person cited, not a dataset. A url that serves more than this is a
# mistake or a hostile answer, and either way it must fail rather than exhaust memory.
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024


class HttpEvidence:
    """Fetch bytes over HTTP through the standard library, following redirects.

    The bytes are returned exactly as received; the caller hashes them and records the URL the
    author cited, which is the provenance rather than the address actually resolved."""

    def __init__(self, *, timeout: float = 30.0, max_bytes: int = MAX_EVIDENCE_BYTES) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def fetch(self, url: str) -> bytes:
        scheme = urlsplit(url).scheme.lower()
        if scheme not in FETCHABLE_SCHEMES:
            named = repr(scheme) if scheme else "no scheme"
            raise ValueError(f"evidence is fetched over http and https only, but {url!r} names {named}")
        with urlopen(url, timeout=self._timeout) as response:  # noqa: S310 — the scheme is checked above
            # One byte past the cap, so that hitting it is a refusal rather than a silent truncation.
            body = response.read(self._max_bytes + 1)
        if len(body) > self._max_bytes:
            raise ValueError(f"{url!r} serves more than the {self._max_bytes} bytes evidence is capped at")
        return body
