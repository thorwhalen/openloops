---
status: accepted
date: 2026-11-16
---

# ADR-012 — The board rebuild is a model-free timer job that reuses what it already knows

## Context

The phone board (ADR-008, ADR-009) was rebuilt only when a session ran its first three stages by hand. A board built on 2026-10-27 was still that build on 2026-11-09, with 210 of its 420 cards closed and 222 new items missing; the receiver job (ADR-011) processes taps and never rebuilds. Gather, the heuristic classifier and build need no model: only the classifier-brief enrichment does.

## Decision

`ol board-refresh WORK` (`openloops.board_refresh.refresh_board`) is the rebuild as one deterministic step: gather every kind, merge with the live `tasks.json` (`merge_refresh`, pure), stop when nothing opened, closed or was retitled, otherwise rebuild, keeping the earlier record of every id still open (its `title` and `url` refreshed from GitHub, never re-classified) and giving each new id the free heuristic record. New ids accumulate in `new-items.json` (until they close) for a session to enrich; a session deletes or trims the file once the brief has run.

The scope lives in `WORK/refresh.json`: owners, exclusions, searches, PR reviews, the run specs and run extras paths, where to publish, and the sha256 of the `tasks.json` last published. Flags given to `board-refresh` or `install-refresh-job` are saved there through one function (`remember_scope`); absent flags are read from it, so the launchd plist names only `WORK`. The board's own settings come from its `board.json`: the first board is built by hand (`ol board-build`), and a refresh with no `board.json` refuses rather than publishing defaults.

Guards, because a wrong rebuild is worse than a stale one:

- an incomplete sweep (`listed: false`) never rebuilds, and the CLI exits 1 so a failing timer shows;
- a saturated sweep (a search hit its cap) adds but never closes;
- a rebuild that would close more than half (`max_close_fraction`) of a board of ten or more cards holds the closes back (additions and retitles still apply, `status: partial`, exit 0 with the remedy `--force` printed; exit 1 if nothing else changed) unless `--force`, so a long gap cannot freeze the board;
- a `tasks.json`, `board.json` or `refresh.json` that exists but does not parse, or has the wrong shape, raises; only a missing one is empty;
- the board's files are built in a temporary directory and moved into place one by one with `os.replace` (`tasks.json` last), since the receiver job reads them at any moment; a `kit.html` that differs from the packaged template is the owner's edit and is kept.

Publishing is a seam (`publish=`; the CLI's `--publish-to` takes a directory or `host:dir`). It runs whenever the local `tasks.json` hash differs from the last one published there, not only after a rebuild, and the hash is recorded only after a success, so a failed publish is retried on the next tick; the failure exits 1 and leaves the local rebuild in place. `ol install-refresh-job` schedules it as a launchd `StartInterval` job (ADR-006), six hours by default.

A board whose page keeps its state in a claude.ai Artifact (`store: artifact`) cannot be republished by a timer: a rebuild returns `needs_republish: True`, and the board is only as fresh as its last republish from a session.

## Consequences

- No daemon, no model, no credentials in the plist; it needs `gh` logged in for the same user.
- Enrichment is not lost on a rebuild, because records are keyed by stable id, but new items stay heuristic until a session runs the brief over `new-items.json`. Doing that automatically would need a model per tick and is a separate decision (ADR-011's "free check first" rule would apply). A kept record's other fields (labels, body) are not re-read; only `title` and `url` follow GitHub.
- After a refresh, by-hand stages start from `WORK/board/tasks.json` (it holds every record, enriched or not), not from an older `records.json`.
- `--publish-to host:dir` uses `scp -o BatchMode=yes` with the user's own keys and a timeout; the remote copy is not atomic (a reader on the host may briefly see a partial file).
- A packaged `kit.html` that changes in a new release is not picked up by a board whose kit differs from it; delete the board's `kit.html` to take the new one.

## When to remove it

If the board is not opened from the phone (`ol receiver-job-status` shows no taps for a month), `ol uninstall-refresh-job`; the by-hand stages still work.
