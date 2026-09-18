"""`coreset-gate`: gate report and population manifest, no study.

A doomed study costs nothing: the draw is gated before any model is called beyond
completion, and a failing draw exits 2 with the gate report that explains it — a crash
exits 1. No world starts here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from simcore.brief import load_brief

from ._concepts import add_backend_arguments
from ._ids import mint_run_id
from ._study import assemble_backend, gate_and_build


def cmd_coreset_gate(argv: list[str] | None = None) -> int:
    """Draw a population and report its gates. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="coreset-gate", description="Gate a population without running a study.")
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--n", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=4021, help="the population draw seed")
    add_backend_arguments(parser)
    args = parser.parse_args(argv)

    pack = load_brief(args.brief, args.ontologies)
    args.population_seed = args.seed
    run_id = args.run_id or mint_run_id()
    run_dir = args.out / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    chat, _embed, coreset, _pins, _pin = assemble_backend(pack, args)
    gate_and_build(pack, n=args.n, population_seed=args.seed, chat=chat, coreset=coreset, run_dir=run_dir)
    print(f"run_id: {run_id}")
    print(f"artefacts: {run_dir}")
    return 0
