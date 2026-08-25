---
status: accepted
date: 2026-08-25
---

# ADR-004 — Loop state, not process state

## Context

A folder of session digests wants a split. The obvious one — "active" and "inactive" —
is a trap, because "active" has two meanings that look the same from a distance: *a
process is running*, and *the loop is not closed*.

If it means the first, the folder is a session dashboard. Claude Code already has one,
it is better at it, and duplicating it adds a surface without replacing anything. It is
also the wrong answer to the question a user actually has, since the sessions worth
remembering are precisely the ones no longer running.

## Options

**Split by process liveness.** Cheap to compute and immediately wrong: every session
that ended, including every session that ended with something unresolved, files as
inactive.

**Split by external evidence** — the linked pull request merged, the issue closed. This
is the only thing that can *honestly* close a loop, and it requires credentials, a
network and a provider integration, none of which this release has.

**Split by what the session itself said.** Available from the transcript alone, honest
about being a reading rather than a fact, and it is the question the tool is named for.

## Decision

**The store splits into `open/` and `archive/` by loop state, read from the session's
own last turn. Nothing in openloops looks at whether a process is running.**

Six rules decide it. Two are structural: the transcript stopping before the assistant's
turn completed, and a last turn that is a usage-limit or API-error banner rather than
the assistant's own words. Three are textual, over the closing lines: a question put to
the reader, a phrase deferring something, or a phrase declaring the session finished.

The sixth exists because the first five say nothing at all on roughly a quarter of
sessions. **When the closing turn is mute, the session's own recap gets the last word** —
Claude Code writes a one-to-three-sentence recap after each turn and most sessions carry
one, so ignoring evidence already on disk in favour of a shrug would be a strange kind of
rigour. Two guards keep it safe: it is consulted last, so it can never override a verdict
the closing turn supported, and it is ignored when it predates that turn, because a stale
"nothing pending" is precisely the false `archive` this design refuses to make.

**Two properties of that rule set are decisions in their own right.**

**`open` is the default.** A session reaches `archive` only by positively saying it
finished. Measured against hand-labelled sessions, the cue rules never produced a false
`archive` but caught only about half the genuinely finished ones. That is the right
direction to be wrong in: a false `archive` buries a loop the tool exists to surface,
while a false `open` only lengthens a list that is sorted by recency anyway.

**Conflicts resolve at sentence granularity, and inside a sentence an open cue always
beats a close cue.** Two real closing paragraphs forced both halves of that. "Say the
word and I'll remove it. Nothing is blocking; safe to close" is finished, and "you're
safe to exit … the two threads waiting for you are" is not — no fixed precedence between
the families gets both right, but *the last sentence carrying a cue* does. Then a third
broke a pure character-offset reading: "**Needs you** (nothing blocking, all tracked):
the #146 decision" puts the close cue inside a parenthetical of the very sentence that
hands work back, and is later in the string. Within one sentence, position means nothing
and the asymmetry decides.

## Consequences

**Most sessions land in `open/`, and that is the finding rather than a defect.**
Agentic sessions do overwhelmingly end with something put to the human. A split that
came out balanced would be a split that was lying. `archive/` is deliberately the
smaller, higher-precision set.

Because that makes `open/` large, two things carry the load instead: recency ordering,
and a `confidence` field. A session that is open *only because nothing said otherwise*
is marked as such, in the digest and in `ol ls --confidence high`. A classifier that hid
which of the two it did would be claiming knowledge it does not have.

Every verdict carries the rule that fired and the cues it saw, so a reader can disagree
with it. That is not politeness; a classification whose grounds are not shown is an
assertion, and openloops does not make assertions about sessions.

## Confirmation

- No module in the package reads a process list, a pid, or a liveness file.
- A test asserts each of the six rules, and that a structural signal outranks the text.
- A test asserts the last cue-bearing sentence decides, and that inside one sentence an
  open cue beats a close cue — with all three real examples above as cases.
- A test asserts a recap that predates the closing turn is ignored.
- A regression test holds the one real false `archive` this rule set ever produced: a
  session that said *"Nothing further is running. The one thing that still needs you is
  #55"*. The close cue is earlier, so latest-cue-wins saves it — but only once the defer
  vocabulary was widened to see the second half at all.
