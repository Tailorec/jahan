"""`concepts run`: the whole study — `report.md`, `report.json`, and the run id."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._study import DEFAULT_VALIDATION, analyze_study, check_budget, prepare_study, run_study, write_report


def add_backend_arguments(parser: argparse.ArgumentParser) -> None:
    """Flags every study command shares: where the models and the corpus come from."""
    parser.add_argument("--fake", action="store_true", help="synthetic coreset and stub inference: no key, no download, no network")
    parser.add_argument("--ontologies", type=Path, default=Path("ontologies"))
    parser.add_argument("--anchors", type=Path, default=Path("anchors"))
    parser.add_argument("--out", type=Path, default=Path("runs"), help="parent directory for the run-named artefact directory")
    parser.add_argument("--run-id", default=None, help="name the run (default: mint one); reusing it resumes the run")
    parser.add_argument("--model", default=None, help="the chat model to pin (real studies)")
    parser.add_argument("--embed-model", default=None, help="the embedding model to pin (real studies)")
    parser.add_argument("--price-chat-in", type=float, default=None, help="chat input price per million tokens")
    parser.add_argument("--price-chat-out", type=float, default=None, help="chat output price per million tokens")
    parser.add_argument("--price-embed-in", type=float, default=None, help="embed input price per million tokens")
    parser.add_argument("--cache", type=Path, default=None, help="cached corpus shards (default: the user cache)")
    parser.add_argument("--validation", default=None, help="the report's recommended real-world validation")


def add_study_arguments(parser: argparse.ArgumentParser) -> None:
    """Flags describing the study itself: who is in it and how long it runs."""
    parser.add_argument("--n", type=int, default=40, help="personas in the population")
    parser.add_argument("--population-seed", type=int, default=4021)
    parser.add_argument("--horizon", type=int, default=4, help="ticks per world")
    parser.add_argument("--tick-unit", default="day")
    parser.add_argument("--budget", type=float, default=20.0, help="max spend in USD")
    parser.add_argument("--channel", default="survey_room")


def cmd_concepts_run(argv: list[str] | None = None) -> int:
    """Run one baseline study and write its report. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="concepts run", description="Run a baseline study and write its report.")
    parser.add_argument("brief", type=Path, help="the product brief to study")
    add_backend_arguments(parser)
    add_study_arguments(parser)
    parser.add_argument("--seeds", default="4021", help="comma-separated replicate seeds")
    args = parser.parse_args(argv)
    seeds = [int(seed) for seed in args.seeds.split(",") if seed.strip()]
    if not seeds:
        raise ValueError("at least one replicate seed is required")

    handles = prepare_study(
        brief_path=args.brief,
        ontologies_dir=args.ontologies,
        anchors_dir=args.anchors,
        out_dir=args.out,
        run_id=args.run_id,
        n=args.n,
        population_seed=args.population_seed,
        scenarios=None,
        seeds=seeds,
        budget=args.budget,
        args=args,
    )
    result = run_study(handles, channel=args.channel)
    (handles.run_dir / "result.json").write_text(result.model_dump_json(indent=2) + "\n")

    if any(outcome.status.value == "completed" for outcome in result.outcomes):
        analysis = analyze_study(handles, result)
        write_report(handles, analysis, validation=args.validation or DEFAULT_VALIDATION)

    print(f"run_id: {handles.run_id}")
    print(f"artefacts: {handles.run_dir}")
    check_budget(result)
    return 0
