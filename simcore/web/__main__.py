"""Serve the engine over HTTP: `python -m simcore.web --runs runs --port 8000`."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simcore.web", description="Serve the engine over HTTP.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--ontologies", type=Path, default=Path("ontologies"))
    parser.add_argument("--briefs", type=Path, default=Path("examples"))
    parser.add_argument("--anchors", type=Path, default=Path("anchors"))
    parser.add_argument("--corpus", type=Path, default=None, help="a cached corpus directory, when not the default cache")
    parser.add_argument(
        "--engine-root", type=Path, default=None,
        help="the checkout studies run from; defaults to the current directory",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    import uvicorn

    from .app import create_app

    args.runs.mkdir(parents=True, exist_ok=True)
    app = create_app(
        runs_dir=args.runs.resolve(),
        ontology_dir=args.ontologies.resolve(),
        briefs_dir=args.briefs.resolve(),
        anchors_dir=args.anchors.resolve(),
        corpus_dir=args.corpus.resolve() if args.corpus is not None else None,
        engine_root=args.engine_root.resolve() if args.engine_root is not None else Path.cwd(),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
