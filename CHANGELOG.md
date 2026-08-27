# Changelog

All notable changes to this project are documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/); each section
corresponds to a git version tag (which is also the release published to PyPI).

## [Unreleased]

### Added

- `openloops.owed()` and `ol owed` — the obligation reader. Lists the open
  `manual-task` issues across the owners you configured, runs the `**Verify:**` shell
  predicate each issue body carries, and reports **three** states: `open` (no predicate,
  or it returned non-zero), `discharged` (it returned `0` — the ask is done and the
  issue is merely still open) and `unknown`/`?` (nothing could be checked). `unknown`
  never collapses into either of the others, and a listing that failed prints `?` rather
  than a count: a surface that says "nothing owed" because it could not check is the
  failure this exists to prevent.
- Two more seams on the established pattern, each defaulting to a real implementation:
  `issues_source=` (a `gh search issues` call, behind the package's single shell-out)
  and `run_predicate=` (a subshell with an explicit timeout). With both injected the
  reader needs no network and no `gh`, which is how its tests run.
- A stated trust boundary, because evaluating a predicate executes text from a GitHub
  issue: predicates run only for `trusted_owners` (defaulting to the owners searched),
  the command is always printed next to its verdict, `--no-verify` lists without
  executing anything, and every evaluation is time-bounded.
- `OPENLOOPS_OWNERS` — comma- or space-separated owners to search. Without it the
  authenticated `gh` login is used, and whichever it was is reported on every result.

### Changed

- The README no longer says the obligation half is withheld pending a measurement. That
  measurement was cancelled; the smallest useful version shipped instead, and it names
  its own kill criterion in `openloops/obligations.py`.
- The test that forbade obligation vocabulary anywhere in the package — the mechanical
  form of that withholding — is replaced by one that checks what is still true: no
  surface exposes an operation that writes, and nothing in the package builds a
  mutating `gh` call. Nothing here closes, reopens, relabels or comments on an issue.

## [0.1.0] - 2026-08-25

First release. The session-digest extractor and reader, and nothing else.

### Added

- `openloops.sync()` — read Claude Code's persisted session state and write one dated
  markdown digest per session. No model, no network, no credentials.
- Two seams, each one keyword argument: `transcript_source=` (defaults to a direct
  reader of the on-disk layout) and `digests_store=` (defaults to a directory under
  `~/.local/share/openloops/`).
- A loop-state classifier that reads a session's own last turn. It is a closed-detector
  with `open` as the default: a session reaches `archive` only by saying it finished.
- The `ol` console script: `ol` (sync and show open loops), `ol sync`, `ol ls`,
  `ol show`, `ol status`, `ol install-job` / `ol uninstall-job` / `ol job-status`.
- The supervised periodic job — a launchd `StartInterval` agent, not a daemon.
- An egress choke point applied before any digest is written: home paths are rewritten
  to `~`-relative, and credential-shaped text raises rather than being redacted.
- mtime-gated change detection, with the cache kept outside the digest store so that
  clearing one cannot reach the other, and versioned so that a change to the renderer
  re-derives instead of leaving old digests frozen.
- The default digest store is `dol` over a directory of markdown files, with its
  encoding pinned to UTF-8 (the locale default breaks a `LANG`-unset cron job on the em
  dash every digest contains) and its delete made a real delete rather than a move to
  the desktop Trash. Any `MutableMapping[str, str]` substitutes for it through the seam.

### Notes for readers of the source

`openloops.sync` and `openloops.classify` are the *functions*. Their modules are
`openloops._sync` and `openloops._classify` — a module and a function cannot both answer
to the same attribute, and the function is the one the API is written around. Everything
those modules export is re-exported from the package, cue tables included.

### Not included, deliberately

Obligations, a ledger, any GitHub read or write, any MCP server, any model call, any
notification surface. See the README's "What openloops is NOT (yet)".
