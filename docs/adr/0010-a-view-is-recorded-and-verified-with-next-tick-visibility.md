# A persona's view is recorded with its turn, verified, and sees only earlier ticks

During a turn a persona sees its impression and a **view**: the public context of exactly those stimuli — engagement counters, reply ancestry, and its tie strength and shared community with each author — and nothing else. No other persona's private state and no aggregate outcome is ever visible, because a persona that can see running adoption reacts to the very result being measured, building herding in by construction.

The view is recorded inside the turn and the partition verifies it against its own earlier events: counters must equal engagement recorded at **earlier ticks**, and ancestry must follow the reply chain. Engagement is therefore invisible within the tick it happens. Votes split into upvotes and downvotes so both can be counted.

## Considered options

Re-deriving views from the trace during analysis was rejected because the counting and timing rules would then live in both the world and analysis, and "what did this persona see" could get two answers. Recording the view without verifying it was rejected because a stored count could disagree with the events beside it unnoticed.
