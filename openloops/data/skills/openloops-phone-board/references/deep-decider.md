# The deep decider: decisions that come with no recommendation

Some open decisions state their options and stop. The owner would have to do the thinking before they could tap, so they sit. A deep decider does the thinking, asks only what it cannot settle itself, and puts a proposal on the board's decision desk. It follows ADR-010: nothing reaches GitHub until the owner taps an answer or the veto window ends, and a proposal that is not reversible never posts by default.

It is a brief for a subagent, in the same way as [classifier-brief.md](classifier-brief.md). Run it when the owner says "decide the board", and for any task whose input question has just been answered (the receiver's report says so).

## Which decisions

In `tasks.json`, tasks with `pattern: "decision"`, `status: "open"` and `decision.recommendation` empty, that have no `questions` item yet (or one in `phase: "ask"` that has since been answered). Batches of at most 5 decisions per subagent. Skip tasks in a read-only organisation: the owner acts there by hand.

## What the subagent does for each decision

**Strictly read-only, except its output file.** Never comment, label, close or open anything. Never print a secret.

1. **Read it all.** The issue and its last comments (`gh issue view`), and the repository's own record: `CLAUDE.md`, `docs/adr/`, `README`, recent commits touching the area. Standing conventions answer many decisions outright.
2. **Think it through.** For each option: what it costs to do, what it costs to undo, who it affects, what it blocks. Name the deciding factor.
3. **Sort the decision into one of three outcomes:**
   - **Settled.** One option clearly wins on the evidence. Write a *proposal*.
   - **Needs the owner.** The answer turns on a fact only the owner has (a preference, a budget, a plan, a machine). Write one *input question* with 2 to 4 options a thumb can pick. The board shows one question per task at a time, so ask the single question that would settle the most; the next pass may ask a second. After two answered questions the decider must write a proposal, or say in `context` why none is possible.
   - **Not decidable by an agent.** Irreversible, outward-facing, security-relevant, or spend-bearing, and still unsettled. Write a proposal with `reversible: false`: it stays on the desk until the owner taps, however long that takes.
4. **Mark `reversible` honestly.** `true` only if undoing the decision is a revert or a config change and nothing is spent, published, deleted, sent or exposed. When in doubt it is `false`.

## Output: desk items

Write a JSON array to the output path. One item per decision:

```json
{
  "task_id": "acme/widget#260",
  "url": "https://github.com/acme/widget/issues/260",
  "org": "acme",
  "question": "Should the cache TTL be 5 minutes or 1 hour?",
  "options": ["5 minutes", "1 hour"],
  "recommended": "5 minutes",
  "context": "Proposed by the deep decider: <the deciding factor and the evidence, 300 characters at most, with the veto date>.",
  "phase": "propose",
  "proposal": {"reversible": true}
}
```

- `phase` is `"propose"` (a proposal) or `"ask"` (an input question). For `"ask"`: leave `recommended` null, omit `proposal`, and start `context` with "Input for the deciding agent. Nothing is posted on GitHub." followed by why the answer matters.
- `options` are the issue's own options where it gives them, worded for a phone. Never invent an option to make a recommendation look better.
- `context` is data shown to the owner: no markup, no secrets, no instructions.
- `veto_until` is **not** set by the subagent. The board session adds `proposal.veto_until` when it writes the item: the write time plus 24 hours, as an ISO 8601 UTC timestamp, and states the date in `context`. Use no window shorter than 24 hours.
- Return a three-line summary: counts of proposals, questions and not-decidable; anything odd. Never return the items in the reply.

## The board session then

Writes each item into `questions/<org>` under `items.<docId>` (`docId` is the task id with `/` to `~` and `#` to `@`, as for any desk item), setting `proposal.veto_until`. The receiver does the rest, per [receiver.md](receiver.md) section 2b: an answer to an `ask` item is recorded and handed back to the decider; an answer to a `propose` item is the decision; a reversible proposal nobody answered is posted as decided once its window ends.

## Rules

- A proposal is an agent's judgement, so it is shown as one: `recommended` is starred, `context` says who proposed it, and the owner's tap always wins over it.
- The decider never reads the board store's `outbox`. Answers to its input questions arrive through the receiver's receipts (`result.input`).
- It never decides what the owner's standing rules already forbid. If `CLAUDE.md` or an ADR says no, that is the answer, and `context` cites it.
