---
status: accepted
date: 2026-08-25
---

# ADR-006 — A periodic job, not a daemon

## Context

Digests have to be refreshed by something. The tempting shape is a resident process: it
amortises startup, holds a warm cache, and can react the moment a transcript changes.

None of those amortised costs exist here. A full scan of a real transcript directory
takes a fraction of a second because change detection is an mtime comparison, and there
is nothing to react to in under a minute — a digest records what a session said, so
being a quarter of an hour behind costs nothing.

What a resident process does have is the failure mode this whole project was built
against: **unsupervised state that goes stale**. When it dies, its last output stays
behind, looks current, and has nothing scheduled to correct it.

## Options

**A resident process.** Amortises costs that are not being paid, and makes its own
liveness a correctness property rather than a latency one.

**Nothing scheduled at all; refresh on read.** Simple, but then the digest store is only
ever as fresh as the last time somebody looked — and the store's whole value is that it
outlives the transcripts, which requires writing before they are collected.

**A supervised periodic job that runs, writes, and exits.**

## Decision

**One launchd `StartInterval` agent. It runs `ol sync`, writes, and exits.** Nothing
resident, nothing to supervise beyond launchd itself.

Two implementation details are part of the decision rather than incidental:

- **The interpreter is invoked directly**, not a console script resolved by name.
  launchd hands a job a nearly empty `PATH`, and a name resolved there is a lottery
  whose losing ticket is a job that dies instantly, every tick, silently.
- **The environment is captured at install time and pinned into the plist**, for the
  same reason. Re-run the installer after moving the interpreter.

**`ol job-status` reports when the job last *wrote*, not just whether it is registered.**
A job that is loaded and doing nothing produces exactly the same silence as a job with
nothing to do, and the two must be distinguishable.

## Consequences

Up to one interval of staleness, which nothing in this release cares about.

The installer is macOS-only. On Linux the same command belongs in a systemd user timer
or a crontab line; the package itself is cross-platform and the installer says so rather
than pretending otherwise.

**The design test this makes structural:** with every session stopped and the job
stopped, `ol ls` still answers, because no read path depends on a process openloops
owns. Any future feature that breaks that has reopened this decision.

## Confirmation

- A test asserts the plist uses `StartInterval` and carries no `KeepAlive`.
- A test asserts the job invokes the interpreter with `-m`, never a script name.
- `ol job-status` reports the age of the last write.
