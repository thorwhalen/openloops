# openloops

An **open loop** is a commitment that outlived the session that made it and that
nothing is watching. An agent said it would come back to something and the message
scrolled away. An agent got blocked on you and filed an issue you never re-read. An
agent found the real fix belonged in another repository, filed it there, wrote a
workaround here, and nobody ever told this repository the blocker was closed.

`openloops` finds those and re-checks them. It answers three questions and nothing
else. It never writes: it does not close, reopen, relabel or comment on anything,
anywhere, and there is no local database — the transcript, the label and the
dependency edge *are* the records.

**The surface most people want is not a command.** If you delegate development to
agents, what you want is an agent that runs the commands and tells you what matters.
That is what to install first; the `ol` command underneath it is plumbing, and it is
documented further down for when you want it directly.

## Start here: install the skills, then ask your agent

```bash
pip install openloops        # Python 3.10+. Puts an `ol` command on your PATH.
ol install-skills            # link the skills and the subagent into ~/.claude
                             # --only openloops,openloops-sweep to skip the capture skill
```

```
installed into ~/.claude
  method: symlink   install: 3   ok: 0   conflict: 0

install  skill  openloops                 not present
                  -> ~/.claude/skills/openloops
install  skill  openloops-needs-human     not present
                  -> ~/.claude/skills/openloops-needs-human
install  agent  openloops-sweep           not present
                  -> ~/.claude/agents/openloops-sweep.md
```

Then open a coding session and ask, in whatever words you would have used anyway:

> **what needs my attention?**

```
## Needs you now
- CI secrets are not provisioned on acme/widget — acme/widget#1, 23 days old. One
  `gh secret set PYPI_PASSWORD --repo acme/widget` and the publish job stops
  failing on merge.
- Decide whether the parser ships in 2.0 or waits — acme/parser#4, 2 days old.
  A judgement call, so no check can ever discharge it; it sits here until you answer.
- Unchecked: acme/widget#9. Its predicate runs the doctests against a live
  third-party fetch and timed out at 20s. Not open, not done — nothing observed it.

## Free to proceed
- acme/widget#109 — every blocker closed. acme/engine#15 has been closed for 5 days
  and nothing has said so. The rename workaround in widget can come out.
- acme/engine#7 — the deploy key is there and the check now passes. The issue is
  merely still open. I have not closed it.

## In flight
- widget: two sessions, the 2.0 parser and an egress scrubbing pass.
- parser, infra, engine: one session each, none of them waiting on you.
- Two widget issues wait on acme/engine and widgets/aix. Nothing for you there.

2 need you, 2 are free to start, 1 could not be checked.
```

That answer is a **synthesis, not a paste** — the skill asks for exactly that, and an
agent that hands you three screens of command output has failed to use it. Every row
behind it is one the `ol` commands printed; you can see the same rows raw, in the
plumbing sections below.

Ask again tomorrow and it is a different answer, because `ol owed` and `ol blocked`
re-run each obligation's check and re-resolve each blocker edge before answering. That
re-check is the whole product; everything else is a list you could have got from `gh`.

### Two things to set up once

**The GitHub CLI, logged in.** Two of the three questions are answered out of GitHub, so
they need `gh` on your PATH and authenticated. The session-digest half needs nothing at
all — no model, no network, no account, no configuration.

**Which repositories you mean.** Left alone, the fleet is whatever login `gh` is
authenticated as. If you work across an organisation, that is a count that looks clean
and is wrong, so say so once:

```bash
export OPENLOOPS_OWNERS="your-login some-org another-org"
```

Every result prints the owners it used, and the read skill is told to check that line
and tell you when it looks too narrow. More on the resolution order below.

### What got installed

| Name | Kind | What it is for |
|---|---|---|
| `openloops` | skill | **the read side.** Teaches an agent which of the three commands answers which question, how to synthesise the three into one page, and — most of all — never to round a `?` into a clean answer. |
| `openloops-needs-human` | skill | **the capture side.** Teaches an agent to file a `manual-task` issue, with a re-checkable predicate, at the moment it gets blocked on you. Without it, `ol owed` has nothing to read. |
| `openloops-sweep` | subagent | the same sweep, run in a fresh context, returning a page instead of three screens. For the session you keep open all day. |

