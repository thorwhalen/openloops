---
status: accepted
date: 2026-11-16
---

# ADR-012 — The board rebuild is a model-free timer job that reuses what it already knows

## Context

The phone board (ADR-008, ADR-009) was rebuilt only when a session ran its first three stages by hand. A board built on 2026-10-27 was still that build on 2026-11-09, with 210 of its 420 cards closed and 222 new items missing; the receiver job (ADR-011) processes taps and never rebuilds. Gather, the heuristic classifier and build need no model: only the classifier-brief enrichment does.

## Decision

`ol board-refresh WORK` (`openloops.board_refresh.refresh_board`) is the rebuild as one deterministic step: gather every kind, diff the ids against the live `tasks.json`, stop when nothing opened or closed, otherwise rebuild reusing the earlier record of every id still open and giving each new id the free heuristic record, then list the new ids in `new-items.json` for a session to enrich. An incomplete sweep (`listed: false`) never rebuilds. The board's own settings are read from its `board.json`. Publishing is a seam (`publish=`; the CLI's `--publish-to` takes a directory or `host:dir`). `ol install-refresh-job` schedules it as a launchd `StartInterval` job (ADR-006), six hours by default.

## Consequences

- No daemon, no model, no credentials in the plist; it needs `gh` logged in for the same user.
- Enrichment is not lost on a rebuild, because records are keyed by stable id, but new items stay heuristic until a session runs the brief over `new-items.json`. Doing that automatically would need a model per tick and is a separate decision (ADR-011's "free check first" rule would apply).
- `--publish-to host:dir` uses `scp` with the user's own keys.

## When to remove it

If the board is not opened from the phone (`ol receiver-job-status` shows no taps for a month), `ol uninstall-refresh-job`; the by-hand stages still work.
