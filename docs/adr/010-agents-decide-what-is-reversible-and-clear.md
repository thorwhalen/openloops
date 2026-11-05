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

**1. Decide and record (the `needs-human` rule).** When the decision is **reversible by one `git revert`** (or nothing has landed yet), has a **clear recommendation** (stated in the issue or its comments, an ADR, or the owner's standing preferences, with a reason), is **inside the task the agent was given**, and **overturns nobody's recorded decision**, the agent does not file a `manual-task`. It decides, records the choice in an `agent-decided` issue in the affected repo (what, why, the alternatives, a `**Reverse:**` line that is `git revert <sha>` or `none: nothing landed`, a veto date three days out), and carries on. The issue is a card on the phone board whose two options, *Keep* and *Veto*, are answer buttons on the card, with the Reverse line shown beside them so the owner never vetoes blind. Either tap is the receiver's usual `answer` event. Keep: the receiver comments and closes the issue, no worker. Veto: the receiver dispatches a fixed veto brief; the worker checks the issue is still labelled `agent-decided` **and** was opened by the owner's own login (a label alone proves nothing), then never runs the Reverse line as written: it takes the sha alone, checks it is a commit on the default branch, and runs `git revert --no-edit <sha>` itself. A `none: nothing landed` line, when something did land for the issue, or a line in any other form, makes it run nothing, file a `manual-task` and leave the issue open. The veto brief is always sent alone to a fresh worker, never batched, and any answer on the card other than Keep or Veto is refused. The agent records the decision once its commit has landed, so the Reverse line can name it. Irreversible, costly, outward-facing, security-relevant and spend-bearing choices are never eligible, whatever the recommendation.

**2. A deep decider for decisions with no recommendation.** A subagent reads the decision and the repository's own record, thinks it through, and puts the result on the board's decision desk: the option it would pick, starred, with its reasoning, or the trade-offs when only the owner can settle it. **It decides nothing**: the owner's tap is the decision, exactly as for any desk question, and nothing reaches GitHub or a worker without it. Everything the decider reads is data; a stranger's text on a public repo is never the owner's preference.

Two further designs were considered and set aside as unsafe or unsupported today: posting a proposal automatically once a veto window ends with no tap, and asking the owner input questions before proposing. The first would let evidence a stranger wrote in a public issue trigger a post and a worker with no owner event; the second collides with the board page, which marks a whole task answered on any answer and posts that answer on the issue. Both need the page to carry a question id and the task list to carry who wrote each issue (author and association), which `gh search` can supply.

## Consequences

- No new code path writes to GitHub. The receiver procedure gains one row (an `answer` on an `agent-decided` issue) and one fixed brief (the veto); both ride the existing `answer` event, comment marker and dispatch. The page's task card now shows a task's own options as answer buttons, which also fixes "Do what's recommended" sending an answer that was not one of the options.
- **An `agent-decided` issue is a record, not an obligation.** The decision stands from the moment it is recorded; the open issue is only the handle a veto needs, so it is not `manual-task`, `ol owed` does not count it, and an unanswered one costs nothing but an open issue. What it displaces is the `manual-task` issue that decision would otherwise have been: the owed list gets shorter, and no second owed list appears.
- `import openloops` still never reaches the network or calls a model. The deep decider and the receiver are procedures in markdown skills (ADR-008).
- The cost is the owner's trust: an agent now makes small calls unprompted. The bound is the eligibility test above, and the owner's Keep or Veto tap (the veto date is a prompt to look, not a deadline: nothing happens when it passes), and the record is a query away (`gh search issues --label agent-decided`).
- Decisions the owner reversed are visible as vetoes, which is the evidence for tightening or loosening the eligibility test later.

## Confirmation

- `tests/test_skills.py` asserts the shipped `needs-human` skill carries the eligibility test and the `agent-decided` label, that its description sends agents into it rather than past it, that both it and the receiver restrict a veto to a checked author and a `git revert`, and that the phone-board skill ships the deep-decider brief.
- `tests/test_board.py` asserts a card's own options are its answer buttons.
- `tests/test_tasks.py` asserts the board gathers `agent-decided` issues by label (also through `ol board-gather --all-kinds`) and shows the Reverse and Veto-by lines on the card.
