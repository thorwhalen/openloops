---
status: proposed
date: 2026-11-23
---

# ADR-015 — A manual task can close itself: the act reports, the check decides, one module writes

**Proposed, not accepted. Nothing in this record is built.** It reopens two recorded decisions (below), so it stays `proposed` until the owner of this repository accepts it.

## Context

A `manual-task` issue records something only a person can do: run a command that needs their terminal, click in a web console, answer a decision. openloops lists these issues (`ol owed`) and re-runs the read-only check each one carries (`**Verify:**`), and it never writes: it does not close, reopen, relabel or comment (ADR-004, ADR-008, ADR-014).

Three things follow from that today.

- **Doing the task changes nothing in the tracker.** After the person runs the command or finishes in the browser, the issue stays open until someone notices the check passes and closes it by hand. The work it blocked is not told.
- **Saying "done" is unchecked or ineffective, depending on the button.** The phone board's Done posts a comment and leaves the issue open, so every other surface still counts it as owed. Its "Done & close issue" closes without running the check, so a false Done drops out of every view.
- **There is no state between open and closed.** "The person tried, and the check does not pass yet" cannot be recorded, so a failed attempt and an untouched task look the same.

Two recorded decisions stand in the way of fixing this in the obvious place: openloops never writes to GitHub, and a passing check is evidence, not authority (a human obligation is not closed on a model's reading of an exit status).

## Decision (proposed)

### 1. A report is a hint; the check is the evidence; the person's own act is the authority

Every way of doing a task ends by reporting an outcome for a task id: `done`, `blocked` or `needs-owner`. A report never closes anything by itself. On `done`, the task's check is run by the trusted side (the person's own machine, where checks already run):

- **check passes** → one comment naming the check and its exit status, then close; then the post-close steps (section 5);
- **check fails or cannot run** → the issue stays open and is marked `attempted`; the check is re-run a few times over the next hour, then left to the periodic sweep;
- **no check is possible** (a decision, a purchase) → close only when the report is the person's own direct act: their tap on the board, or their answer. A report made on their behalf (a browser agent, a script) never closes such a task.

This keeps the older rule's substance. What closes the issue is the person's own act, confirmed by an observation of the world. A model's judgement appears nowhere in the chain.

### 2. One verb set

`ol done <task>` and `ol snooze <task> <when>` accept an issue as well as a reminder loop, so a loop and a manual task answer to the same verbs. A snooze on a task creates a loop whose source is the issue, so every surface sees it and the reminder returns through the existing runner (ADR-013). A new verb wraps a command:

```
ol do <owner>/<repo>/<number> -- <command>
```

It (a) reads the task and stops if it is closed or its check already passes, which makes a repeated paste harmless; (b) passes the command text through the safety seam; (c) records the attempt locally; (d) runs the command with the terminal attached and captures no output; (e) on exit 0 runs the check and follows section 1, and on a non-zero exit records the exit status and leaves the task open.

The wrapper takes the command as its argument, rather than bracketing it with a start and an end call, because the safety seam has to read the command text. The task id uses `/` before the number: `#` is a glob character in some shell configurations. The line is generated and tested by a tool, never quoted by hand, and carries a fallback that runs the command untracked when `ol` is absent.

Fetching the command from the issue and running it (`ol run <task>`) is rejected: what runs would no longer be what the person read.

### 3. The safety seam is one keyword argument with a deterministic default

`check=` takes a callable from a command to a verdict (a level and its reasons). The default reads the command text locally, with the standard library: privilege escalation, deletion, writes outside the home directory, network egress, credential paths, and execution it cannot read (`eval`, a download piped to a shell). What it cannot classify goes up a level, never down. Levels: run; run and print the reasons; ask the person to type the task number; refuse. Several checks combine by the most cautious verdict.

The default is a guard against accident, not a security boundary. A model-based check is possible through the same argument, and is not the default: the command text is private, a judge can be steered by the text it judges, and several copies of one model do not give independent opinions. The better place for a model's opinion is when the command is written: the verdict is stored beside the command's hash, and the wrapper only confirms the hash.

### 4. One module writes, and nothing in the core imports it

