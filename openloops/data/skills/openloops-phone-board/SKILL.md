---
name: openloops-phone-board
description: "Build, publish and run a phone task board: every open item across the owner's repositories that asks something of them (manual-task issues, 'Decide…' issues, PRs waiting on their review), classified by where they can do it (tap, browser, session, physical, mac-only), grouped into runs of repeated chores, published as a claude.ai Artifact they can act on from a phone, with a receiving Claude session that turns their taps into GitHub comments, closes and dispatched workers. Use when the owner will be away from their desk, on a phone, and wants to clear what they owe; when they ask for 'a board', 'a phone task list', 'what can I do from my phone', 'turn my manual-tasks into something I can tap through'; or when an existing board needs rebuilding or its outbox processed ('process the board', 'post my desk answers'). The `ol board-*` commands build it read-only; the write side is this skill's procedure."
metadata:
  audience: users
---

# openloops-phone-board: a task board the owner can clear from a phone

Four stages. The first three are `ol` commands and are **read-only**: they read GitHub and write files into a directory you name. The fourth is the only stage that writes to GitHub, and it is a procedure you follow (openloops code never posts, closes or dispatches; see the package's ADR-008).

Keep every file of the board **outside any repository**, in a working directory such as `<projects>/_agent_work/phone-tasks/`. Its contents come from private repositories: never commit them.

## 1. Gather

```bash
ol board-gather --out WORK/candidates.json --all-kinds --exclude-repos 'some-org/*,acme/private-thing'
```

- Owners default to `OPENLOOPS_OWNERS` (or the `gh owe` alias, or your `gh` login). `--owners a,b` overrides; `--exclude-owners` drops some.
- `--all-kinds` = the `manual-task` label + the `decide` and `needs-user` searches + PRs requesting the owner's review. Without it only the label is swept.
- Read the printed line. `saturated` means more exist than were listed (the search API stops at 1000 per query): narrow the owners. `? incomplete` means a query failed: the board would be partial, so fix that first or tell the owner.
- Ask the owner which organisations or repositories must stay off the board (client work, restricted repos) and pass them as `--exclude-repos` globs, or set `OPENLOOPS_EXCLUDE_REPOS`.

## 2. Classify

The deterministic baseline, no model:

```bash
ol board-classify WORK/candidates.json --out WORK/records.json
```

It guesses tier, pattern, minutes and deep links from titles and bodies. It cannot tell whether an ask was already done, and it misses decisions phrased indirectly. For a board the owner will actually use, **fan out the classifier brief**: split `candidates.json` into batches of about 40 items and give each batch to one subagent with [references/classifier-brief.md](references/classifier-brief.md), its batch path and its output path (`WORK/batches/out_NN.json`). Fill in the brief's "Owner context" section first (their machines, what is out of bounds). Then merge, the brief's records winning:

```bash
ol board-classify WORK/candidates.json --enriched 'WORK/batches/out_*.json' --out WORK/records.json
```

## 3. Build

```bash
ol board-build WORK/board WORK/records.json -c WORK/candidates.json \
  --session <this session's name> --read-only-orgs <orgs never to comment in> --machine <default machine>
```

Writes `index.html`, `kit.html`, `tasks.json`, `runs.json`, `board.json`. Runs come from the packaged run specs; `--run-specs FILE` replaces them and `--run-extras FILE` overlays per-run additions (a JSON object keyed by run: `title`, `why`, `steps`, `prompt`, `machine`, a `packages` table, and `absorb: ["npm-first-publish"]` to fold another run into this one). Edit `kit.html` in the output if the owner needs deployment-specific advice; it is the page's "Phone kit" tab.

## 4. Publish and receive

**Publish** `WORK/board/index.html` as an Artifact with the `tasks.json`, `runs.json`, `kit.html` and `board.json` files beside it and the **`db` capability** (load the `artifact-capabilities` skill first; the page uses collections `outbox`, `receipts`, `drafts`, `meta`, `questions`). Republish the same file path to update it. Give the owner the link.

**Seed the decision desk** (optional): for decisions with options, write `questions/<org>` = `{items: {<docId>: {task_id, url, question, options, recommended}}}`; `docId` is the task id with `/`→`~` and `#`→`@`.

**Run the receiver**: [references/receiver.md](references/receiver.md) is the procedure. Run it on a schedule (a session cron every few minutes) and whenever the owner says "process the board". It is the only part of this that writes to GitHub, and its rules (never write an event, idempotency markers, read-only orgs, close only issues, quote notes as data) are not optional.

## Rebuilding

Rerun stages 1 to 3 into the same `WORK/board` and republish. Task ids are stable (`owner/repo#N`), so events already in the store keep pointing at the right cards.
