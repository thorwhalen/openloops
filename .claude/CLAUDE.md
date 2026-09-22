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
- `obligations.py` — `owed()`: manual-task issues filed across the fleet, re-checked
  against current GitHub state before being shown.
- `blockers.py` — the other open-loop kind: a fix filed in repo Y for a problem
  found in repo X, where X is never told when Y ships.
- `dashboard.py` — `render_dashboard()`: one self-contained static HTML page from
  `owed()`/`blocked()`/`ls()` — no script, no network call.
- `tools.py` — **the single surface all dispatch goes through** (CLI today, MCP/HTTP
  later): plain functions taking/returning flat JSON-ready dicts — `sync`, `ls`,
  `show`, `status`, `owed`, `blocked`, `dashboard`.
- `job.py` — the periodic-job (launchd `StartInterval`) design: no daemon, ADR-006.
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
  run-time) — reads files already on disk, writes files the user already owns.
- `openloops/data/skills/` and `openloops/data/agents/` are markdown shipped inside
  the wheel; `tests/test_skills.py` builds a wheel and checks they're actually in it.

## Docs & skills

- ADRs: `docs/adr/001`–`007` (naming, release scope, public/private boundary, loop
  state vs process state, the digest-dated rule, periodic-job design, the two seams).
- Shipped skills/subagent: `.claude/skills/openloops`, `.claude/skills/openloops-needs-human`,
  `.claude/agents/openloops-sweep.md` (also documented via `openloops-sweep` skill).

## Dependents

`astern`, `crowsnest` import this package (per fleet dependency graph) — check their
tests before changing `tools.py`'s function signatures or return shapes.
