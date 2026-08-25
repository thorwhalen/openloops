# openloops

Tells you what your Claude Code sessions were doing — and still tells you after the
transcripts are gone.

Claude Code keeps a full JSONL transcript of every session, then garbage-collects it
after about a month. Meanwhile the thing you actually wanted from that session — what
it did, what it left for you, how to get back to it — was one paragraph at the end.
`openloops` reads the transcripts, writes one short dated markdown digest per session,
and keeps the digests. It is a **retention** device, not a dashboard.

No model is called. No network request is made. No account, no credentials, no
configuration: it reads files you already have and writes files you already own.

## Install

```bash
pip install openloops
```

That puts an `ol` command on your PATH. Python 3.10+.

## Quick start

### CLI

```bash
ol                          # sync, then show what your sessions left open
ol ls --state all           # every digest, newest first
ol ls --confidence high     # drop the ones open only because nothing said otherwise
ol show 2b1f                # one digest, by session id or a unique prefix
ol status                   # where the digests are, how many, how stale the cache is
ol install-job              # run the sync every 15 minutes (macOS launchd)
```

### Python API

```python
import openloops

openloops.sync()  # read transcripts → write digests
for row in openloops.ls(state="open"):  # what your sessions left open
    print(row["session"], row["title"])

print(openloops.show("2b1f")["text"])  # one digest, in full
```

## What a digest says — and what it never says

A digest is a dated record of **what one session said**. It carries the session's last
turn, the prompt that provoked it, a context-compaction summary if the session made
one, and any pull-request links the session recorded for itself. Every heading carries
the timestamp of the thing under it.

It never says that anything is *currently* true. There is no "still open", no "more to
do", no "waiting on you" — because openloops has checked nothing against the world, and
a snapshot presented as a live fact is worse than no snapshot at all. The front matter
says `verified: false` for exactly that reason.

This is the constraint the whole design is arranged around. A tool that quietly tells
you a loop is open when you closed it out of band destroys the count, and the count is
the product.

## `open/` and `archive/` are loop state, never process state

Digests are filed under `open/` or `archive/` by how the session's own last turn
**read** — not by whether a `claude` process is running. Five rules decide it, and the
digest always prints which one fired and what cues it saw, so you can disagree with it:

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

## Where things are stored

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
`ol sync` prints the label it is writing under, and `OPENLOOPS_SOURCE` overrides it.

The cache is deliberately somewhere else. Deleting it re-reads every transcript and
must produce byte-identical digests; deleting the digests loses whatever the
transcripts no longer hold. Those are very different operations and they should not
live in the same folder.

Override with `OPENLOOPS_DATA_DIR`, `OPENLOOPS_STATE_DIR`, `OPENLOOPS_SOURCE`.

## The two seams

Both are one keyword argument, and both default to something that already works:

```python
openloops.sync(
    transcript_source=my_sessions,  # any Mapping[str, Session]
    digests_store=my_store,  # any MutableMapping[str, str]
)
```

`transcript_source=` defaults to a direct reader of Claude Code's on-disk layout.
`digests_store=` defaults to a `dol` store over a directory of markdown files, with its
encoding pinned to UTF-8 and its delete made a real delete. Point it at an S3-backed
store, or at a git-synced directory shared between machines, and nothing else changes.

Pass `state_dir=` too when you swap a seam in a test: the change-detection cache is
separate from both, and left alone it would record your fixture's revisions in the real
one.

## Keeping it up to date

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

The installer is macOS-only. On Linux, put the same command in a systemd user timer or
a crontab line — `openloops` itself is cross-platform.

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

## Why not just read the transcripts, or use `claude` itself?

`claude` shows you your live sessions, which is a different question — and a better
answer to it than this could be. The transcripts themselves answer the question
`openloops` answers, right up until they are deleted. A digest is a few hundred bytes
and outlives the megabyte it came from.

There is one caveat worth knowing before you read a digest as a diary: a Claude Code
*session* is not a sitting. Sessions get resumed, so a single session can span days,
and a digest keyed on one is a digest of a thread of work rather than of an afternoon.

## What openloops is NOT (yet)

It does not track what you owe your agents, or what they owe you. That is the
project's headline claim, and it is **withheld pending a measurement** rather than
unfinished: whether an obligation ledger is worth building depends on whether agents
actually file the asks they raise, and that number had not been measured. Publishing a
ledger before measuring would be construction in search of a justification.

So this release contains no obligation, no ledger, no GitHub write, no MCP server, no
model call and no notification surface. What it does contain is the instrument the
measurement needs — the same extractor that writes digests answers "did this session
end with a question directed at the human?" — which is why it ships first.

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
- **`import openloops` does not import the CLI library.** The core has no opinion about
  how it is called.
- **Nothing in this repository carries an absolute home path or credential-shaped
  text** — checked mechanically, by the same code that scrubs your digests.

## License

Apache-2.0.
