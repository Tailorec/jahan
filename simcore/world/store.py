"""Platform state in SQLite, internal to the world module.

The store holds what platforms know: published stimuli (with reply parents)
and per-action engagement rows. Counts shown to personas aggregate only rows
from earlier ticks, which is what keeps within-tick independence structural
rather than disciplined. Provenance columns (`world_id`, `written_tick`) are
written at write time, never backfilled, and every row carries them.

Nothing here crosses the module boundary: deltas carry trace record types
only, and a world resumes by replaying turns, never by handing this state out.
"""

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stimuli (
    stimulus_id TEXT PRIMARY KEY,
    tick INTEGER NOT NULL,
    author TEXT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    claim_id TEXT,
    parent_id TEXT,
    world_id TEXT NOT NULL,
    written_tick INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS engagements (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    stimulus_id TEXT NOT NULL,
    action TEXT NOT NULL,
    persona_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    world_id TEXT NOT NULL,
    written_tick INTEGER NOT NULL
);
"""

_COUNT_ACTIONS = ("like", "repost", "quote", "upvote", "downvote")


class Store:
    """SQLite-backed platform facts for one world."""

    def __init__(self, path: str | None = None) -> None:
        self._db = sqlite3.connect(path or ":memory:")
        self._db.executescript(_SCHEMA)

    def record_stimulus(
        self,
        *,
        stimulus_id: str,
        tick: int,
        author: str | None,
        kind: str,
        text: str,
        claim_id: str | None,
        parent_id: str | None,
        world_id: str,
        written_tick: int,
    ) -> None:
        self._db.execute(
            "INSERT INTO stimuli VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stimulus_id, tick, author, kind, text, claim_id, parent_id, world_id, written_tick),
        )
        self._db.commit()

    def record_engagement(
        self, *, stimulus_id: str, action: str, persona_id: str, tick: int, world_id: str, written_tick: int
    ) -> None:
        self._db.execute(
            "INSERT INTO engagements (stimulus_id, action, persona_id, tick, world_id, written_tick)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (stimulus_id, action, persona_id, tick, world_id, written_tick),
        )
        self._db.commit()

    def stimuli_published_before(self, tick: int) -> list[dict]:
        """Every stimulus published strictly before `tick`, oldest first, id-stable."""
        rows = self._db.execute(
            "SELECT stimulus_id, tick, author, kind, text, claim_id, parent_id"
            " FROM stimuli WHERE tick < ? ORDER BY tick, stimulus_id",
            (tick,),
        ).fetchall()
        keys = ("stimulus_id", "tick", "author", "kind", "text", "claim_id", "parent_id")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def counts_visible_at(self, tick: int) -> dict[str, dict[str, int]]:
        """Engagement counts from earlier ticks only: {stimulus_id: {count_name: n}}.

        Reposts count quotes too — both reshare. Replies count published
        peer replies, which are stimuli rather than engagement rows.
        """
        counts: dict[str, dict[str, int]] = {}
        for stimulus_id, action in self._db.execute(
            "SELECT stimulus_id, action FROM engagements WHERE tick < ?", (tick,)
        ).fetchall():
            entry = counts.setdefault(stimulus_id, {"likes": 0, "reposts": 0, "upvotes": 0, "downvotes": 0})
            if action == "like":
                entry["likes"] += 1
            elif action in ("repost", "quote"):
                entry["reposts"] += 1
            elif action == "upvote":
                entry["upvotes"] += 1
            elif action == "downvote":
                entry["downvotes"] += 1
        for stimulus_id, parent_id in self._db.execute(
            "SELECT stimulus_id, parent_id FROM stimuli WHERE tick < ? AND parent_id IS NOT NULL", (tick,)
        ).fetchall():
            counts.setdefault(parent_id, {"likes": 0, "reposts": 0, "upvotes": 0, "downvotes": 0})
        replies: dict[str, int] = {}
        for parent_id, in self._db.execute(
            "SELECT parent_id FROM stimuli WHERE tick < ? AND parent_id IS NOT NULL", (tick,)
        ).fetchall():
            replies[parent_id] = replies.get(parent_id, 0) + 1
        for stimulus_id, entry in counts.items():
            entry["replies"] = replies.get(stimulus_id, 0)
        for stimulus_id in replies:
            counts.setdefault(stimulus_id, {"likes": 0, "reposts": 0, "upvotes": 0, "downvotes": 0, "replies": replies[stimulus_id]})
        return counts

    def ancestry(self, stimulus_id: str) -> tuple[str, ...]:
        """Reply chain from nearest parent to root, following stored parents."""
        chain: list[str] = []
        seen = {stimulus_id}
        parent = self._db.execute(
            "SELECT parent_id FROM stimuli WHERE stimulus_id = ?", (stimulus_id,)
        ).fetchone()
        while parent is not None and parent[0] is not None:
            if parent[0] in seen:
                break
            chain.append(parent[0])
            seen.add(parent[0])
            parent = self._db.execute(
                "SELECT parent_id FROM stimuli WHERE stimulus_id = ?", (parent[0],)
            ).fetchone()
        return tuple(chain)

    def provenance_complete(self) -> bool:
        """Every row names its world and the tick it was written at."""
        for table in ("stimuli", "engagements"):
            missing = self._db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE world_id IS NULL OR written_tick IS NULL"  # noqa: S608
            ).fetchone()[0]
            if missing:
                return False
        return True

    def export(self) -> dict:
        """All rows for a checkpoint: stimuli and engagements in stable order."""
        stimuli = self._db.execute(
            "SELECT stimulus_id, tick, author, kind, text, claim_id, parent_id, world_id, written_tick"
            " FROM stimuli ORDER BY stimulus_id"
        ).fetchall()
        engagements = self._db.execute(
            "SELECT stimulus_id, action, persona_id, tick, world_id, written_tick"
            " FROM engagements ORDER BY stimulus_id, action, persona_id, tick"
        ).fetchall()
        return {"stimuli": stimuli, "engagements": engagements}

    def import_data(self, data: dict) -> None:
        """Restore rows exported by `export`; provenance travels with them."""
        self._db.executemany("INSERT INTO stimuli VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", data["stimuli"])
        self._db.executemany(
            "INSERT INTO engagements (stimulus_id, action, persona_id, tick, world_id, written_tick)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            data["engagements"],
        )
        self._db.commit()

    def dump(self) -> str:
        """The canonical logical state: ordered rows, comparable across processes."""
        parts = []
        for row in self._db.execute(
            "SELECT stimulus_id, tick, author, kind, text, claim_id, parent_id, world_id, written_tick"
            " FROM stimuli ORDER BY stimulus_id"
        ).fetchall():
            parts.append("stimulus:" + "|".join("" if item is None else str(item) for item in row))
        for row in self._db.execute(
            "SELECT stimulus_id, action, persona_id, tick, world_id, written_tick"
            " FROM engagements ORDER BY stimulus_id, action, persona_id, tick"
        ).fetchall():
            parts.append("engagement:" + "|".join(str(item) for item in row))
        return "\n".join(parts) + ("\n" if parts else "")
