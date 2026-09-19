"""`brief check`: a brief against the engine's own contracts, before a run can start.

Loads the brief the way a study will — unknown keys, unvalidated claims and an
ontology version that resolves nowhere are refused — and prints the assumption
ledger the brief assembles: what it states, what its claims assume, and what it
leaves unstated. A refusal exits 2 with the explanation — a crash exits 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simcore.brief import assumptions_of, load_brief


def cmd_brief_check(argv: list[str] | None = None) -> int:
    """Validate one brief file and print its ledger. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="brief check", description="Validate a brief and print its assumption ledger.")
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--ontologies", type=Path, default=Path("ontologies"))
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    pack = load_brief(args.brief, args.ontologies)
    ledger = assumptions_of(pack)
    if args.format == "json":
        print(json.dumps({
            "valid": True,
            "product": pack.brief.product.name,
            "category": pack.brief.product.category,
            "ontology_version": pack.brief.ontology_version,
            "claims": [claim.id for claim in pack.brief.claims],
            "audiences": [audience.name for audience in pack.brief.audiences],
            "assumption_ledger": [
                {"text": item.text, "source": item.source.value} for item in ledger
            ],
        }, indent=2, sort_keys=True))
    else:
        print(f"valid: {pack.brief.product.name} on {pack.brief.product.category}@{pack.brief.ontology_version}")
        for item in ledger:
            print(f"- [{item.source.value}] {item.text}")
    return 0
