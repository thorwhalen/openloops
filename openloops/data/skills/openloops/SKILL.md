---
name: openloops
description: >-
  Answer "what is being done, and what needs my attention?" across every coding
  session and every repository, by running the `ol` command and synthesising its
  answers rather than pasting them. Use when the user asks what needs their
  attention, what their agents have been doing or left unfinished, what they
  missed while they were away, what they still owe an agent, what is blocked or
  waiting on another repo, or what quietly became unblocked and nobody noticed.
  Triggers on: 'what needs my attention', 'anything waiting on me', 'catch me
  up', 'what did I miss', 'where are we', 'status across my sessions', 'what are
  my agents doing', 'what did my sessions leave open', 'what do I owe', 'what am
  I blocked on', 'what can I start now', 'give me the overview', 'morning
  briefing', 'what should I look at first', 'is anything stuck'. Also use before
  planning a day's work, so the plan starts from what is outstanding rather than
  from memory. Read-only: it never closes, reopens or relabels anything.
metadata:
  audience: users
---

# openloops: what is being done, and what needs your attention

An **open loop** is a commitment that outlived the session that made it and that
nothing is watching. The `ol` command finds them and re-checks them. **Gathering the
facts is its job. The synthesis is yours** — and a raw paste of three command outputs
is a failure of this skill, not a use of it.

If `ol` is not on the PATH, say so and stop rather than guessing: `pip install
openloops`. Two of the three commands also need the GitHub CLI (`gh`) logged in.

## The three commands, and which question each one answers

| The user is asking | Run | It reads | Cost |
|---|---|---|---|
| what were my sessions doing / what did they leave open? | `ol` | this machine's session transcripts | a second or two |
| what do I still owe my agents? | `ol owed` | open `manual-task` issues, **re-running each one's check** | tens of seconds |
| what is waiting on another repo — and what is not any more? | `ol blocked` | GitHub `blocked_by` edges, resolved | tens of seconds |

**`ol owed` and `ol blocked` are slow on purpose.** They are not listing a cache; they
are asking the world again, one shell predicate or one API call per row. That is the
entire reason to prefer them over a `gh search issues` one-liner — and the reason not
to run them reflexively.

So: **match the command to the question.**

- "what were my sessions doing", "catch me up on yesterday" → `ol` alone answers what was
  *done*. Do not spend a minute on `owed` and `blocked` for that — but then do not claim
  anything about obligations either, and say which you ran (see below).
- "what needs my attention", "anything waiting on me", "what should I look at first",
  a morning briefing, anything about obligations → run all three.
- "what can I start now", "what is unblocked" → `ol blocked` is the one that answers it.

Useful narrowings, when the full sweep is more than was asked for:

```bash
ol ls --state all             # every digest, not just the open ones
ol ls --confidence high       # drop sessions open only because nothing said otherwise
ol show 2b1f                  # one session digest in full, by id or a unique prefix
ol owed --no-verify           # list obligations without executing anything (see below)
ol blocked --repos owner/name,owner/other   # audit exactly these repos
ol status                     # where the digests are, and how stale the cache is
```

## `?` means nothing was checked. Never round it away.

`ol owed` and `ol blocked` each report **three** states, and the third is `unknown`,
printed `?`. It is not a rounding error and it is not a small `open`.

`?` means *the check did not happen*: no `gh`, no network, a timeout, an owner the user
never marked as trusted, a predicate that would not parse. **An agent that reports
"nothing owed" when rows read `?` has told the exact lie this package exists to
prevent.** A clean board the user did not earn is worse than no board, because they
stop looking.

Two shapes to recognise, and neither may be softened:

```
?      23d  acme/widget#9              Doctests depend on a live third-party HTTP fetch
          verify: python3 -m pytest -q --doctest-modules --pyargs widget.remote
                  -> the predicate timed out after 20s
```

One row could not be checked. Report it as unchecked, with the reason, in the bucket it
would land in if it were still open.

