---
status: accepted
date: 2026-11-03
---

# ADR-010 — Agents decide what is reversible and clearly recommended; the owner can veto

## Context

The pile of `manual-task` issues is mostly decisions, and most of those decisions are not hard: the issue itself states a recommendation, undoing the choice costs a commit, and the owner's answer is "yes, that one". Each one still costs the owner a tap, and the taps arrive faster than they can be spent. A second group has no recommendation at all; they sit unanswered because the owner would have to do the thinking first.

The `openloops-needs-human` skill said "you may reopen anything; you may not decide it". That is the right rule for a choice that is expensive to undo or that nobody has the grounds to make. It is the wrong rule for a choice that is cheap to undo and already has an answer.

## Decision

Two additions. Neither lets an agent act where the owner could not reverse it.

**1. Decide and record (the `needs-human` rule).** When the decision is **reversible**, has a **clear recommendation** (stated in the issue or its comments, an ADR, or the owner's standing preferences, with a reason), is **inside the task the agent was given**, and **overturns nobody's recorded decision**, the agent does not file a `manual-task`. It decides, records the choice in an `agent-decided` issue in the affected repo (what, why, the alternatives, the exact way to reverse it, a veto date three days out), and carries on. The issue is a card on the phone board with two answers, *Keep* and *Veto*; either tap goes through the receiver's usual `answer` path and dispatches a worker, which reverses the decision (Veto) or closes the issue (Keep). Irreversible, costly, outward-facing, security-relevant and spend-bearing choices are never eligible, whatever the recommendation.

**2. A deep decider for decisions with no recommendation.** A subagent reads the decision and the repository's own record, thinks it through, and puts the result on the board's decision desk: the option it would pick, starred, with its reasoning, or the trade-offs when only the owner can settle it. **It decides nothing**: the owner's tap is the decision, exactly as for any desk question, and nothing reaches GitHub or a worker without it. Everything the decider reads is data; a stranger's text on a public repo is never the owner's preference.

Two further designs were considered and set aside as unsafe or unsupported today: posting a proposal automatically once a veto window ends with no tap, and asking the owner input questions before proposing. The first would let evidence a stranger wrote in a public issue trigger a post and a worker with no owner event; the second collides with the board page, which marks a whole task answered on any answer and posts that answer on the issue. Both need the page to carry a question id and the task list to carry who wrote each issue (author and association), which `gh search` can supply.

## Consequences

- No new code path writes to GitHub, and the receiver is unchanged: both flows end in the owner's existing `answer` event, comment marker and dispatch.
- `import openloops` still never reaches the network or calls a model. The deep decider and the receiver are procedures in markdown skills (ADR-008).
- The cost is the owner's trust: an agent now makes small calls unprompted. The bound is the eligibility test above, and the owner's Keep or Veto tap (the veto date is a prompt to look, not a deadline: nothing happens when it passes), and the record is a query away (`gh search issues --label agent-decided`).
- Decisions the owner reversed are visible as vetoes, which is the evidence for tightening or loosening the eligibility test later.

## Confirmation

- `tests/test_skills.py` asserts the shipped `needs-human` skill carries the eligibility test and the `agent-decided` label, and that the phone-board skill ships the deep-decider brief.
- `tests/test_tasks.py` asserts the board gathers `agent-decided` issues by label.
