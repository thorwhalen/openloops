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

**1. Decide and record (the `needs-human` rule).** When the decision is **reversible**, has a **clear recommendation** (stated in the issue or its comments, an ADR, or the owner's standing preferences, with a reason), is **inside the task the agent was given**, and **overturns nobody's recorded decision**, the agent does not file a `manual-task`. It decides, records the choice in an `agent-decided` issue in the affected repo (what, why, the alternatives, the exact way to reverse it, a veto date three days out), and carries on. The issue is a card on the phone board with two answers, *Keep* and *Veto*; a veto sends a worker to reverse it, keeping closes the issue. Irreversible, costly, outward-facing, security-relevant and spend-bearing choices are never eligible, whatever the recommendation.

**2. A deep decider for decisions with no recommendation.** A subagent reads the decision, thinks it through, and either asks the owner up to three one-tap questions on the board's decision desk or proposes an answer with its reasoning. A proposal appears on the desk with the agent's pick starred and its reasoning attached. **Nothing is posted to GitHub while the proposal stands unanswered, until its veto window ends.** If the owner taps any answer first, that answer is the decision, exactly as for any desk question. If the window ends untouched and the proposal is marked reversible, the receiver posts it as decided and dispatches the follow-up; if it is not marked reversible, it waits for a tap indefinitely.

## Consequences

- No new code path writes to GitHub: both flows reuse the receiver's existing `answer` action, comment marker and dispatch. The one new receiver duty is posting a *due proposal* once; it is idempotent through a marker derived from the proposal itself.
- `import openloops` still never reaches the network or calls a model. The deep decider and the receiver are procedures in markdown skills (ADR-008).
- The cost is the owner's trust: an agent now makes small calls unprompted. The bound is the eligibility test above plus the veto window, and the record is a query away (`gh search issues --label agent-decided`).
- Decisions the owner reversed are visible as vetoes, which is the evidence for tightening or loosening the eligibility test later.

## Confirmation

- `tests/test_skills.py` asserts the shipped `needs-human` skill carries the eligibility test and the `agent-decided` label, and that the phone-board skill ships the deep-decider brief.
- `tests/test_tasks.py` asserts the board gathers `agent-decided` issues by label.
