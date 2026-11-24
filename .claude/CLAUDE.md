# openloops

Finds "open loops" between you and your coding agents — what they left open, what
they need from you, what is no longer blocked — by reading Claude Code transcripts
and GitHub `manual-task` issues. Read-only: never closes, reopens, relabels or
comments on anything. No local database; the transcript/label/dependency edge *are*
the records.

## Module map (`openloops/`)

- `base.py` — shared data types (`Session`, digest record). No I/O, no judgement.
- `transcripts.py` — `ClaudeCodeTranscripts`, the default `transcript_source`: reads
  `~/.claude/projects/<cwd>/<session-uuid>.jsonl`.
- `_classify.py` — the only judgement made: did a session's own last turn *say* it
  was finished? Never inferred from whether a process is still running.
- `digest.py` — renders one session into one dated markdown digest.
- `store.py` — where digests live (`~/.local/share/openloops/digests/`, a
  `MutableMapping[str, str]`) and the separate change-detection cache.
- `egress.py` — the choke point: strips home paths/secrets before a digest leaves
  the machine (digest stores can be git-synced/shared).
- `_sync.py` — `sync()`: the incremental pass; `transcript_source=` and
  `digests_store=` are its two keyword seams, both defaulting to something that
  works with zero config.
- `exchanges.py` — `exchanges()`: each prompt of a transcript paired with its turn's reply
  (origin: typed, another session, tooling) and `question_sentences()`; pure, no model. Not in
  `tools.py`: consumers import it. Its `Exchange` fields are a contract (crowsnest reads them).
- `obligations.py` — `owed()`: manual-task issues filed across the fleet, re-checked
  against current GitHub state before being shown.
- `blockers.py` — the other open-loop kind: a fix filed in repo Y for a problem
  found in repo X, where X is never told when Y ships.
- `dashboard.py` — `render_dashboard()`: one self-contained static HTML page from
  `owed()`/`blocked()`/`ls()` — no script, no network call.
- `tasks.py` — the phone board's read side: the `Task` record schema (SSOT),
  `gather()` (multi-owner `gh search`, no 50 cap, exclusions), `heuristic_classify()`
  (no model; `classifier=` seam), `merge_records()` for classifier-brief records.
- `board.py` — `build_board()`: tasks.json, runs.json (run specs are data:
  `openloops/data/board/runs.json`), board.json, and the page template shipped in
  `openloops/data/board/`. The write side is the `openloops-phone-board` skill (ADR-008).
- `board_store.py` — the board store API's rules over any MutableMapping (roles,
  immutable events, newest-wins drafts); no network. `board_server.py` — optional
  FastAPI app (`openloops[server]`) wrapping it; nothing else imports it (ADR-009).
- `loops.py` — the `Loop` record (one commitment: A2A `state`, GTD `list`, `remind_at`/`due`, provenance, append-only log) and the pure `evaluate(loops, now)` → actions (ADR-013). No I/O.
- `remind.py` — the reminder runner, imported by nothing in the core: `remind`/`done`/`snooze`/`tick` over three seams (`store=` JSON files under `~/.local/share/openloops/loops/`, `deliver=` correspond's ntfy with scheduled delivery and cancel, `settings=` from env). The `openloops[remind]` extra.
- `pile.py` — the capture pile (GTD In list as issues in a private repo): `items`/`show`
  (read), `propose` (heuristic, `proposer=` seam), `plan` (the signed steps for one
  decision, as data: the caller writes, ADR-014), `signed`, `nudge` (one pending reminder
  loop while items are stale; never touches an item).
- `tools.py` — **the single surface all dispatch goes through** (CLI today, MCP/HTTP
  later): plain functions taking/returning flat JSON-ready dicts — `sync`, `ls`,
  `show`, `status`, `owed`, `blocked`, `dashboard`, `published`, `board_*`, `remind`, `loops`, `done`, `snooze`, `remind_tick`, `pile*`.
- `board_refresh.py` — `refresh_board()`: the model-free board rebuild on a timer (ADR-012; `ol board-refresh`, `ol install-refresh-job`). `merge_refresh()` is the pure merge; the scope and the last-published hash live in `WORK/refresh.json`.
- `job.py` — the periodic-job (launchd `StartInterval`) design: no daemon, ADR-006; also the board-receiver job (ADR-011).
- `receiver_tick.py` — run by that job, nothing imports it: a no-model check of the
  board store (HTTP), then `exec` of `claude -p` only if work is pending. The one module
  that reaches the network.
- `skills.py` — the agent-facing surface: `ol install-skills` symlinks the shipped
  skills/subagent (`openloops/data/skills/`, `openloops/data/agents/`) into
  `~/.claude`.
- `__main__.py` — `ol` CLI entry point (`openloops.__main__:main`).

## Tests & lint

```bash
uv venv .venv && uv pip install -e . pytest ruff
.venv/bin/pytest            # tests/ + doctests in openloops/ (testpaths in pyproject.toml)
.venv/bin/ruff check .
```
Or `wads ci-local` for the full matrix (Python 3.10 + 3.12, per `[tool.wads.ci]`).

**Gotcha:** `tests/test_sync.py::test_an_unreadable_transcript_is_reported_not_swallowed`
fails when run as root — it `chmod`s a file to simulate an unreadable transcript, and
root ignores file-mode permissions. Not a regression; run as a non-root user to see it
pass, or ignore that one failure in a root sandbox.

## Invariants

- **A digest says what a session said, dated — never what is true now** (ADR-005).
  Nothing here re-checks a digest's own content against the world after writing it.
- Never calls a model, never reaches the network, needs no account (import-time or
  run-time) — reads files already on disk, writes files the user already owns. The
  exceptions: `receiver_tick.py` (ADR-011), which nothing imports; `remind.py` (ADR-013),
  which writes the loops store and reaches ntfy through correspond, imported by nothing in the core; the `gh` reads of
  `obligations`/`tasks.gather`; and `board_refresh`'s optional `scp` publish to a host
  the owner names (`--publish-to host:dir`, ADR-012).
- `openloops/data/skills/` and `openloops/data/agents/` are markdown shipped inside
  the wheel; `tests/test_skills.py` builds a wheel and checks they're actually in it.

## Docs & skills

- ADRs: `docs/adr/001`–`014` (naming, release scope, public/private boundary, loop
  state vs process state, the digest-dated rule, periodic-job design, the two seams,
  board write side in a skill, self-hosted board store, agents decide what is reversible and clearly recommended, the board receiver as a periodic job, the board rebuild as a free timer job, loops and reminders a channel holds, the pile: openloops reads and plans, the caller writes). ADR-015 is **proposed, not accepted** (a manual task can close itself): do not build from it until its status changes. ADR-016 is **proposed, not accepted** (a session can be rendered as a private page): same rule.
- Shipped skills/subagent: `.claude/skills/openloops`, `.claude/skills/openloops-needs-human`,
  `.claude/skills/openloops-phone-board`, `.claude/skills/openloops-remind`, `.claude/skills/openloops-pile` (triage of the owner's capture pile into loops, ideas and issues),
  `.claude/agents/openloops-sweep.md` (also documented via `openloops-sweep` skill).

## Dependents

`astern`, `crowsnest` import this package (per fleet dependency graph) — check their
tests before changing `tools.py`'s function signatures or return shapes.
