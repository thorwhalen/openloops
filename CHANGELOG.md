# Changelog

All notable changes to this project are documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/); each section
corresponds to a git version tag (which is also the release published to PyPI).

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
- One dependency: `argh`, for the CLI. The default digest store is a small
  `MutableMapping` over a directory, so `dol`, `s3dol` or a `dict` substitute for it
  through the seam without being imported by anyone who does not use them.

### Notes for readers of the source

`openloops.sync` and `openloops.classify` are the *functions*. Their modules are
`openloops._sync` and `openloops._classify` — a module and a function cannot both answer
to the same attribute, and the function is the one the API is written around. Everything
those modules export is re-exported from the package, cue tables included.

### Not included, deliberately

Obligations, a ledger, any GitHub read or write, any MCP server, any model call, any
notification surface. See the README's "What openloops is NOT (yet)".