```
owed ?  could not check - gh: not logged in
```

The **listing itself** failed, so there are no rows at all. Say "I could not check what
you owe — `gh` is not logged in." Never "you owe nothing", never "nothing came back",
never silence. Say the same for `blocked ?`.

When you write the summary, carry the count of unchecked rows into it explicitly:
"3 need you, 1 is free to start, **2 could not be checked**." If everything checked
cleanly, say that too — "nothing unchecked" is information.

One disambiguation, because the character appears twice: the `?` in the second column
of plain `ol` output is **not** this. There it means *low confidence* — the session
never said it was finished, so it stayed open by default. The session-digest half
checks nothing against the world, so it has nothing to be unable to check.

## The five verdicts, and what each one means

| Printed | Command | Means |
|---|---|---|
| `open` | `ol owed` | no check at all, or the check ran and said not done |
| `done` | `ol owed` | the check returned 0 — the ask is finished, the issue is merely still open |
| `ready` | `ol blocked` | every blocker has closed. The work is free and nobody has been told |
| `waits` | `ol blocked` | at least one blocker is still open; the row names it, with its repo |
| `?` | either | nothing was checked. Not a small `open`, not a quiet `done` |

## Synthesise: three buckets, in this order

The order is the order that matters to a human, not the order the commands ran in.
Lead with what costs them something to not know.

### 1. Needs you now

Anything the user personally has to do or decide, and nothing else.

- `ol owed` rows printed `open` — an agent is blocked on them and still is.
- Any row whose ask is a decision (`Decide whether…`, `Decision needed:`) — those never
  discharge on their own; a predicate cannot observe a judgement.
- `?` rows from either command, marked as unchecked, never as clean.

Give each one: what it is, which repo and issue, how long it has been waiting, and — if
you can see it — the single next action. Age is the argument: `23d` on a one-command ask
is the line that makes someone act.

### 2. Free to proceed

`ol blocked` rows printed `ready`: every blocker has closed and **nobody was told**.
This is the cheapest win on the page and the row the command exists for, so it gets its
own bucket even when there is only one. Say how long it has been free — `free for 5d,
and nothing has said so` — and name the workaround it unblocks removing.

Also belongs here: an `ol owed` row printed `done`. The predicate returned 0, so the ask
is finished and the issue is merely still open. Report it, note that you did not close
it, and let the user close it.

### 3. In flight

What the sessions were actually doing — the `ol` half. Group by project, not by session:
five sessions in one repo are one line of context, not five. Prefer `--confidence high`
rows when the list is long; the low-confidence ones are open only because nothing in
them said otherwise, and treating them as live work invents urgency.

`waits` rows belong here too, one line each, naming the foreign repo. They are context,
not an action: the user cannot do anything about them, which is the point of the state.

**One exception, and it is worth looking for.** If a `waits` row's blocker is itself
something the user owes — the blocking issue is one of the `open` rows from `ol owed` —
then the whole chain is waiting on *them*, and it belongs in **needs you now** instead,
with the chain spelled out. That is a person waiting on themselves without knowing it,
and neither command can see it alone; you are the only thing that reads both.

**An empty bucket means one of two things, and you must say which.** If you ran the
command and it returned nothing, say so: *"nothing is waiting on another repo"* — that is
an answer. If you did not run the command, you do not know, and saying *"nothing is
waiting"* is a lie of exactly the kind this whole tool exists to prevent. Say *"I did not
check what is blocked"* instead, and offer to.

This is not hypothetical. Answering "catch me up" with `ol` alone and then adding
"nothing is waiting on another repo" is wrong the moment a blocker has quietly closed —
which is the single case `ol blocked` was built for. **Close every summary by naming which
of the three you ran**, in one short line: *"read from `ol` and `ol owed`; I did not run
`ol blocked`."* One clause, and it makes the difference between a report and a guess.

Do not print an empty heading.

### What the summary is not

