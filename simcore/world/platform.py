# Adapted from OASIS (https://github.com/camel-ai/oasis, Apache-2.0):
# `platform.py` + `channel.py` (already trace-shaped — extended, not
# rewritten). Upstream channels decide what lands; here the world owns
# affordances: an action a channel does not support is recorded as rejected
# and changes no state, never raised, never retried.

"""Where a platform's facts live, and what each channel allows.

The world is the authority on what a channel supports. A persona may attempt
anything; the channel decides what lands. An unsupported action is recorded
with its rejection and dropped — what a persona tried is data, not an error.
"""

from enum import StrEnum

from simcore.schemas import CHANNEL_AFFORDANCES, action_lands, ActionKind, Channel

# What each channel supports. Ignoring needs no support: doing nothing lands anywhere.
# The table lives in `schemas`, beside the record that counts engagement by it: the world and the
# partition cannot disagree about whether an action landed.
AFFORDANCES = CHANNEL_AFFORDANCES


def is_supported(channel: Channel, action: ActionKind) -> bool:
    """Whether an action lands on a channel; rejected actions change no state."""
    return action_lands(channel, action)


class ForumPreset(StrEnum):
    """The two dynamics of the one forum class: herding globally, slow hardening by community."""

    REDDIT_GLOBAL = "reddit_global"
    COMMUNITY_SCOPED = "community_scoped"


class Forum:
    """One forum class, two presets — the comparison is a study variable, not a fork.

    `reddit_global` lets any persona reach any thread and ranks by the
    upstream hot score: herding, fast. `community_scoped` scopes threads to
    the population's Leiden communities and ranks by recency and agreement
    with no hot score: consensus hardening, slow.
    """

    def __init__(self, preset: ForumPreset | str) -> None:
        self.preset = ForumPreset(preset)

    def threads_for(
        self, viewer: str, rows: list[dict], community_of: dict[str, str]
    ) -> list[dict]:
        """The threads a persona can reach.

        Under the global preset, every thread. Under the scoped preset, the
        study's own stimuli, threads rooted in the viewer's community, and
        threads rooted in the shared proposition — a reply to the study is a
        response everyone may read. A persona with no community assignment is
        handled explicitly: it keeps the study's stimuli and its own posts,
        and is never silently excluded.
        """
        if self.preset is ForumPreset.REDDIT_GLOBAL:
            return list(rows)
        if not community_of or viewer not in community_of:
            return [row for row in rows if row["author"] is None or row["author"] == viewer]
        parents = {row["stimulus_id"]: row["parent_id"] for row in rows}
        authors = {row["stimulus_id"]: row["author"] for row in rows}

        def root(stimulus_id: str) -> str:
            seen = set()
            while parents.get(stimulus_id) is not None and stimulus_id not in seen:
                seen.add(stimulus_id)
                parent = parents[stimulus_id]
                assert parent is not None
                stimulus_id = parent
            return stimulus_id

        mine = community_of[viewer]
        visible = []
        for row in rows:
            if row["author"] is None:
                visible.append(row)
                continue
            root_author = authors.get(root(row["stimulus_id"]))
            if root_author is None or community_of.get(root_author) == mine:
                visible.append(row)
        return visible


__all__ = ["AFFORDANCES", "Forum", "ForumPreset", "is_supported"]
