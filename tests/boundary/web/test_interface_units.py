"""The interface's own plain functions, run by node: `npm test` in `frontend/`.

What is testable without a browser is kept in `frontend/lib/` as functions over plain data — how a
refusal is worded, how the form's brief is written out as the YAML the engine reads — and their
tests run under node's built-in runner with type stripping, so there is nothing to install for them.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules" / "js-yaml").is_dir(),
    reason="node or the interface's dependencies are missing: `npm install` in frontend/",
)


def test_the_interface_units_pass():
    done = subprocess.run(
        ["node", "--test", *sorted(str(path) for path in (FRONTEND / "test").glob("*.test.mts"))],
        capture_output=True, text=True, cwd=FRONTEND, timeout=120,
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
    assert "# fail 0" in done.stdout