`~/.claude` is Claude Code's config directory, and `CLAUDE_CONFIG_DIR` is honoured if
you have moved it. Any other agent host: `ol install-skills --target DIR`. They are
plain markdown files with YAML front matter; nothing about them is Claude-specific
except where they get installed.

**Re-running it changes nothing.** Each asset is a symlink into the installed package,
so `pip install -U openloops` upgrades the skills too, and a second `ol install-skills`
reads `ok: 3`. Where symlinks are unavailable — Windows without Developer Mode — it
copies instead, and the report says which happened rather than pretending they are the
same thing.

**Nothing already there is ever overwritten.** A destination holding something that is
not ours is reported and left exactly as it was:

```
installed into ~/.claude
  method: symlink   install: 2   ok: 0   conflict: 1

conflict skill  openloops                 something else with this name is already there
                  -> ~/.claude/skills/openloops
install  skill  openloops-needs-human     not present
                  -> ~/.claude/skills/openloops-needs-human
install  agent  openloops-sweep           not present
                  -> ~/.claude/agents/openloops-sweep.md

conflict means nothing was written there. Look at the file, then re-run with --force to replace it.
```

```bash
ol install-skills --dry-run     # print the plan, touch nothing
ol install-skills --copy        # copy instead of link (stops tracking upgrades)
ol install-skills --force       # replace what is there — after you have looked at it
ol install-skills --target DIR  # some other agent host's config directory
```

## The sweep subagent, for the session you keep open all day

The session you want to have this conversation in is a long one: the master session you
leave open and come back to. Running the sweep inline fills that session's context with
command output that is stale ten minutes later, and does it again every time you ask.

`openloops-sweep` is the fix, and it is one file. It runs the three commands in its own
fresh context and returns only the synthesis, so the tenth "what needs my attention?" of
the day costs the main session the same as the first — about a page — no matter how long
the conversation has run.

The read skill dispatches to it when it is installed. Inline is still right for a one-off
question, or when you are about to drill into one row.

## The capture skill, and why `ol owed` has anything to read

`ol owed` reads open issues labelled `manual-task`. On a fresh machine there are none,
and there is no amount of reading that will produce any: **something has to file them.**

That something is `openloops-needs-human`, installed above. It fires at the moment an
agent gets blocked on you — a secret it cannot write, a permission it does not have, a
decision that is yours, a recorded decision that now looks wrong — and files the blocker
as a labelled issue in the affected repository *before* writing the hand-back message
you were never going to re-read.

> **Did openloops file this issue?** No. **openloops never writes to GitHub.** The
> `manual-task` issues it reads are filed by whatever you have told your coding agents to
> do when they get blocked on you, running under your own `gh` credentials; the capture
> skill is one such thing and you can point yours at anything else. If an issue appeared
> that you did not write, an agent wrote it, and that is the system working. openloops
> only reads them back.

The label is the whole storage design. It outlives the session, it is queryable from a
terminal or a phone with every session stopped, and it needs no database to disagree
with:

```bash
gh search issues --owner acme --label manual-task --state open
```

What `openloops` adds to that one-liner is the re-check — and the re-check only works if
the issue carries something to run.

### The field that decides whether an obligation can ever be closed

**An obligation without a predicate can never be re-checked.** It will sit at `open`
forever, correctly, because nothing openloops can run would ever observe it as done. The
capture skill writes these; it is worth two minutes to know what a good one looks like,
because you are the one who will read the count.

Obligations get discharged **out of band.** Somebody adds a deploy key in a web UI,
pays an invoice, answers in chat. None of that emits an event anyone is listening to,
so the issue sits open for months describing something that was done in five minutes.
A stale row annoys; a phantom row destroys the count, and the count is the whole
product.

So each obligation carries its own answer, in its body, as a shell command whose **exit
status is the question**:

```markdown
**Verify:** `gh secret list --repo OWNER/REPO --json name -q '.[].name' | grep -qx PYPI_PASSWORD`
```

The rules the parser actually applies, in the order they bite:

- The field is `Verify:` at the start of a line. The `**` bold markers are optional —
  the field is the contract, not its markup.
- **The predicate is the first backtick code span in the field.** Everything outside it
  is prose.
- **Fenced and indented code blocks are ignored** when looking for the field, so an
  issue that quotes this format in a `<details>` block does not get the example run
  instead of its own predicate.
