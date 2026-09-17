"""One entry per run: everything a replay needs, and what the run knows about its spend.

The registry pins the configuration, brief, ontology, population and graph hashes, the seeds,
the pins, the engine version, the recorded cost, the discarded ticks and the status. A view
asks the registry which backend answers; a replay is configured from the entry alone.
"""

import json
import sqlite3
from pathlib import Path

from simcore.schemas import RunConfig, RunRegistryEntry

from .errors import DuplicateEntryError, UnknownRunError


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS entries ("
        " run_id TEXT PRIMARY KEY,"
        " entry_json TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " engine_version TEXT NOT NULL,"
        " recorded_cost REAL NOT NULL,"
        " discarded_ticks INTEGER NOT NULL,"
        " config_hash TEXT NOT NULL,"
        " contract_version TEXT NOT NULL)"
    )
    connection.commit()
    return connection


class SqliteRunRegistry:
    """The run registry, backed by one SQLite file. Satisfies the `RunRegistry` port."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: RunRegistryEntry) -> None:
        """Pin this run's entry. A second entry for the same run is refused, never replaced."""
        if not isinstance(entry, RunRegistryEntry):
            raise TypeError(f"the registry records entries, not mappings; build the model first ({type(entry).__name__})")
        with _connect(self._path) as connection:
            exists = connection.execute("SELECT 1 FROM entries WHERE run_id = ?", (entry.config.run_id,)).fetchone()
            if exists is not None:
                raise DuplicateEntryError(f"an entry for run {entry.config.run_id} already exists")
            connection.execute(
                "INSERT INTO entries (run_id, entry_json, status, engine_version, recorded_cost,"
                " discarded_ticks, config_hash, contract_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.config.run_id,
                    entry.model_dump_json(),
                    entry.status.value,
                    entry.engine_version,
                    entry.recorded_cost,
                    entry.discarded_ticks,
                    entry.config_hash,
                    entry.contract_version,
                ),
            )
            connection.commit()

    def entry(self, run_id: str) -> RunRegistryEntry | None:
        """This run's entry, strictly validated, or nothing when the run is unknown."""
        with _connect(self._path) as connection:
            row = connection.execute("SELECT entry_json FROM entries WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRegistryEntry.model_validate(json.loads(row[0]))

    def update(self, entry: RunRegistryEntry) -> None:
        """Move what a run learns about itself: status, recorded cost, discarded ticks.

        `record` stays refuse-on-duplicate so nothing silently replaces a run, and this refuses
        an update that would rewrite what a replay rests on — the configuration, the engine
        version or the contract. A run's own progress moves; its identity does not.
        """
        if not isinstance(entry, RunRegistryEntry):
            raise TypeError(f"the registry records entries, not mappings; build the model first ({type(entry).__name__})")
        held = self.entry(entry.config.run_id)
        if held is None:
            raise UnknownRunError(f"no entry for run {entry.config.run_id}")
        pinned = (
            ("configuration", held.config_hash, entry.config_hash),
            ("engine version", held.engine_version, entry.engine_version),
            ("contract version", held.contract_version, entry.contract_version),
        )
        moved = [f"{name} ({was} to {now})" for name, was, now in pinned if was != now]
        if moved:
            raise ValueError(
                f"an update moves a run's progress, never what a replay pins: {', '.join(moved)}"
            )
        with _connect(self._path) as connection:
            cursor = connection.execute(
                "UPDATE entries SET entry_json = ?, status = ?, engine_version = ?, recorded_cost = ?,"
                " discarded_ticks = ?, config_hash = ?, contract_version = ? WHERE run_id = ?",
                (
                    entry.model_dump_json(),
                    entry.status.value,
                    entry.engine_version,
                    entry.recorded_cost,
                    entry.discarded_ticks,
                    entry.config_hash,
                    entry.contract_version,
                    entry.config.run_id,
                ),
            )
            if cursor.rowcount == 0:
                raise UnknownRunError(f"no entry for run {entry.config.run_id}")
            connection.commit()


def replay_config(entry: RunRegistryEntry) -> RunConfig:
    """The run configuration a replay needs, from the registry entry alone.

    The entry carries the configuration whole, so replay is a round-trip: the config taken
    back out validates strictly and hashes to the entry's own config hash.
    """
    config = RunConfig.model_validate(entry.config.model_dump(mode="json"))
    assert config.model_dump_json() == entry.config.model_dump_json(), "a replay is configured from the entry alone"
    return config
