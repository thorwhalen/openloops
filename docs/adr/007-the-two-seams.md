---
status: accepted
date: 2026-08-25
---

# ADR-007 — The two seams, and what is deliberately not one

## Context

The boundaries of a package are decided once, in the first release, and every later
iteration either adds at a boundary that already exists or churns every caller. The
question is which boundaries, and the failure modes are symmetric: hardwire everything
and v2 is a rewrite; declare nine injection points and there is no v1.

## Decision

**Two seams. Each is one keyword argument, and each defaults to the strongest
implementation that needs no new dependency — useful out of the box, never a stub.**

| Seam | v1 default | The replacement it exists for |
|---|---|---|
| `transcript_source=` | a direct reader of Claude Code's on-disk layout | another machine's synced transcripts; an in-house parser; a test fixture |
| `digests_store=` | a directory of markdown files under the data root | a git-synced directory shared between machines; blob storage |

Both are `Mapping`s, so a plain `dict` substitutes for either in a test, and the
`{source}/{state}/{session}.md` key layout comes along with any backend.

**The default store is thirty lines openloops owns, not a library.** A general-purpose
file store was tried and removed: what it gave for free it also gave wrongly here —
text opened in the *locale* encoding, so a cron job with `LANG` unset dies on the em dash
every digest contains, and a delete that sends the file to the desktop Trash, which for
session digests is an undeclared second copy of every superseded one, outside the store,
indefinitely. The seam is the `MutableMapping` interface, so `dol`, `s3dol` or a `dict`
still drop in unchanged — they are simply not imported by anyone who does not ask for
them. The package has one dependency, and it is the CLI parser.

**Deliberately not seams**, written directly and on purpose: the digest markdown
template, the classifier's rule set (its cue lists are ordinary keyword arguments, not
an injection point), the CLI's argument parsing, and the report format. Each could
plausibly want to vary; none has a replacement anyone can point at today, and a seam
whose replacement is imaginary is generality that gets maintained and never used.

One caveat an adapter must honour: the seam arguments are for callers, not for models.
An MCP or HTTP surface built over `openloops.tools` must not advertise `transcript_source`
or `digests_store` in its schema — a model that helpfully supplies an empty store would
be told, confidently, that it has no open loops.

**One surface: the `ol` command.** The core returns JSON-ready dicts from a single list
of functions and prints nothing, so an MCP or HTTP adapter would dispatch from that same
list rather than needing the core to change. Whether either is worth building is not
this release's question; keeping the core able to answer it is.

## Consequences

The store seam is what makes the public/private split of
[ADR-003](003-the-public-private-boundary.md) cheap: the private half is a *backend*,
selected by one argument, not a fork.

`ClaudeCodeTranscripts` supplies a cheap `revision()` token from file modification
times, and any mapping that does not is wrapped so it gets a total default. No caller
ever asks whether a backend supports change detection — capability probing is backend
leakage by another name, and a gap in it would silently change what the user is told.

## Confirmation

- Every entry point takes both seams as keyword arguments, and the tests exercise them
  with plain dictionaries.
- A test asserts that swapping the seams also scopes the change-detection cache, so a
  caller's fixture cannot write into their real one.
- `import openloops` does not import the CLI library, and opens no socket.
- The one-command test runs the whole path on the defaults and must keep passing after
  any seam is swapped.