- **A field that begins `none possible`, `none`, `n/a`, `no predicate` or `not
  possible` yields no command, even if the prose that follows contains a code span.**
  This matters: the natural way to write that sentence mentions `` `gh` `` or
  `` `true` ``, and both exit `0`, which would report a live obligation as done. Use it
  for genuine judgement calls.
- A field with a backtick but no closed code span is *malformed*, and reads `?` rather
  than `open` — a typo should not look like an answer.

What makes a good one:

- **It observes the world, not the issue.** `gh secret list …`, `curl -fsS https://…`,
  `gh api repos/…`. Never something that reads the issue itself: closing an issue is not
  doing the thing.
- **`0` means done and nothing else.** Non-zero for anything short of done.
- **It fails loudly when it cannot check.** openloops already catches the common
  shapes — exit `126`/`127`, death by signal, and stderr saying `command not found`,
  `bad credentials`, `HTTP 401`, `could not resolve host` and friends — and turns them
  into `?` rather than `open`, because a check that never reached the world has not
  observed anything. Write yours so it lands in one of those rather than silently
  exiting `1`.
- **It finishes fast.** Every evaluation is time-bounded (20s by default) and a timeout
  is `?`, not an answer.

One honest limit: predicates are POSIX shell. On a shell that cannot parse one, the
command exits non-zero and the row reads `open`. That is the safe direction to be wrong
in, and it is why the exit status is always on screen.

## `?` means nothing was checked — read this once

`ol owed` and `ol blocked` each report **three** states, never two, and the third is
`unknown`, printed `?`.

`?` is not a rounding error. A tool that says "nothing owed" because `gh` was missing,
or "nothing is waiting" because the network was down, is worse than no tool: it hands
you a clean board you did not earn, and you stop looking. So `unknown` is never
collapsed into either of the other states — not into the alarming one, not into the
reassuring one — and every row that reads `?` prints *why* on the next line: a timeout,
a missing `gh`, an untrusted owner, a malformed predicate.

When the listing itself fails there are no rows to mark, so the whole command says so
and refuses to print a count:

```
owed ?  could not check - gh: not logged in
```

That refusal is the single most important design decision in the package, and the read
skill spends more words on it than on anything else: an agent that answers "nothing
owed" when rows read `?` has told the exact lie this package exists to prevent.

One disambiguation, because the character appears in two places: the `?` in the second
column of `ol`'s own output is **not** this. It means low confidence — the session
never said it was finished — and it is explained under `ol` below. The digest half
checks nothing against the world by design, so it has nothing to be unable to check.

## Before you run it: this executes text from an issue body

Evaluating a predicate means **running a command that came out of a GitHub issue** —
whether you typed `ol owed` or an agent did. That is a real capability, and it is
bounded in five ways, all of them visible:

- **Only owners you configured.** A predicate runs only when the issue's repository
  owner is trusted, which defaults to exactly the owners you searched — so widening the
  search never quietly widens what runs. A row outside that set reads `?`: never
  `open`, because nothing checked it, and never `done`, because nothing ran. In Python
  it is `trusted_owners=`; on the CLI it follows `--owners`.
- **The command is always printed next to its verdict**, in full and never abbreviated,
  so nothing executes invisibly and you can disagree with the answer.
- **`ol owed --no-verify` lists without executing anything.** Every row that has a
  predicate then reads `?`, because that is what is true about it. The read skill is
  told to reach for it on a machine that is not yours, or after you have just added an
  owner whose issues neither of you has read.
- **Every evaluation is time-bounded**, and a timeout is `?` rather than an answer. On
  POSIX the predicate runs in its own process group and the timeout kills the group, so
  anything it started dies with it. On Windows only the shell itself is killed — a
  predicate that backgrounds work can outlive its timeout there. That is a platform
  limit worth knowing rather than a promise broken quietly.
- **`run_predicate=` replaces the evaluator entirely**, and `issues_source=` the reader.

The default is to check, and that is deliberate rather than an oversight: not checking
has a silent failure mode (a count quietly full of things you finished weeks ago) and
checking has a loud one (a command you can see on screen).

---

## The plumbing: the `ol` command

