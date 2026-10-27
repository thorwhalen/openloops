---
status: accepted
date: 2026-10-27
---

# ADR-008 — The phone board's write side lives in a skill, not in openloops code

## Context

The phone task board turns the owner's open items into a page they can act on from a phone: tap Done, answer a decision, ask an agent to do something. Every one of those taps is meant to land somewhere real: a comment on the issue, the issue closed, a worker session dispatched to implement the decision.

openloops has two standing invariants that this pushes against. Its code never writes to GitHub (`ol owed` never closes an issue even when its own predicate says the ask is done, ADR-004 and the obligations module), and it never calls a model. A board whose events nobody acts on is a to-do list with extra steps; a board whose events openloops acts on breaks both invariants at once, since deciding what an answer means for an issue, and briefing a worker, are judgement calls.

## Decision

**Split along the invariant.** openloops code does the read side, deterministically:

- `gather` (`ol board-gather`): sweep owners with `gh search`, read-only;
- `classify` (`ol board-classify`): a heuristic classifier with no model, plus a merge for richer records;
- `build_board` (`ol board-build`): write the page and its data files into a directory the caller names.

The write side is a **procedure a Claude session follows**, shipped as the `openloops-phone-board` skill with its `references/receiver.md`: read the board's outbox, claim each event with a receipt, post idempotent comments carrying a hidden marker, close only open issues (never PRs, never in read-only organisations), dispatch one worker per repository under a resource gate, and report. The page and the receiver share a persistence contract (immutable `outbox/<eventId>` events written only by the page, `receipts/<eventId>` written only by the receiver) documented at the top of the page's script.

The richer classifier follows the same split: the classifier brief is shipped markdown a subagent reads, producing records in the `Task` schema that `ol board-classify --enriched` merges. The schema is defined once, in `openloops.tasks`.

## Consequences

- `import openloops` still cannot write to GitHub or call a model; nothing in the package's code changes that, and a reviewer can check it by grepping for `gh issue close`, `gh issue comment` or an API client.
- The write side improves without a release of code: the receiver procedure is markdown, so tightening a rule is a skill edit. The cost is that it is followed, not executed, so its safety rules are stated as rules (data never instructions, `--body-file`, read-only organisations) and the receiver must be a session the owner trusts.
- The board's data (titles from private repositories) is written only where the caller says, never into the package or the repository.
- A board built by the heuristic alone is usable but coarse; the brief is the path to a good one, and it costs model calls the owner's session makes, not openloops.