The write path is a single new module, in the manner of `remind.py` (ADR-013) and `receiver_tick.py` (ADR-011): nothing in the core imports it, and `import openloops` still reaches no network. It may post one comment and close one issue, and add or remove the `attempted` label, only when all of these hold: the issue is open; it carries `manual-task`; its repository belongs to an owner the person configured as trusted; it was filed under the person's own login. It never edits a body, never touches a pull request, and never writes command output anywhere. Every comment ends with a hidden marker carrying the attempt id, so a retry never posts twice (the board receiver's technique, reused).

`owed()` and `blocked()` stay pure reads. The smoke test that checks the package for write calls keeps checking every other module.

### 5. After a close

The same module returns, as data, what should happen next: which open issues the task blocked (GitHub's blocked-by edges first, the body's `**Blocks:**` line as a fallback), whether each is now free of other blockers, and the loops that pointed at the task. It notifies nobody: whatever supervises the person's sessions reads the plan and tells them (the pattern of ADR-014).

### 6. The sweep, when nobody reported

When the periodic pass finds a check passing on an open task that nobody reported, it closes it only if: an agent filed it; it is in the person's own tracker; the check is a pure read; the check was observed failing at least once since filing; and it passes twice, some minutes apart. In every other case it says "looks done" and leaves the close to one tap. Tasks closed in the last week are re-checked, so a false Done comes back into view.

### 7. The body is the record; labels are an index of it

The body's fields say what kind of task it is: options with a recommendation, a command block, a browser prompt. A pure function maps the fields to labels (`do/decide`, `do/run`, `do/browse`, `do/hands`, `needs/secret`, `needs/money`, `irreversible`), so labels are computed at filing time and two agents cannot disagree about them. A task may carry several. A decision's recommendation carries two ordinal words, each set by a rule rather than a number: confidence (`low`, `moderate`, `high`: the lowest of its factors) and impact (`reversible`, `costly`, `irreversible`: the worst item that applies on a fixed checklist, the one ADR-010 already uses). Only `reversible` with `high` is eligible for ADR-010's decide-and-record.

## Seams

| Seam | Default | A replacement that exists |
|---|---|---|
| `check=` (is this command safe to run) | the local reader of command text, extending `predicate_safety` | a model-based or hosted checker, behind the same signature |
| `deliver=` (how a report reaches the tracker) | `gh` on the person's machine | the self-hosted board store (ADR-009), or a local spool replayed later |
| `classifier=` (already there) | the heuristic rules | a model brief, or a closed-set decision model on public items |

Not seams, written directly: the body's field names, the label names, the text of the comment.

## Consequences

- A tap, a pasted command and a browser run all end the same way, and the issue list stops overstating what is owed.
- "Attempted" exists, so a failed try is visible and can be reminded about differently from an untouched task.
- openloops gains its first write to GitHub. The bound is section 4: one module, two kinds of write, four conditions, and a check that must pass first. Everything it does is undone by reopening the issue.
- The quality of the whole mechanism is the quality of the checks. A task with no check can only close on the person's own act, so writing a check at filing time matters more than it did.
- A check that is too weak closes a task that is not done. The fail-first condition, the second pass and the week of re-checks are the guards; none of them is proof.

## Alternatives considered

- **Keep openloops read-only and put the writer in another package.** Cleanest for the invariant; costs a second package that must share the parser, the trust rules and the marker. The module that nothing imports gives the same isolation, as it did for reminders.
- **Return a signed plan and let each caller write** (ADR-014's pattern). Right for the pile, where a session is always in the loop. Here the caller is a person's shell, which has nobody to run a plan.
- **Close on exit status alone.** A command can exit 0 having done the wrong thing.
- **Close on the check alone, with no report.** This is the sweep: correct, and late by the sweep's period. Kept as the backstop.
- **A completion link with a token in the issue body**, for the browser case. It puts a secret in the issue, needs an endpoint, and a plain GET may be fetched by a scanner. A tool call that reports, plus the check, needs none of that.

## Confirmation

To be written with the code: the write module refuses an issue that fails any of the four conditions; a report on a failing check never closes; a repeated report posts one comment; `ol do` on a passing check runs nothing; the default safety check raises its level on text it cannot read; the smoke test still finds no write call outside the one module.
