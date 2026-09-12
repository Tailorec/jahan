"""A `CoresetSource` serving a handful of committed rows, readable beside the tests that use them.

Where the synthetic source hides input behind a shape, this one keeps input and expectation a person
can read side by side: a small JSON tree of named rows and an explicit value order per attribute."""

import json
from pathlib import Path

from simcore.schemas import FrozenDict

from .coreset import DecodedRow, _DecodedRowSource


class FixtureCoresetSource(_DecodedRowSource):
    """Rows committed in a JSON file: `vocabulary` gives each attribute's order, `rows` its values."""

    @classmethod
    def from_json(cls, path: Path) -> "FixtureCoresetSource":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        vocabulary = {attribute: tuple(values) for attribute, values in data["vocabulary"].items()}
        rows = [
            DecodedRow(row_id=entry["row_id"], source=entry["source"], values=FrozenDict(entry["values"]))
            for entry in data["rows"]
        ]
        return cls(rows, vocabulary)
