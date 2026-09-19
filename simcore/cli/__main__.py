"""Entrypoints: `python -m simcore.cli <command>`.

`concepts run`, `sweep run`, `coreset-gate`, `ssr-replica` — each prints the `run_id`
that names what it produced. Exit codes come from the exception class, mapped in
`_errors`.
"""

from __future__ import annotations

import sys

from ._concepts import cmd_concepts_run
from ._errors import report_error

USAGE = """usage: python -m simcore.cli <command>

  concepts run brief.yaml [--fake]   the whole study: report.md, report.json, run id
  sweep run --grid grid.yaml         a grid of scenarios and seeds under one budget
  coreset-gate --brief b.yaml        gate report and population manifest, no study
  ontology check --ontology o.json   an ontology draft against the corpus codebook
  brief check --brief b.yaml         a brief against the engine contracts, with its ledger
  ssr-replica --anchors <set>        the anchor check and its distribution diagnostics
"""


def main(argv: list[str] | None = None) -> int:
    """Dispatch one command. Returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] in ("-h", "--help"):
            print(USAGE)
            return 0
        command, rest = argv[0], argv[1:]
        if command == "concepts":
            if not rest or rest[0] != "run":
                print(USAGE)
                return 1
            return cmd_concepts_run(rest[1:])
        if command == "sweep":
            if not rest or rest[0] != "run":
                print(USAGE)
                return 1
            from ._sweep import cmd_sweep_run

            return cmd_sweep_run(rest[1:])
        if command == "coreset-gate":
            from ._coreset_gate import cmd_coreset_gate

            return cmd_coreset_gate(rest)
        if command == "ontology":
            if not rest or rest[0] != "check":
                print(USAGE)
                return 1
            from ._ontology import cmd_ontology_check

            return cmd_ontology_check(rest[1:])
        if command == "brief":
            if not rest or rest[0] != "check":
                print(USAGE)
                return 1
            from ._brief import cmd_brief_check

            return cmd_brief_check(rest[1:])
        if command == "ssr-replica":
            from ._ssr_replica import cmd_ssr_replica

            return cmd_ssr_replica(rest)
        print(USAGE)
        return 1
    except SystemExit as exit_request:
        # argparse ends a malformed command line with `SystemExit(2)`, and 2 is the code this
        # CLI documents for a failed gate. A usage error is not a study's verdict: it is
        # unmapped, so it exits 1, with argparse's own message already printed.
        code = exit_request.code
        if code in (0, None):
            return 0
        return 1
    except Exception as error:  # noqa: BLE001 — the mapping decides the code, nothing escapes
        return report_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
