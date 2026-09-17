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

from simcore.schemas import ActionKind, Channel

# What each channel supports. Ignoring needs no support: doing nothing lands anywhere.
AFFORDANCES: dict[Channel, frozenset[ActionKind]] = {
    Channel.SURVEY_ROOM: frozenset({ActionKind.ANSWER}),
    Channel.SOCIAL_FEED: frozenset(
        {
            ActionKind.POST,
            ActionKind.COMMENT,
            ActionKind.LIKE,
            ActionKind.REPOST,
            ActionKind.QUOTE,
            ActionKind.FOLLOW,
        }
    ),
    Channel.FORUM: frozenset(
        {
            ActionKind.POST,
            ActionKind.REPLY,
            ActionKind.UPVOTE,
            ActionKind.DOWNVOTE,
        }
    ),
    Channel.WOM: frozenset({ActionKind.ANSWER}),
}


def is_supported(channel: Channel, action: ActionKind) -> bool:
    """Whether an action lands on a channel. Ignoring always lands; anything
    else must be afforded, or it is recorded as rejected and changes no state."""
    if action is ActionKind.IGNORE:
        return True
    return action in AFFORDANCES[channel]


class Forum:
    """One forum class, two presets — the comparison is a study variable, not a fork.

    `reddit_global` lets any persona reach any thread and ranks by the
    upstream hot score: herding, fast. `community_scoped` (next phase) scopes
    threads to the population's Leiden communities and ranks by recency and
    agreement with no hot score: consensus hardening, slow.
    """

    def __init__(self, preset) -> None:
        self.preset = preset

    def threads_for(self, viewer: str, rows: list[dict], community_of: dict[str, str]) -> list[dict]:
        """The threads a persona can reach: every thread under the global preset."""
        return list(rows)


__all__ = ["AFFORDANCES", "Forum", "is_supported"]