This is what the skills call. It is a perfectly good thing to type yourself — it is how
the author uses it half the time — but if you came here wanting an overview of what your
agents are doing, the section at the top is the one you want.

### Which command answers which question

| You want to know | Run | Needs `gh`? |
|---|---|---|
| What did my sessions leave open? | `ol` | no |
| What do I still owe my agents? | `ol owed` | yes |
| What is waiting on another repo — and what is not any more? | `ol blocked` | yes |

Everything else is a variation on those:

```bash
ol ls --state all           # every digest, newest first
ol ls --confidence high     # drop the ones open only because nothing said otherwise
ol show 2b1f                # one digest, by session id or a unique prefix
ol status                   # where the digests are, how many, how stale the cache is
ol dashboard --out b.html   # all three answers as one self-contained HTML page
ol install-job              # run the digest sync every 15 minutes (macOS launchd)
```

Every block of command output below came out of the shipped renderers. Repository,
project and machine names have been replaced with generic ones; nothing else has been
touched.

## `ol` — what your sessions left open

Claude Code keeps a full JSONL transcript of every session, then garbage-collects it
after about a month. Meanwhile the thing you actually wanted from that session — what
it did, what it left for you, how to get back to it — was one paragraph at the end.
`ol` reads the transcripts, writes one short dated markdown digest per session, and
keeps the digests. It is a **retention** device, not a dashboard.

Bare `ol` syncs and then prints what is open:

```
2026-08-27 10:05   015dcf33  widget                ship the 2.0 parser
2026-08-27 09:53   f8c0b9e2  engine                cross-repo blocker harvest
2026-08-27 09:47 ? 7f400fcb  parser                skill_management
2026-08-26 21:42 ? 8437d111  infra                 sync the staging box
2026-08-26 12:35   8cad34f9  widget                egress scrubbing pass

acme-laptop: 170 sessions scanned, 0 digests written, 170 unchanged, 0 moved; 170 digests in store.
```

Columns: the session's last turn, a `?` for low confidence, the session id (`ol show`
takes any unique prefix), the project directory, and the session's own title for
itself.

**The gotcha: `open` here is loop state, never process state.** A `?` in the second
column does not mean the session is running or crashed. It means the session's own
closing words never said it was finished, so the classifier defaulted to `open`. Five
rules decide it, and the digest always prints which one fired and what cues it saw, so
you can disagree:

| Rule | Reads as |
|---|---|
| the last turn is a usage-limit or API-error notice | `open` — it was cut off |
| the transcript stops before the assistant's turn completed | `open` |
| the closing line is a question put to you | `open` |
| the latest cue in the closing lines defers something | `open` |
| the latest cue in the closing lines declares it finished | `archive` |
| nothing decided it, but the session's own recap does | either |
| nothing decided it at all | `open`, marked low confidence |

**`archive` is earned, `open` is the default.** A session only reaches `archive` by
saying it finished. Against hand-labelled sessions the cue rules never produced a false
`archive` but caught only about half the genuinely finished ones — and that is the right
direction to be wrong in, because a false `archive` buries a loop this tool exists to
surface, while a false `open` only lengthens a list already sorted by recency.

**Conflicts resolve at sentence granularity, and inside a sentence an open cue always
beats a close cue.** Real closing paragraphs carry both kinds: *"say the word and I'll
remove it. Nothing is blocking; safe to close"* is finished, and *"you're safe to exit …
the two threads waiting for you are"* is not — the last cue-bearing sentence decides
those. But *"**Needs you** (nothing blocking, all tracked): the #146 decision"* puts the
close cue inside a parenthetical of the sentence that hands work back, so within one
sentence the asymmetry decides instead of position.

Expect most sessions to land in `open/`. That is what agentic sessions do, and a split
that came out balanced would be a split that was lying. `ol ls --confidence high` drops
the ones that are open only because nothing said otherwise — which is also why the read
skill is told to prefer those rows when it summarises what is in flight.

If `open` ever came to mean "a process is running", this would be a session dashboard.
It is not one, and `claude` already has that view.

### What a digest says — and what it never says

A digest is a dated record of **what one session said**. It carries the session's last
turn, the prompt that provoked it, a context-compaction summary if the session made
one, and any pull-request links the session recorded for itself. Every heading carries
the timestamp of the thing under it.

