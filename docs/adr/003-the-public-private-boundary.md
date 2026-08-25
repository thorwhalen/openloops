---
status: accepted
date: 2026-08-25
---

# ADR-003 — The public/private boundary, and the egress rule

## Context

openloops reads transcripts. Transcripts are the highest-entropy secret source on a
developer's machine: pasted tokens, `.env` contents, tracebacks full of absolute paths,
the names of private repositories and the shape of somebody's working life.

Two boundaries follow from that, and they are different problems.

The first is **this repository's own**. The design work that produced openloops happened
in a private repository dense with material that must not be published. Making that
repository public would have required a history rewrite and a sweep of every issue —
"flip it public later" was never available, so a separate public repository was always
going to exist.

The second is **the user's**. A digest store can be a synced git repository, which makes
a written digest an export surface. The moment to apply discipline is before the first
byte is written, not before the first push.

## Options

**Build privately, extract the public part later.** No egress discipline needed while
moving fast — but the extraction boundary *is* this product's principal seam, so
building private-first bakes one machine's paths into the core and then requires digging
them out.

**One repository, private material gitignored.** Fewest moving parts, and the protection
is a `.gitignore`, which is advisory.

**Split by what may be published, and make the rule mechanical.** A repository wall is
the only mechanical form the first boundary can take; a function that runs before every
write is the only mechanical form the second can take.

## Decision

**Two rules, one implementation.**

**The repository boundary.** The design repository stays private, permanently. This
public repository holds the package, its documentation, and synthetic-fixture tests.
Nothing here may carry an absolute local path, a real repository or session identifier,
or any content lifted from a transcript. That binds code, tests, documentation, issues
and commit messages alike, and it is enforced by a test that scans every file git would
publish.

**The user boundary.** Every digest passes through the same scrubber before it is
written. Home paths are **rewritten**: this machine's becomes `~`, and *any other* — an
ssh'd server's, a colleague's, a CI runner's — becomes `~other`, keeping the tail of the
path and dropping the identity. Credential-shaped text **raises**, and is never silently
redacted: the session is skipped, the run says so and exits non-zero, and the error names
the pattern class and offset without ever quoting the match.

Two shapes were missed in the first implementation and both mattered. Claude Code encodes
a working directory into a directory name by turning separators into dashes, so a home
path also appears in a dashed form that no path pattern matched. And rewriting only
`$HOME` left every *foreign* home intact — which is most of them, for anyone who works
over ssh. Both are covered, and the scrubber now asserts its own postcondition rather
than trusting that its rewrite was exhaustive.

The asymmetry is the decision. A rewritten path is still readable. A silently redacted
secret teaches nobody that a secret was there, and leaves a store that is *probably*
clean — which is not a property anyone can act on.

## Consequences

**This repository can never accept a bug report containing a real transcript.** That is
a genuine support cost: reproductions must be synthetic or redacted. It is accepted, and
it is the same cost any tool that reads private data pays; paying it visibly is better
than discovering later that a helpful user pasted a session log containing a token.

A false positive on the credential patterns costs one skipped digest and a loud message.
That is the right price for never writing a secret into a store that may be synced.

## Confirmation

- `tests/test_egress_repo.py` scans every file git would publish and fails on any
  absolute home path or credential-shaped text — including files not yet committed. The
  scrubber's own module obeys the rule too: it spells the home roots in split literals
  so that it carries none of them as a matchable string.
- A test proves that scan actually fires, so a check that silently stopped working
  cannot pass as a clean bill of health.
- A digest containing credential-shaped text raises rather than being written.
