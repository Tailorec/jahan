# Channels, survey waves and launch reach are scenario content

A study chooses which channels spread information — social feed, forum, word of mouth, in any combination including
none — and measures purchase intent in survey waves put to every persona at a fixed interval, apart from anything
they do on a channel. All three settings (the channels, the survey interval and, when word of mouth is the only
channel, the launch reach) are part of the scenario, so they enter the scenario's canonical hash and with it every
world identity (ADR 0005) and the run's config hash.

The architecture specified a list of channels per scenario and a persona reacting once per channel per tick. The
first world phase (2026-09-17) built a single `platform` per world instead, chosen outside the scenario, and
nothing later lifted it: a study picked one environment, word of mouth rode hard-wired beside the feed or forum, and
purchase intent was asked of every channel turn or of none. Because the channel was not scenario content, a feed run
and a forum run over the same population and seed shared their config hash and world id — a result could not say
which environment produced it, and a resume naming a different channel was not refused as a moved input.

## Considered options

Keeping the channels as run-level settings outside the scenario was rejected: it preserves existing hashes, but two
worlds that differ only in their channels would still collide, and channels could not be varied within one run.
Asking purchase intent inside channel turns (the old `elicits`) was rejected: intent would come from whoever a
channel happened to activate, mixed into what they did there, rather than from everyone on one schedule.

## Consequences

Every existing world identity and config hash changes. Runs recorded before the change stay readable; resuming one
is refused as a moved input. A study runs one world with its channels fixed from launch to horizon; an experiment on channels
is another simulation over the same population. Because a world's seed still derives from the replicate seed and the
variant alone (ADR 0005), two simulations that differ only in their channels share their random draws, so comparing
them isolates what the channels did. The survey room is no longer an
environment: it is a scenario with no channels. A survey wave only reads a persona and never changes its state, and
the degrade ladder never thins one: a world pauses before a wave it cannot afford.