It never says that anything is *currently* true. There is no "still open", no "more to
do", no "waiting on you" — because `ol` has checked nothing against the world, and a
snapshot presented as a live fact is worse than no snapshot at all. The front matter
says `verified: false` for exactly that reason.

This is the constraint the whole design is arranged around. A tool that quietly tells
you a loop is open when you closed it out of band destroys the count, and the count is
the product. It is also why the other two commands exist: they are the ones that *can*
re-check, and they do.

### Where the digests are stored

```
~/.local/share/openloops/digests/{source}/open/{session}.md
                                          /archive/{session}.md
~/.local/state/openloops/sync-state.json      ← a cache, not data
```

`{source}` is this machine. Two machines syncing digests into one git repository never
write the same path, so there is no merge to reconcile — the directory layout *is* the
answer to cross-machine sync. The label seeds from the machine's short hostname and is
then **sticky**, remembered in the state directory: macOS renames a host that collides on
a network, and a label that drifted would silently fork the store into two copies. Every
sync prints the label it is writing under, and `OPENLOOPS_SOURCE` overrides it.

The cache is deliberately somewhere else. Deleting it re-reads every transcript and
must produce byte-identical digests; deleting the digests loses whatever the
transcripts no longer hold. Those are very different operations and they should not
live in the same folder.

Override with `OPENLOOPS_DATA_DIR`, `OPENLOOPS_STATE_DIR`, `OPENLOOPS_SOURCE`.

### Keeping it up to date

```bash
ol install-job              # a launchd StartInterval agent, every 15 minutes
ol job-status               # installed? loaded? when did it last actually write?
ol uninstall-job
```

It is a periodic job, not a daemon, and that is a decision rather than an
implementation detail: a tick that crashes is repaired by the next one, whereas a
resident process that dies leaves its last output behind with nothing scheduled to
correct it. `ol job-status` reports when a tick last *wrote*, because "the job is
registered" and "the job is working" are not the same claim.

The installer is macOS-only. On Linux, put `ol sync` in a systemd user timer or a
crontab line — `openloops` itself is cross-platform.

---

## `ol owed` — what you still owe your agents

When an agent gets blocked on something only you can do — a secret it cannot write, a
permission it does not have, a decision that is yours — the ask usually dies in a final
message nobody re-reads. The fix is not a new database: it is a `manual-task` label on
an issue in the affected repo, filed by the capture skill above.

`ol owed` lists those issues, and runs each one's check before printing it:

```
2 open, 1 discharged, 1 unknown
  owners: acme  |  predicates: 3 of 4

open   23d  acme/widget#1              CI secrets are not provisioned on this repo
          verify: gh secret list --repo acme/widget --json name -q '.[].name' | grep -qx PYPI_PASSWORD
                  -> exit 1
open    2d  acme/parser#4              Decide whether the parser ships in 2.0 or waits
          verify: (none)
                  -> none possible - a judgement call.
?      23d  acme/widget#9              Doctests depend on a live third-party HTTP fetch
          verify: python3 -m pytest -q --doctest-modules --pyargs widget.remote
                  -> the predicate timed out after 20s
done   30d  acme/engine#7              Add a deploy key so CI can clone the fixture repo
          verify: [ "$(gh api repos/acme/engine/keys --jq length)" -gt 0 ]
                  -> exit 0
```

| Printed | State | Means |
|---|---|---|
| `open` | `open` | no predicate at all, or the predicate ran and returned non-zero |
| `done` | `discharged` | the predicate returned `0` — the ask is finished, the issue is merely still open |
| `?` | `unknown` | nothing could be checked: no `gh`, no network, a timeout, an untrusted owner, a malformed predicate |

`done` rows are reported, never acted on. A passing predicate is evidence, not
authority; you close the issue, or you don't. The read skill is told the same thing in
the same words, because a model that closes an issue on a shell exit status has written
a record nobody can audit back.

```bash
ol owed                     # list them, and re-check each one against the world
ol owed --no-verify         # list them, executing nothing — every predicate row reads ?
ol owed --owners acme,widgets
ol owed --limit 100
```

Writing the `**Verify:**` predicate is covered above, under the capture skill; so is
what it means that running one executes text out of an issue body.

---

## `ol blocked` — what is waiting on another repo, and what is not any more

The same shape, pointed at a repository instead of at a person.

