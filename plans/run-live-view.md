# Plan: the run page as a live view

The `/run` page becomes tabs over one run: the world graph replaying each closed tick, the X-like
feed, the Reddit-like forum, word of mouth, and the numbers (audience PMFs, belief movement, purchase
intent per wave). Decided 2026-10-02:

- **Tick replay, not turn streaming.** Readers see closed ticks only; a closed tick's turns play back
  in record order. A running study is watched one tick behind; a finished one replays the same way.
- **Conversations form; communities do not.** Communities are the draw's fixed partition. What grows
  is who has talked to whom and who follows whom — shown as such, coloured by community where any formed.
- **The engine computes every number.** After each closed tick the study writes `live/<world>.json`
  with the same `digest` the report uses; the page only displays it.

## Phase 1 — live digest (engine)
- [x] `run_study` writes `live/<world_id>.json` after each closed tick, from `digest` over the live view.
- [x] A failure to digest is written as the reason, never breaks the run.
- [x] `GET /api/runs/{id}/live` serves the live digests; the interface proxies it.

## Phase 2 — tabs and replay clock
- [x] Tabs: World, Numbers, X-like feed, Reddit-like forum, Word of mouth, Run details.
- [x] One replay clock (tick, play/pause, speed) shared by the activity tabs; follows new ticks while live.

## Phase 3 — world graph
- [x] Every persona a dot; an acting persona flashes in its channel's colour with a bubble naming the action.
- [x] A word-of-mouth delivery, or a reaction to another persona's post, lights the link between them.
- [x] Links that carried something stay drawn: the conversation network forming, tick by tick.

## Phase 4 — feed, forum, word of mouth
- [x] Each channel's turns as a stream: who, what action, on whose post, in their words.

## Phase 5 — numbers
- [x] Intent over waves (live), audience PMFs, belief movement mean and absolute, action mix.
