---
status: accepted
date: 2026-11-20
---

# ADR-014 — The pile: openloops reads and plans, the caller writes

## Context

The owner captures by voice into a *pile*: one GitHub issue per capture in a private repo, labelled `pile`. Emptying it (GTD's clarify step) turns each item into a loop, an idea, an issue in the repo that owns it, work handed to a session, or a drop with a reason. Each of those ends with a comment on the pile item, labels changed and, usually, the item closed. Three surfaces need to do it the same way: the `openloops-pile` skill in a Claude Code session, the `ol` command, and a voice connector (bosun) whose own tools already create issues and post comments behind a publication check.

Two things pull against each other. The surfaces should share one core, so the rules (a drop needs a reason, a public repo gets no private text, every write is signed) are code, not three paraphrases. And openloops never writes to GitHub (ADR-004, ADR-008); a smoke test checks the package for any write call.

The owner also wants every agent comment traceable: the agent's name and a link to its session, so an idea's development can be followed back to who did it and why.

## Decision

**openloops computes the plan; the caller carries it out.** `openloops.pile` reads the pile (`items`, `show`), proposes (`propose`, a model-free heuristic behind a `proposer=` seam), and for one decision the owner said yes to returns `plan(...)`: a list of steps as data (`remind`, `idea`, `create_issue`, `comment`, `labels`, `close`). The first step's result (an issue URL, a loop id, an idea id) fills the `{result}` placeholder in later steps. A Claude Code session runs the steps with `gh` (the skill maps each op to one command); bosun runs them with its own tools. This is ADR-008's split, applied to the pile.

**Every write the plan contains is signed**: `Agent: <name>` and, on a private repo, `Claude-Session: <url>` (or `Session: <address>` when there is no URL). The identity defaults to `OPENLOOPS_AGENT` and Claude Code's own session variables, and a plan with no name is refused. Only a private repo of the pile's owner counts as private (fail closed: public, internal, another owner's repo, or an unreadable visibility all count as public). A public destination gets the name alone in the signature, and an issue body that is only the text the caller wrote for it: no dictation, no pile link, no session link. The pile itself must be private, or nothing is planned. A plan refuses a second destination for an item that already records one (a half-run plan is finished, not repeated).

**Nudges, never action.** `nudge()` keeps one reminder coming (through the ADR-013 runner, at most one made per 24 h) while any item, on the pile or handed to a session, is older than a threshold, saying only the count and the oldest age. It reads the pile and writes only its own loop. `ol install-pile-nudge-job` runs it every six hours on macOS. No GitHub Action, no webhook.

## Consequences

- `import openloops` still cannot write to GitHub, and the smoke test still holds; the plan is data any surface can execute.
- The rules live once, in `plan()`, and are tested there; the skill holds only the op-to-command table and the conversation (propose, one yes, act).
- A caller that executes a plan badly (skips the comment, drops the signature) is not prevented by code. The skill and the connector are where that is checked.
- The nudge depends on `gh` and on correspond in the job's environment, like the reminder tick.
