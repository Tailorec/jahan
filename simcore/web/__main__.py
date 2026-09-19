"""Serve the engine over HTTP: `python -m simcore.web --runs runs --port 8000`."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simcore.web", description="Serve the engine over HTTP.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--ontologies", type=Path, default=Path("ontologies"))
    parser.add_argument("--briefs", type=Path, default=Path("examples"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    import uvicorn

    from .app import create_app

    app = create_app(runs_dir=args.runs, ontology_dir=args.ontologies, briefs_dir=args.briefs)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
