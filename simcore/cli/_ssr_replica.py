"""`ssr-replica`: the anchor check and its distribution diagnostics.

A supplied scale is judged before a study depends on it: the ladder must score in
increasing order, rank stability must clear its floor, and varied responses must not
collapse. A version that fails its check is reported as failing and is not pinned —
pinning refuses it, so exit 2, not 0. The check record is written beside the version
it judged, and the diagnostics name the population they were judged for.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simcore.elicitation import assert_pinnable, check_anchors
from simcore.ports.fake import FakeEmbed
from simcore.schemas import GateFailure, PopulationManifest

from ._fake import FAKE_EMBED
from ._ids import mint_run_id


def cmd_ssr_replica(argv: list[str] | None = None) -> int:
    """Run the anchor check on a named anchor set. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="ssr-replica", description="Judge an anchor scale before a study depends on it.")
    parser.add_argument("--anchors", required=True, help="the anchor set id to judge")
    parser.add_argument("--construct", required=True, help="the construct the set scores")
    parser.add_argument("--anchor-version", default="v1")
    parser.add_argument("--population", type=Path, required=True, help="the population manifest the judgement is made for")
    parser.add_argument("--fake", action="store_true", help="stub embeddings: no key, no network")
    parser.add_argument("--embed-model", default=None, help="the embedding model to check against (real runs)")
    parser.add_argument("--model", default=None, help="chat tiers ride along unused; pins travel together (real runs)")
    parser.add_argument("--anchors-dir", type=Path, default=Path("anchors"))
    parser.add_argument("--out", type=Path, default=Path("runs"))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    try:
        manifest = PopulationManifest.model_validate_json(args.population.read_text())
    except (OSError, ValueError) as error:
        raise GateFailure(f"population manifest {args.population} cannot be read: {error}") from error

    if args.fake:
        embed = FakeEmbed(model_id=FAKE_EMBED)
    else:
        if not args.embed_model or not args.model:
            raise GateFailure("a real check pins its models: pass --model and --embed-model (or run --fake)")
        from simcore.inference import ExecutionSettings, InferenceClient
        from simcore.schemas import ModelPins

        pins = {
            "tier_a": {"model_id": args.model, "serves": [args.model]},
            "tier_b": {"model_id": args.model, "serves": [args.model]},
            "embed": {"model_id": args.embed_model, "serves": [args.embed_model]},
        }
        embed = InferenceClient(ModelPins.model_validate(pins), ExecutionSettings.from_environment())

    result = check_anchors(args.anchors, args.construct, args.anchor_version, embed, args.anchors_dir)
    try:
        assert_pinnable(args.anchors, args.construct, args.anchor_version, args.anchors_dir,
                        embed_model_id=getattr(embed, "model_id", None))
        pinnable = True
    except ValueError:
        pinnable = False

    run_id = args.run_id or mint_run_id()
    run_dir = args.out / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = {
        "run_id": run_id,
        "anchor_set_id": result.anchor_set_id,
        "construct": result.construct,
        "version": result.version,
        "embed_model_id": result.embed_model_id,
        "passed": result.passed,
        "pinnable": pinnable,
        "expected_ratings": list(result.expected_ratings),
        "spearman_min": result.spearman_min,
        "collapse_distance": result.collapse_distance,
        "detail": result.detail,
        "population_hash": manifest.population_hash,
        "personas": len(manifest.persona_ids),
    }
    (run_dir / "anchors-check.json").write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n")
    print(f"run_id: {run_id}")
    print(f"artefacts: {run_dir}")
    print(f"verdict: {'passed' if result.passed else 'FAILED'} — {result.detail}")
    if not result.passed:
        raise GateFailure(
            f"anchor version {args.construct}/{args.anchor_version} failed its check ({result.detail}): it is not pinned"
        )
    return 0
