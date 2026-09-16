"""The holdout command.

    python -m simcore.holdout --hidden att_ai --pool 600 --seed 4021

Without ``--endpoint`` the production path runs on the deterministic fake, which is how CI proves the
metrics; with it, the endpoint and key are read from the environment (the same variables the engine
uses) and the model is pinned on the command line. The report records the pins, served models, seeds,
completion temperature and row counts behind every number, and is written as JSON."""

import argparse
import json
import sys
from pathlib import Path

from simcore.brief import load_brief
from simcore.ports.fake import FakeChat
from simcore.ports.fixture import FixtureCoresetSource

from ._evaluate import evaluate

DEFAULT_PACK = Path("examples/code_review_ai.yaml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simcore.holdout", description=__doc__)
    parser.add_argument("--hidden", default="att_ai", help="comma-separated measured attitudes to hide")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK, help="brief (with its ontology version) to evaluate against")
    parser.add_argument("--ontologies", type=Path, default=Path("ontologies"))
    parser.add_argument("--pool", type=int, default=600, help="rows carrying every hidden attitude to consider")
    parser.add_argument("--holdout-share", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=4021, help="the holdout split seed")
    parser.add_argument("--population-seed", type=int, default=None, help="the draw seed for the engine's sampling")
    parser.add_argument("--temperature", type=float, default=1.0, help="the study's completion temperature")
    parser.add_argument("--endpoint", action="store_true", help="run against the configured OpenAI-compatible endpoint")
    parser.add_argument("--model", default=None, help="the tier_a model name to pin (with --endpoint)")
    parser.add_argument("--cache", type=Path, default=None, help="cached corpus shards (default: $CONSUMERSIM_CORESET_CACHE)")
    parser.add_argument("--coreset-fixture", type=Path, default=None, help="a packed fixture instead of cached shards")
    parser.add_argument("--source", default="stackoverflow", help="the source the measured attitudes are held out from")
    parser.add_argument("--out", type=Path, default=None, help="where to write the JSON report (default: stdout)")
    args = parser.parse_args(argv)

    pack = load_brief(args.pack, args.ontologies)
    hidden = tuple(name.strip() for name in args.hidden.split(",") if name.strip())
    coreset, rows = _rows(pack, hidden, args)
    if args.endpoint:
        inference, inference_label, pins = _endpoint(args)
    else:
        inference, inference_label, pins = FakeChat(), "FakeChat", {"tier_a": "fake/chat"}
    report = evaluate(
        pack,
        coreset,
        rows,
        hidden=hidden,
        inference=inference,
        holdout_seed=args.seed,
        population_seed=args.population_seed,
        completion_temperature=args.temperature,
        holdout_share=args.holdout_share,
        inference_label=inference_label,
        pins=pins,
        # The models that actually answered are known only once the evaluation has run them through.
        served_models=getattr(inference, "served_models", {}),
    )
    text = report.to_json()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"holdout report written to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def _rows(pack, hidden, args):
    if args.coreset_fixture:
        source = FixtureCoresetSource.from_json(args.coreset_fixture)
        return source, list(source.rows(source.matching({}, present=[*pack.ontology.conditioning_set, *hidden], sources=[args.source])))
    from simcore.ports.hf import HfCoresetSource, MissingShard, default_cache_dir

    cache = args.cache or default_cache_dir()
    if not (cache / "manifest.json").is_file():
        raise MissingShard(f"no coreset cached at {cache}; fetch it with hf download, or pass --coreset-fixture")
    shards = _stackoverflow_shards(cache)
    if not shards:
        raise MissingShard(f"no cached shard carries {args.source!r}; fetch the release with the command in examples/README.md")
    source = HfCoresetSource(cache_dir=cache, shards=shards, sources=(args.source,))
    found = source.matching({}, present=[*pack.ontology.conditioning_set, *hidden], sources=[args.source])
    return source, list(source.rows(found[: args.pool]))


def _stackoverflow_shards(cache: Path) -> list[str]:
    manifest = json.loads((cache / "manifest.json").read_text())
    import pyarrow.parquet as pq

    found = []
    for entry in manifest["files"]:
        path = cache / entry["path"]
        if not path.is_file():
            continue
        if any(row == "stackoverflow" for row in pq.read_table(path, columns=["source"])["source"].to_pylist()):
            found.append(entry["path"])
    return found


def _endpoint(args):
    if not args.model:
        raise SystemExit("--endpoint needs --model NAME (the study's pinned tier_a model)")
    from simcore.inference import ExecutionSettings, InferenceClient
    from simcore.schemas import ModelPins

    pins = ModelPins.model_validate({"tier_a": args.model, "tier_b": args.model, "embed": "unused/embed-v1"})
    client = InferenceClient(pins, ExecutionSettings.from_environment())
    return client, "endpoint", {"tier_a": args.model}


if __name__ == "__main__":
    raise SystemExit(main())
