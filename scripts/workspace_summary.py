"""Print the workspace summary: `analysis.workspace_summary` over registry entries.

One derived shape, read from entries rather than by walking partitions — the
CLI writes it, the interface displays it, neither computes it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    from simcore.analysis import workspace_summary
    from simcore.schemas import RunRegistryEntry
    from simcore.trace import TraceStore

    runs = Path("runs")
    entries = []
    for run_dir in sorted(runs.iterdir()) if runs.is_dir() else []:
        if not run_dir.is_dir():
            continue
        stored = None
        result = run_dir / "result.json"
        if result.is_file():
            stored = (json.loads(result.read_text()) or {}).get("registry")
        if stored is None and (run_dir / "trace" / "registry.db").is_file():
            entry = TraceStore(run_dir / "trace").registry.entry(run_dir.name)
            stored = json.loads(entry.model_dump_json()) if entry else None
        if not stored:
            continue
        try:
            entries.append(RunRegistryEntry.model_validate(stored))
        except Exception:
            continue
    summary = workspace_summary(entries)
    print(json.dumps(json.loads(summary.model_dump_json()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
