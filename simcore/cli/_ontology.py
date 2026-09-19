"""`ontology check`: an ontology draft against the corpus it claims to describe.

A draft may be authored anywhere, but it cannot become a version until the
corpus backs it: an attribute the corpus does not carry is refused, naming
what resembles it. A refusal exits 2 with the explanation — a crash exits 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simcore.brief import validate_against_codebook
from simcore.ports.decoder import Codebook
from simcore.schemas import CategoryOntology
from simcore.schemas.errors import GateFailure


def cmd_ontology_check(argv: list[str] | None = None) -> int:
    """Check one ontology file against the corpus codebook. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="ontology check", description="Validate an ontology draft against the corpus.")
    parser.add_argument("--ontology", type=Path, required=True, help="the draft ontology JSON to check")
    parser.add_argument("--corpus", type=Path, default=None, help="corpus cache dir holding persona_codes.schema.json")
    args = parser.parse_args(argv)

    try:
        draft = json.loads(args.ontology.read_text(encoding="utf-8"))
    except OSError as error:
        raise GateFailure(f"cannot read {args.ontology}: {error}")
    try:
        ontology = CategoryOntology.model_validate(draft)
    except ValueError as error:
        raise GateFailure(f"{args.ontology} is not an ontology: {error}")
    schema = (args.corpus / "persona_codes.schema.json") if args.corpus is not None else _default_schema()
    if not schema.is_file():
        raise GateFailure(
            f"no corpus is cached at {schema.parent}: a draft may be authored without the corpus "
            "present, but it cannot be pinned until it validates against one"
        )
    try:
        validate_against_codebook(ontology, Codebook.from_json(schema))
    except ValueError as error:
        raise GateFailure(str(error))
    print(f"valid: {ontology.category}@{ontology.version}")
    return 0


def _default_schema() -> Path:
    from simcore.ports.hf import default_cache_dir

    return default_cache_dir() / "persona_codes.schema.json"
