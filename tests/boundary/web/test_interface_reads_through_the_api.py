"""Phase 2, asserted over the interface's source: every engine number arrives through the API.

`frontend/` holds no engine logic. It reads no run directory, starts no process and finds no
engine checkout; its own routes are proxies, and the only thing it is configured with is where the
engine API is.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
SOURCES = [
    path for root in ("app", "components", "lib")
    for path in (FRONTEND / root).rglob("*")
    if path.suffix in (".ts", ".tsx")
]


def test_no_page_or_route_reads_the_filesystem_or_finds_the_checkout():
    forbidden = ("node:fs", "node:os", "node:path", "readFile", "engineRoot", "SIM_ENGINE_ROOT", ".venv", "ui-trace")
    assert SOURCES
    for path in SOURCES:
        text = path.read_text()
        for marker in forbidden:
            assert marker not in text, f"{path.relative_to(FRONTEND)} reads the engine's files: {marker!r}"


def test_the_only_environment_it_reads_is_where_the_engine_is():
    reads = {
        (path.relative_to(FRONTEND).as_posix(), line.strip())
        for path in SOURCES
        for line in path.read_text().splitlines()
        if "process.env" in line
    }
    assert {name for name, _ in reads} == {"lib/server.ts"}
    assert all("SIMCORE_WEB_URL" in line for _, line in reads)


def test_a_refusal_is_never_reduced_to_its_status_code():
    """`throw new Error(`${p}: ${res.status}`)` discarded the sentence the engine wrote."""
    for name in ("api.ts", "server.ts"):
        text = (FRONTEND / "lib" / name).read_text()
        assert "refusalText" in text, f"{name} does not carry the engine's reason"
    for path in (FRONTEND / "app" / "api").rglob("route.ts"):
        text = path.read_text()
        assert "status: 502" not in text, f"{path.relative_to(FRONTEND)} turns a refusal into a bare 502"


def test_the_shell_states_nothing_the_engine_did_not_say():
    """The shell wrapped every page in invented studies, a version the engine never had, a monthly
    budget and a plan — the opposite of a single-operator application with no quota and no account."""
    text = (FRONTEND / "components" / "shell.tsx").read_text()
    for invented in ("Team plan", "1,500", "avatar", "Oral-care", "Refill pouch", "v0.4.1", "MatrAIx-1M", "seeds pinned"):
        assert invented not in text, f"the shell shows a placeholder: {invented!r}"
    assert "/api/overview" in text and "/api/status" in text


def test_no_page_shows_a_number_or_name_it_made_up():
    for path in SOURCES:
        text = path.read_text()
        for invented in ("Team plan", "Monthly simulation budget", "Oral-care electric brush"):
            assert invented not in text, f"{path.relative_to(FRONTEND)} carries placeholder content: {invented!r}"