An agent working in repo X finds that the real fix belongs in repo Y. It files in Y,
writes a workaround in X, and moves on. Y gets fixed. **X is never told.** Nobody was
blocking, nothing waited on a human, so the loop is invisible to `ol owed` — and the
workaround in X quietly becomes architecture, noticed months later only when somebody
asks why the code looks like that.

GitHub already models the edge, and it already crosses repositories: an issue's
**blocked-by dependencies** name each blocker's own repository, number and state. They
are a first-class GitHub field, set on the issue itself in GitHub's own UI, not a
convention openloops invented — the representation costs nothing and exists today.
**What is missing is the harvest**: nothing notices when a blocker closes, because the
edge is queryable, not eventful.

`ol blocked` is that harvest:

```
1 unblocked, 2 blocked, 0 unknown
  scope: acme, widgets  |  candidates: 4  |  1 had no dependency edge at all

ready    8d  acme/widget#109              Drop the rename workaround once the engine lands it
        blocked by: acme/engine#15 [closed]
                    -> free for 5d, and nothing has said so
waits    8d  acme/widget#27               Criteria carry a structured definition, not free text
        blocked by: acme/engine#61 [open]
waits    8d  acme/widget#34               Track the six facade gaps, and which phase each one blocks
        blocked by: widgets/aix#40 [open] widgets/aix#41 [open]
```

| Printed | State | Means |
|---|---|---|
| `ready` | `unblocked` | every blocker is closed. The work can proceed and nobody has been told — **this is the row the command exists for.** It sorts first and says how many days it has been free |
| `waits` | `blocked` | at least one blocker is still open, and the row names which, with the foreign repository |
| `?` | `unknown` | the edges could not be resolved |

`ready` is a finding, not an instruction. The workaround in X may still be the right
code; only you know that.

```bash
ol blocked                                  # search a fleet, resolve every edge
ol blocked --owners acme,widgets
ol blocked --repos acme/widget,acme/engine  # the audit path: enumerate these exactly
ol blocked --no-resolve                     # spend nothing; every row reads ?
ol blocked --limit 100
```

### The gotcha: discovery is a candidate list, not an answer

Finding the blocked issues has two implementations, and which one runs depends on
whether you passed `--repos`.

**Across a fleet** (the default): one `gh search issues` call carrying GitHub's own
`is:blocked` qualifier. One request answers for every repository, which is what makes
this cheap enough to run at the start of a session. But the qualifier is a *search
index*, and a search index is not the dependency graph. Measured on one real fleet on
2026-08-27, scoped to three owners: `is:blocked` returned 15 open issues, of which **10
carried a blocked-by edge and 5 carried no dependency edge of any kind** — not a stale
edge, and four of the five carry no sub-issue relation either, simply none. Recall was perfect
on that fleet: all 10 were found, checked against a full per-repository enumeration of
821 open issues across 148 repositories. Precision was 10/15.

So every candidate is re-resolved against the dependency graph itself, and one with no
edge is dropped and *counted* — that is the `1 had no dependency edge at all` note in
the header. A discovery step that quietly disagrees with reality is the same class of
defect as a count that cannot say `?`.

**Per repository** (`--repos owner/name,owner/other`): one paginated listing per
repository, filtered on the dependency counts GitHub already returns on every row of
it. This reads the counts themselves rather than an index of them, so it cannot
over-report and cannot miss. It is the audit, not the daily command.

### What it costs

Resolving edges is **one API call per candidate** — there is no batch form. `--limit`
is that bound and it defaults to 50; one more than it is requested, so a candidate list
that saturates its own cap comes back marked `TRUNCATED` and the counts are then a
**floor**, never a total. At the default that is at most 51 requests against a
5000/hour limit. A 15-candidate fleet run took 41-48 s wall-clock across several runs here.

`--no-resolve` skips all of it and every row reads `?`, which is honest and free.

---

## `ol dashboard` — the same four registers as one page

```bash
ol dashboard --out board.html
```

All three answers rendered as one self-contained HTML document: no stylesheet, no
script, no font, no request to anywhere. It is the page you leave open on a second
monitor, or publish somewhere your phone can reach.

