---
status: accepted
date: 2026-08-25
---

# ADR-002 — What the first release contains, and what is withheld

## Context

openloops began as a design for something else: a ledger of what you owe your agents and
what they owe you. That design is finished. It is also **unevidenced** — whether such a
ledger is worth building depends on whether agents actually file the asks they raise,
and that number had never been measured. Building the schema first would have been
construction in search of a justification.

Meanwhile the same machinery that would measure it — a reader of Claude Code's own
persisted session state — is useful on its own, to anyone, on day one, with no account
and no configuration.

## Options

**Ship the obligation read path.** It is the project's headline claim and it already
works — for one person, with a provisioned label across a hundred-odd repositories and
authenticated credentials. As a public package's first release it would be a personal
shell alias with packaging around it.

**Ship a placeholder to reserve the name.** Fastest, and it spends the one first
impression the package gets on a stub.

**Ship the session-digest extractor and reader.** Useful with no GitHub, no model, no
fleet and no configuration. Produces the measurement's instrument as a by-product.
Exercises the store seam the whole public/private split depends on, on day one, where it
is cheapest to get right.

## Decision

**v0.1.0 is the session-digest extractor and reader, and nothing else.**

In scope: reading Claude Code's persisted sessions behind a `transcript_source=` seam;
deriving one digest per session from its last turn and its own recap, with **no model**;
writing digests behind a `digests_store=` seam; mtime-gated change detection; a read
path; the `ol` command; and the periodic job.

**Explicitly out of scope, and stated as deliberate in the README:** obligations, the
ledger, any GitHub read or write, any MCP server, any model call, any notification
surface.

The package's public identity for this release is *"a tool that tells you what your
Claude Code sessions were doing"*, not *"a tool that tracks what you owe your agents"*.
That is a narrower and less interesting claim, and it is the one currently supported by
evidence.

## Consequences

The README has to be honest that the ledger is withheld pending a measurement rather
than merely unfinished. That is a more credible story than a half-built ledger, and it
is true.

Shipping a package makes it psychologically easier to declare the measurement satisfied
by momentum rather than by measurement. The mitigation is ordering: the measurement was
run and reported before this surface was merged, so the number existed before there was
anything to rationalise.

A framing this release should be read through: Claude Code garbage-collects transcripts
after about a month, so **a digest outlives the thing it was derived from.** That makes
this a retention device rather than a dashboard, and it is the honest answer to "why not
just look at your sessions".

## Confirmation

- `pip install openloops && ol` produces useful output on a machine with a `~/.claude`
  directory, no credentials and no network.
- The test suite passes with no network, no credentials and no `~/.claude` present.
- A grep of the package source for obligation vocabulary returns nothing.
