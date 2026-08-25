---
status: accepted
date: 2026-08-25
---

# ADR-005 — A digest is dated, never current

## Context

This one was learned the hard way, from a snapshot of local agent state that was
**wrong on two of its four fields at the moment it was read**: it reported a task as
blocked on a credential that had already been created, and suggested a follow-up on a
pull request that had been merged weeks earlier. Neither error was detectable from
inside the snapshot. Both had the same cause: the discharge happened somewhere that
emits no event, so nothing told the record it was stale.

Generating that automatically, writing it to a store, and handing it to a consumer that
acts on it makes the wrong answer *distributable*. That is the trust-destroying failure
mode, industrialised.

The asymmetry underneath: **a stale increment annoys; a wrong decrement destroys the
count**, and the count is the product.

## Options

**Report current state, and accept that some of it is stale.** This is what the failing
snapshot did. It is the norm for status tooling, and it is why nobody trusts status
tooling.

**Verify before displaying.** Correct, and it requires a machine-checkable predicate per
record plus the credentials to evaluate it. This release has neither, by
[ADR-002](002-what-the-first-release-contains.md).

**Never make the claim.** Report what was said and when, and let the reader decide what
is still true.

## Decision

**A digest states what the session said, dated. It never states what is currently true.**

Mechanically:

- Every section heading carries the timestamp of the thing under it.
- The loop state is phrased as a reading of a specific turn, at a specific time.
- The front matter says `verified: false`, because nothing has been checked against
  anything.
- No line says "still open", "still needs" or "remains open".
- When the loop state is the default rather than a reading, the digest says so.
- Claude Code's own recap is carried, and if it predates the closing turn the digest
  says that too — they can disagree, and the reader should see both rather than a
  reconciliation openloops is not entitled to make.

## Consequences

A digest is less immediately actionable than a status line, and more trustworthy. The
user does the last step — deciding what is still true — because the user is the only
party here who can.

When a verify predicate does arrive, it slots in against `verified: false` without
changing anything else about the format. That is the point of stating the field now
rather than omitting it.

## Confirmation

- A test asserts every section heading carries a date.
- A test asserts the rendered text contains none of the forbidden present-tense claims.
- A test asserts a default verdict is displayed as a default, not as a reading.