Being self-contained is what makes it publishable, and it is also its one limit: **a
page cannot re-check anything.** So it stamps the moment it was made and says
"snapshot" in its largest type, and its fourth register is `Unknown` — every `?`, with
why, including the envelope-level failures. An `owed` that could not list is not
"nothing owed", and rendering that as a `0` would make the page worse than no page.
When the count really is zero the section names which checks earned it.

Everything printed goes through the same scrubber that guards the digests, plus HTML
escaping and a scheme allowlist on every link. `--fragment` drops the document scaffold
for a host that supplies its own `<head>`.

---

## Turning it off

Nothing here runs unless you type it, or an agent you installed a skill for does. There
is one exception, and it is opt-in: `ol install-job` puts the digest sync on a timer.
Check with `ol job-status`; if it says the plist is absent, nothing of openloops is
running in the background at all.

```bash
ol uninstall-job            # stop the timer, if you ever installed it
rm -rf ~/.claude/skills/openloops ~/.claude/skills/openloops-needs-human \
       ~/.claude/agents/openloops-sweep.md      # the skills are three symlinks
pip uninstall openloops     # remove the package
```

`pip uninstall` leaves your digests where they are — `~/.local/share/openloops/` by
default, or wherever `OPENLOOPS_DATA_DIR` points — because deleting a record is not part
of removing a tool. Delete that directory yourself if you want the data gone too.

Nothing needs undoing on GitHub. openloops never wrote anything there: no issue was
created, closed, relabelled or commented on, and the `**Verify:**` lines in your issue
bodies were put there by whoever wrote them, not by this package.

## Which repositories all this is about

`ol owed` and `ol blocked` answer about the same fleet, resolved the same way, so the
two can never quietly disagree about which repositories exist. Three sources, first one
wins:

1. `OPENLOOPS_OWNERS` — comma- or space-separated (or `--owners` on either command).
2. The owners named by a `gh` alias called `owe`, if you have one. A fleet of several
   organisations is usually already written down there, and disagreeing with the thing
   you actually type is how a count goes quietly wrong.
3. The login `gh` is authenticated as.

Whichever it was is printed on every result, so a partial answer is a visible one. It is
worth setting explicitly: the fallback is your personal login, and if you work across an
organisation, a count that only ever saw your own repositories looks clean and is wrong.
The read skill is told to check that line and say so.

## Python API

```python
import openloops

openloops.sync()  # read transcripts → write digests
for row in openloops.ls(state="open"):  # what your sessions left open
    print(row["session"], row["title"])

print(openloops.show("2b1f")["text"])  # one digest, in full

report = openloops.owed()  # open `manual-task` issues, each re-checked
print(report["counts"])  # {'open': 2, 'discharged': 1, 'unknown': 1, ...}

report = openloops.blocked()  # cross-repo blocker edges, every one resolved
print([r["repo"] + "#" + str(r["number"])
       for r in report["rows"] if r["state"] == "unblocked"])

openloops.install_skills(dry_run=True)  # the plan, having touched nothing
```

`owed()` and `blocked()` return an **envelope, never a bare list** — because a caller
has to be able to tell "nothing is owed" from "I could not find out":

```python
{
    "listed": True,  # False ⇒ the listing/discovery itself failed; the counts mean nothing
    "checked": True,  # blocked() calls this "resolved"
    "error": "",
    "truncated": False,  # the result set hit its cap: the counts are a floor
    "owners": [...],
    "counts": {...},
    "rows": [...],
}  # every row carries every documented key, present and empty if unset
```

Check `listed` before you read `counts`. That is the whole contract.

`openloops.tools` is the single dispatch list every surface goes through — the `ol`
command today, an MCP server or an HTTP endpoint later. Operations go there, never
straight into the CLI, which is what stops two surfaces from drifting apart.
`install_skills` is deliberately *not* in it: "symlink files into this machine's agent
config" is not an operation a remote surface could honestly offer.

## The seams

Each is one keyword argument, and each defaults to a real implementation rather than a
stub wearing a keyword argument as a disguise:

```python
openloops.sync(
    transcript_source=my_sessions,  # any Mapping[str, Session]
    digests_store=my_store,  # any MutableMapping[str, str]
)

openloops.owed(
    issues_source=[...],  # a list of dicts, or any callable
    run_predicate=lambda cmd: 0,  # any callable from command to exit status
)

openloops.blocked(
    issues_source=[...],
    blockers_source={"acme/widget#12": [...]},  # or any callable of (repo, number)
)
```

