"""In-process command invocation against temporary directories; the suite reaches no network."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from simcore.cli.__main__ import main

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIEF = REPO_ROOT / "examples" / "protein_water.yaml"
ONTOLOGIES = REPO_ROOT / "ontologies"
ANCHORS = REPO_ROOT / "anchors"


def run_command(*argv: str) -> tuple[int, str]:
    """Invoke the CLI in-process, capturing stdout. Returns (exit code, output)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def fake_args(out: Path, run_id: str, **overrides) -> list[str]:
    """A small fake study: fast enough for the suite, large enough to pass the graph gates."""
    args = [
        "concepts", "run", str(BRIEF),
        "--fake",
        "--ontologies", str(ONTOLOGIES),
        "--anchors", str(ANCHORS),
        "--out", str(out),
        "--run-id", run_id,
        "--n", "24",
        "--horizon", "2",
    ]
    for flag, value in overrides.items():
        args.extend([f"--{flag.replace('_', '-')}", str(value)])
    return args


def run_id_from(output: str) -> str:
    """The run id a command printed."""
    for line in output.splitlines():
        if line.startswith("run_id: "):
            return line.removeprefix("run_id: ").strip()
    raise AssertionError(f"no run id printed in:\n{output}")