- Not a paste. If your answer contains a block of `ol` output verbatim, you have handed
  the user the thing they asked you to read for them.
- Not every row. Twenty open loops become three lines and an offer: "…and 14 more
  sessions with no open ask — say the word and I will list them."
- Not a re-ranking by your own taste. `ready` rows and `open` obligations are the
  user's, in their repos; you order them by age and blast radius, not by what you find
  interesting.

Keep the whole thing short enough to read standing up. Offer the detail; do not deliver
it unasked.

## `ol owed` executes shell out of issue bodies. Know this before you run it.

Each `manual-task` issue carries its own check, as a shell command whose exit status is
the answer:

```
**Verify:** `gh secret list --repo OWNER/REPO --json name -q '.[].name' | grep -qx PYPI_PASSWORD`
```

Running `ol owed` **executes that text**. It is bounded — only for repository owners the
user configured as trusted, always time-limited, and the command is printed next to its
own verdict so nothing runs invisibly — but it is a real capability and it deserves a
sentence before it happens.

Use `ol owed --no-verify` when:

- the user has just added an owner, or a repo whose issues neither of you has read;
- you are on someone else's machine, or in an environment where running arbitrary
  commands is not yours to authorise;
- the user only wants the list, not the re-check.

Then say what you did: **every predicate row reads `?` under `--no-verify`**, because
nothing was checked. That is the honest reading, not a degraded one — but it must not be
reported as "nothing owed".

## Never write. A passing predicate is evidence, not authority.

openloops never writes to GitHub, and neither do you while using it. Do not close,
reopen, relabel, comment on, or edit any issue on the strength of anything `ol` printed
— including a `done` row whose predicate returned 0.

The reason is not caution, it is arithmetic: the label **is** the record. There is no
local database to disagree with, so an issue closed on a model's reading of a shell exit
status is a record nobody can audit back. Report it, quote the predicate and its exit
status, and let the human close it. If they ask you to close it, that is their
instruction and a different thing entirely.

## Setting up the fleet — a partial owner list is a partial count

`ol owed` and `ol blocked` search *someone's* repositories, and they resolve whose from
three sources, first one wins:

1. **`OPENLOOPS_OWNERS`** — comma- or space-separated. The explicit answer:
   `export OPENLOOPS_OWNERS="acme widgets"`.
2. **A `gh owe` alias**, if one is installed — the owners named by its `--owner` flags.
   A fleet is usually already written down there once, and disagreeing with the thing
   the human actually types is how a count goes quietly wrong.
3. **The login `gh` is authenticated as** — the fallback, and the one that bites.

Every result prints the owners it used:

```
  owners: acme  |  predicates: 3 of 4
```

**Read that line every time.** If the user works across an organisation and it says only
their personal login, the count is silently partial — clean-looking, and wrong. Say so,
and offer the fix:

```bash
export OPENLOOPS_OWNERS="personal-login some-org another-org"   # in the shell profile
ol owed --owners personal-login,some-org                        # or just this once
```

To find the owners worth naming: `gh api user --jq .login` for the login, and
`gh api user/orgs --jq '.[].login'` for the organisations that account can see. Confirm
the list with the user rather than assuming every org they belong to is one they want
counted.

Two more lines on the same header deserve a glance:

- `predicates: 3 of 4` — one obligation carries no check and can therefore never be
  observed as done. Worth mentioning once, not every time.
- `TRUNCATED` — the result set hit its cap, so **the count is a floor**. Re-run with a
  larger `--limit` before quoting a number.

## When to hand this to a subagent

In a long-lived session — the one the user keeps open all day to ask "what needs my
attention?" — running the sweep inline fills the context with command output that is
stale ten minutes later.

If an `openloops-sweep` subagent is available, dispatch to it: it runs the three
commands in a fresh context and returns only the synthesis. Ask it again later and it
costs the same, no matter how long the conversation has run.

Inline is right for a one-off question, or when the user is going to want to drill into
a specific row immediately afterwards.