`transcript_source=` defaults to a direct reader of Claude Code's on-disk layout.
`digests_store=` defaults to a `dol` store over a directory of markdown files, with its
encoding pinned to UTF-8 and its delete made a real delete. Point it at an S3-backed
store, or at a git-synced directory shared between machines, and nothing else changes.

`issues_source=` and `run_predicate=` default to a `gh` search and a time-bounded
subshell; `blockers_source=` to the dependency-graph call. **With them injected, the
GitHub half needs no network and no `gh` on PATH** — which is how the whole of it is
tested.

Pass `state_dir=` too when you swap a digest seam in a test: the change-detection cache
is separate from both, and left alone it would record your fixture's revisions in the
real one.

## Nothing leaves without being scrubbed

Transcripts are the highest-entropy secret source on a developer machine: pasted
tokens, `.env` contents, tracebacks full of absolute paths. A digest store can be a
synced git repository, so **a written digest is an export surface**, and the discipline
belongs before the first byte is written rather than before the first push.

- Absolute paths under your home directory are rewritten to `~`-relative.
- Credential-shaped text **raises**. It is never silently redacted, because a silent
  redaction teaches nobody that a secret was there. That session is skipped, the run
  says so and exits non-zero, and the error names the pattern class and offset without
  ever quoting the match.

The same two rules are what the capture skill applies to an issue title and body before
it files anything, through the same `openloops.egress` functions — so an agent that
gets blocked while holding a token in its context cannot publish it by accident, and
cannot mask it and file anyway either.

## Why not just read the transcripts, or use `gh` directly?

For the digests: `claude` shows you your live sessions, which is a different question —
and a better answer to it than this could be. The transcripts themselves answer the
question `ol` answers, right up until they are deleted. A digest is a few hundred bytes
and outlives the megabyte it came from.

For the other two: the query is one line of `gh` and always was. The whole of what
openloops adds is **the re-check** — running the predicate, resolving the edge — and
the refusal to round an unchecked row into an answer. That is the entire difference
between a list and a count you can act on.

There is one caveat worth knowing before you read a digest as a diary: a Claude Code
*session* is not a sitting. Sessions get resumed, so a single session can span days,
and a digest keyed on one is a digest of a thread of work rather than of an afternoon.

## The name

Two live collisions, both deliberate, both worth knowing before you search for it:

- **OpenLoops** is an established particle-physics one-loop amplitude library
  ([openloops.hepforge.org](https://openloops.hepforge.org)). It is not on PyPI, and it
  is what a web search will find first.
- **openloops** is also [a browser-history tool](https://github.com/sholajegede/openloops)
  that groups your browsing into what you were trying to do — an adjacent product using
  the same metaphor, in a different distribution channel.

Neither blocks `pip install openloops`. The command is `ol` because a read path that
costs eighteen characters to reach is a read path that does not get reached.

## Design tests

These are tests in the suite, not aspirations:

- **A digest is derived, never authored.** Delete the digest store and the cache, sync
  again, and every digest whose transcript still exists comes back byte-for-byte.
  Digests whose transcripts have since been collected are *retained* — that is the
  point of the tool — and `ol status` counts them separately.
- **The suite passes with no network, no credentials, and no `~/.claude` present.**
- **`import openloops` does not import the CLI library**, and opens no socket. The core
  has no opinion about how it is called, and a job on a plane still has to run.
- **Nothing in this repository carries an absolute home path or credential-shaped
  text** — checked mechanically, by the same code that scrubs your digests. The shipped
  skills are in the repository, so they are checked by it too.
- **No surface exposes an operation that writes.** Enforcement is by omission: there is
  no `close`, no `comment`, no `POST`. A test walks the source and fails the build if a
  mutating verb or a mutating `gh` argument appears anywhere in the package.
- **`ol install-skills` never overwrites anything.** An occupied destination reads
  `conflict` and is left exactly as it was; a second run of a clean install reads `ok`
  and writes nothing.
- **`unknown` never becomes `open`, `discharged`, `blocked` or `unblocked`**, and a
  listing that failed prints `?` rather than a count. Both are tested directly, because
  they are the two ways a tool like this becomes a liar.

## License

Apache-2.0.
