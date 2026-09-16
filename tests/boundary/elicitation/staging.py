"""Anchor directories staged for tests, with a check record standing in for a passing check.

The repository's own anchor versions failed their check on Titan and cannot be scored, so tests that exercise
scoring stage a copy whose record says it passed for the test's embedding model. The record is a test fixture,
not evidence: nothing here writes into the repository's `anchors/`."""

import shutil
from pathlib import Path

from simcore.elicitation import anchor_hash, load_anchor_version
from simcore.elicitation._check import AnchorCheckResult, check_record_path

REPO_ANCHORS = Path(__file__).resolve().parents[3] / "anchors"
FAMILIES = (("purchase_intent", "purchase-intent-v1"), ("satisfaction", "satisfaction-v1"))


def stage_passing(tmp_path: Path, *, model_id: str = "fake-embed", version: str = "v1") -> Path:
    staged = tmp_path / "anchors"
    shutil.copytree(REPO_ANCHORS, staged)
    for construct, set_id in FAMILIES:
        parsed = load_anchor_version(staged / construct / f"{version}.json")
        record = AnchorCheckResult(
            anchor_set_id=set_id, construct=construct, version=version, anchor_hash=anchor_hash(parsed),
            embed_model_id=model_id, passed=True, expected_ratings=(1.0, 2.0, 3.0, 4.0, 5.0, 5.5, 6.0),
            spearman_min=1.0, collapse_distance=1.0, detail="test fixture standing in for a passing check",
        )
        check_record_path(staged, construct, version).write_text(record.model_dump_json(indent=2) + "\n")
    return staged


def pinned(staged: Path, construct: str = "purchase_intent", set_id: str = "purchase-intent-v1", version: str = "v1") -> dict[str, str]:
    return {set_id: anchor_hash(load_anchor_version(staged / construct / f"{version}.json"))}
