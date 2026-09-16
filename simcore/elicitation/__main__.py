"""Run the mapping validation: `python -m simcore.elicitation --synthetic 500 --seed 7 --out report.json`."""

from __future__ import annotations

import argparse
import json

from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import ModelPins

from ._anchors import anchor_hash, load_anchor_version
from ._validate import SATISFACTION_CONSTRUCT, reviews_from_jsonl, synthetic_reviews, validate_mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SSR's text-to-rating mapping on human reviews.")
    parser.add_argument("--reviews", help="JSONL file with {text, stars} objects, downloaded at run time")
    parser.add_argument("--synthetic", type=int, default=500, help="synthetic sample size when --reviews is absent (CI)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--anchors-dir", default="anchors")
    parser.add_argument("--anchor-set-id", default="satisfaction-v1")
    parser.add_argument("--anchor-version", default="v1")
    parser.add_argument("--epsilon", type=float, default=0.0)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--embed-model", default="amazon.titan-embed-text-v2:0")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.reviews:
        sample = reviews_from_jsonl(args.reviews, seed=args.seed)
    else:
        sample = synthetic_reviews(args.synthetic, args.seed)
    pins = ModelPins.model_validate(
        {
            "tier_a": "tier-a/model",
            "tier_b": "tier-b/model",
            "embed": {"model_id": args.embed_model, "serves": [args.embed_model]},
        }
    )
    client = InferenceClient(pins, ExecutionSettings())
    try:
        report = validate_mapping(
            sample,
            client,
            anchors_dir=args.anchors_dir,
            anchor_set_id=args.anchor_set_id,
            anchor_version=args.anchor_version,
            anchor_hash_pinned=anchor_hash(load_anchor_version(f"{args.anchors_dir}/{SATISFACTION_CONSTRUCT}/{args.anchor_version}.json")),
            epsilon=args.epsilon,
            temperature=args.temperature,
            seed=args.seed,
        )
    finally:
        try:
            import asyncio

            asyncio.get_event_loop().run_until_complete(client.aclose())
        except Exception:
            pass
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
