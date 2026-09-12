"""The production evidence port. The suite refuses sockets, so what is tested here is everything
the adapter decides before it opens anything, and how it reads what it is given."""

import pytest

from simcore.ports import EvidencePort
from simcore.ports.http import MAX_EVIDENCE_BYTES, HttpEvidence


class _Response:
    """What urlopen yields: a context manager whose read(n) returns at most n bytes."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, size: int | None = None) -> bytes:
        return self._body if size is None else self._body[:size]


def serving(body: bytes, monkeypatch):
    monkeypatch.setattr("simcore.ports.http.urlopen", lambda url, timeout=None: _Response(body))


def test_the_adapter_satisfies_the_port():
    assert isinstance(HttpEvidence(), EvidencePort)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/hostname", "ftp://example.com/report.pdf", "data:text/plain,hello", "/etc/hostname"],
    ids=["a-local-file", "ftp", "inline-data", "a-bare-path"],
)
def test_only_http_urls_are_fetched(url):
    with pytest.raises(ValueError, match="http and https only"):
        HttpEvidence().fetch(url)


def test_a_refused_scheme_is_refused_before_anything_is_opened(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("the adapter opened a url it should have refused")

    monkeypatch.setattr("simcore.ports.http.urlopen", explode)
    with pytest.raises(ValueError, match="http and https only"):
        HttpEvidence().fetch("file:///etc/hostname")


def test_a_document_within_the_cap_is_returned_as_received(monkeypatch):
    serving(b"\x00 the bytes as served \xff", monkeypatch)
    assert HttpEvidence().fetch("https://example.com/panel") == b"\x00 the bytes as served \xff"


def test_a_response_past_the_cap_is_refused_rather_than_truncated(monkeypatch):
    serving(b"x" * 101, monkeypatch)
    with pytest.raises(ValueError, match="serves more than the 100 bytes"):
        HttpEvidence(max_bytes=100).fetch("https://example.com/enormous")


def test_a_response_exactly_at_the_cap_is_accepted(monkeypatch):
    serving(b"x" * 100, monkeypatch)
    assert len(HttpEvidence(max_bytes=100).fetch("https://example.com/exact")) == 100


def test_the_default_cap_is_documented_and_generous_for_a_document():
    assert MAX_EVIDENCE_BYTES == 32 * 1024 * 1024
