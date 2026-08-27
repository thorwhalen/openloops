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

## Install

```bash
pip install openloops
```

That puts an `ol` command on your PATH. Python 3.10+.

Two of the three commands need the GitHub CLI (`gh`) on your PATH and logged in. The
session-digest half needs nothing at all — no model, no network, no account, no
configuration.

## Which command answers which question

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
ol install-job              # run the digest sync every 15 minutes (macOS launchd)
```

Every sample below was produced by the shipped renderers from the commands' own renderers. Repository,
project and machine names have been replaced with generic ones; nothing else has been
touched.

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

That refusal is the single most important design decision in the package.

One disambiguation, because the character appears in two places: the `?` in the second
column of `ol`'s own output is **not** this. It means low confidence — the session
never said it was finished — and it is explained under `ol` below. The digest half
checks nothing against the world by design, so it has nothing to be unable to check.

---

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
the ones that are open only because nothing said otherwise.

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

> **Did openloops file this issue?** No. **openloops never writes to GitHub.** The
> `manual-task` issues it reads are filed by whatever you have told your coding agents to
> do when they get blocked on you — for the author, that is a
> [`needs-human` skill](https://github.com/thorwhalen/openloops-lab) that files one and
> marks it with an HTML comment. If an issue appeared that you did not write, an agent
> wrote it, and that is the system working. openloops only reads them back.


When an agent gets blocked on something only you can do — a secret it cannot write, a
permission it does not have, a decision that is yours — the ask usually dies in a final
message nobody re-reads. The fix is not a new database: it is a `manual-task` label on
an issue in the affected repo, which outlives the session and is queryable from a
terminal or a phone with every session stopped.

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
authority; you close the issue, or you don't.

```bash
ol owed                     # list them, and re-check each one against the world
ol owed --no-verify         # list them, executing nothing — every predicate row reads ?
ol owed --owners acme,widgets
ol owed --limit 100
```

### The gotcha: the verify predicate, and how to write one

**An obligation without a predicate can never be re-checked.** It will sit at `open`
forever, correctly, because nothing openloops can run would ever observe it as done.
You are the person who will be writing these, so it is worth two minutes.

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
  `gh api repos/…`. Never something that reads the issue itself.
- **`0` means done and nothing else.** Non-zero for anything short of done.
- **It fails loudly when it cannot check.** openloops already catches the common
  shapes — exit `126`/`127`, death by signal, and stderr saying `command not found`,
  `bad credentials`, `HTTP 401`, `could not resolve host` and friends — and turns them
  into `?` rather than `open`, because a check that never reached the world has not
  observed anything. Write yours so it lands in one of those rather than silently
  exiting `1`.
- **It finishes fast.** Every evaluation is time-bounded (20s by default) and a timeout
  is `?`, not an answer — as the `acme/widget#9` row above shows.

One honest limit: predicates are POSIX shell. On a shell that cannot parse one, the
command exits non-zero and the row reads `open`. That is the safe direction to be wrong
in, and it is why the exit status is always on screen.

### Before you run it: this executes text from an issue body

Evaluating a predicate means **running a command that came out of a GitHub issue**.
That is a real capability, and it is bounded in five ways, all of them visible:

- **Only owners you configured.** A predicate runs only when the issue's repository
  owner is trusted, which defaults to exactly the owners you searched — so widening the
  search never quietly widens what runs. A row outside that set reads `?`: never
  `open`, because nothing checked it, and never `done`, because nothing ran. In Python
  it is `trusted_owners=`; on the CLI it follows `--owners`.
- **The command is always printed next to its verdict**, in full and never abbreviated,
  so nothing executes invisibly and you can disagree with the answer.
- **`ol owed --no-verify` lists without executing anything.** Every row that has a
  predicate then reads `?`, because that is what is true about it.
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

## Turning it off

Nothing here runs unless you type it. There is one exception, and it is opt-in:
`ol install-job` puts the digest sync on a timer. Check with `ol job-status`; if it says
the plist is absent, nothing of openloops is running in the background at all.

```bash
ol uninstall-job            # stop the timer, if you ever installed it
pip uninstall openloops     # remove the package
```

That is the whole of it. `pip uninstall` leaves your digests where they are —
`~/.local/share/openloops/` by default, or wherever `OPENLOOPS_DATA_DIR` points — because
deleting a record is not part of removing a tool. Delete that directory yourself if you
want the data gone too.

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

Whichever it was is printed on every result, so a partial answer is a visible one.

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
print(
    [
        r["repo"] + "#" + str(r["number"])
        for r in report["rows"]
        if r["state"] == "unblocked"
    ]
)
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
  text** — checked mechanically, by the same code that scrubs your digests.
- **No surface exposes an operation that writes.** Enforcement is by omission: there is
  no `close`, no `comment`, no `POST`. A test walks the source and fails the build if a
  mutating verb or a mutating `gh` argument appears anywhere in the package.
- **`unknown` never becomes `open`, `discharged`, `blocked` or `unblocked`**, and a
  listing that failed prints `?` rather than a count. Both are tested directly, because
  they are the two ways a tool like this becomes a liar.

## License

Apache-2.0.
