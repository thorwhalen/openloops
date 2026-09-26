# openloops

What your Claude Code sessions were doing — kept after the transcripts are gone.

Claude Code writes a JSONL transcript for every session and deletes it after about a
month. openloops reads those transcripts, writes one short dated markdown digest per
session, and keeps the digests. Nothing here calls a model, reaches the network, or
needs an account: it reads files you already have and writes files you already own.

```pycon
>>> import openloops
>>> report = openloops.sync()
>>> for row in openloops.ls(state='open'):
...     print(row['session'], row['ai_title'] or row['title'])
```

The whole design rests on one sentence, and everything else follows from it:

> **A digest says what a session said, dated. It never says what is true now.**

So a digest is filed under `open/` or `archive/` by what the session’s own last
turn *read* like — not by whether a process is running, which would make this a session
dashboard rather than a record of open loops. Nothing is asserted to be still
outstanding, because openloops has checked nothing against the world.

The two modules whose primary export shares their name — the sync engine and the
classifier — are private (`openloops._sync`, `openloops._classify`), because a
module and a function cannot both answer to `openloops.sync`. Everything they export
is re-exported here, including the classifier’s cue tables.

Two seams, both one keyword argument, both defaulting to something that works out of
the box: `transcript_source=` (a reader of Claude Code’s on-disk layout) and
`digests_store=` (a directory of markdown files under `~/.local/share/openloops/`).
Swap either for a test fixture, a git-synced directory, or blob storage without
touching anything else.

There is a second thing here, added later and kept deliberately small:
`openloops.owed()` lists the open `manual-task` issues your agents filed when they
got blocked on you, and — this is its whole reason to exist — re-runs the shell
predicate each issue carries before showing it, so an obligation discharged out of band
reads *discharged* rather than sitting open for months. It reads and reports; it never
closes, relabels or writes anything, and it keeps no copy of anything: the label is the
record. Its trust boundary (evaluating a predicate executes text from an issue body)
and its kill criterion are both written out in [`openloops.obligations`](openloops.obligations.md#module-openloops.obligations).

```pycon
>>> report = openloops.owed()
>>> report['counts']
{'open': 6, 'discharged': 1, 'unknown': 2, 'with_predicate': 7, 'total': 9}
```

And a third thing, which is the same thing pointed at a repository instead of at a
person: `openloops.blocked()`. When an agent working in repo X finds the real fix
belongs in repo Y, it files in Y and moves on — and X is never told when Y is fixed, so
the workaround in X quietly becomes architecture. GitHub’s issue dependencies already
record that edge across repositories; what nothing does is notice when the blocker
closes, because the edge is queryable rather than eventful. `blocked()` resolves every
edge and reports `unblocked` (every blocker resolved: the work is free and nobody has
been told), `blocked` (naming the foreign repository) and `unknown`. It reads and
reports; it writes nothing. What its discovery step is measured to over-report, what
bounds its one-call-per-issue resolution, and its kill criterion are all in
[`openloops.blockers`](openloops.blockers.md#module-openloops.blockers).

```pycon
>>> report = openloops.blocked()
>>> [r['repo'] + '#' + str(r['number'])
...  for r in report['rows'] if r['state'] == 'unblocked']
['acme/widget#109']
```

All three of those are plumbing, and the surface most people actually want is an agent
that knows how to use the plumbing and tells them what matters. So the package also
ships that agent, as files: a `openloops` skill that answers “what is being done, and
what needs my attention?”, a `openloops-needs-human` skill that files the
`manual-task` issues `owed()` later reads back, and an `openloops-sweep` subagent
that runs the whole sweep in a fresh context. `install_skills()` links them into an
agent host; see [`openloops.skills`](openloops.skills.md#module-openloops.skills) for why it links rather than copies and why it
never overwrites.

```pycon
>>> plan = openloops.install_skills(dry_run=True)
>>> [row['name'] for row in plan['actions']]
['openloops', 'openloops-needs-human', 'openloops-sweep']
```

And a page to look at instead of reading three command outputs:
`openloops.render_dashboard()` turns those same three answers into one self-contained
HTML document — no stylesheet, no script, no font, nothing fetched from anywhere.
Because it fetches nothing it also *checks* nothing, so it is a **snapshot**: it stamps
the moment it was made and says so in its largest type, and any figure it could not
establish reads `?` rather than `0`. `ol dashboard` writes one.

```pycon
>>> page = openloops.render_dashboard(
...     openloops.owed(), openloops.blocked(), openloops.ls(limit=0))
```

**Still not here, and deliberately:** a ledger. No store, no schema, no history, no
event log, no cross-repo links, no session model, and no write path of any kind.

### Functions

| [`exchanges`](#openloops.exchanges)(records, \*[, key])                      | Every prompt of a transcript's main thread, in order, each with its turn's reply.                                     |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`question_sentences`](#openloops.question_sentences)(text)                           | The sentences of a person's prompt that ask something, in order, at most `MAX_QUESTIONS`.                             |
| [`agents_dir`](#openloops.agents_dir)()                                       | The bundled subagent definitions, inside the installed package.                                                       |
| [`asks_the_human`](#openloops.asks_the_human)(text, \*[, ask_cues, chars])        | The ask cues in the closing lines, if those lines put a question to the reader.                                       |
| [`blocked`](#openloops.blocked)(\*[, resolve, owners, repos, query, ...])  | Open issues that carry a blocker edge, with every edge resolved.                                                      |
| [`classify`](#openloops.classify)(session, \*[, ask_cues, defer_cues, ...]) | Read a session's loop state from its own last turn.                                                                   |
| [`data_dir`](#openloops.data_dir)()                                         | The project's data root.                                                                                              |
| [`default_source`](#openloops.default_source)([directory])                        | This machine's label for its digest folder.                                                                           |
| [`digest_key`](#openloops.digest_key)(source, state, session_key)             | The store key for one session's digest.                                                                               |
| [`digests_store`](#openloops.digests_store)([rootdir])                           | The default `digests_store`: markdown files under the data root.                                                      |
| [`gh_blocked_by`](#openloops.gh_blocked_by)(repo, number, \*[, timeout])         | The default `blockers_source`: the blocker edges out of one issue.                                                    |
| [`gh_blocked_candidates`](#openloops.gh_blocked_candidates)(\*[, owners, repos, ...])    | The default `issues_source`: open issues that *may* carry a blocker edge.                                             |
| [`gh_issues`](#openloops.gh_issues)(\*, owners[, label, state, limit, ...])  | The default `issues_source`: the open `manual-task` issues, from `gh`.                                                |
| [`headline_counts`](#openloops.headline_counts)(owed, blocked, sessions)           | The four figures across the top of the page.                                                                          |
| [`install_skills`](#openloops.install_skills)(\*[, target, only, copy, ...])      | Make the bundled skills and subagent visible to an agent host.                                                        |
| [`ls`](#openloops.ls)(\*[, state, source, project, confidence, ...])  | The digests in the store, newest last-turn first.                                                                     |
| [`make_digest`](#openloops.make_digest)(session, verdict, \*, source[, ...])   | Render, scrub, and key one digest.                                                                                    |
| [`owed`](#openloops.owed)(\*[, verify, owners, trusted_owners, ...])    | The open `manual-task` obligations, each re-checked against the world.                                                |
| [`parse_session`](#openloops.parse_session)(records, \*[, key])                  | Read one transcript's records into a [`Session`](openloops.base.md#openloops.base.Session). |
| [`parse_verify`](#openloops.parse_verify)(body)                                 | `(predicate, verify_text)` for an issue body.                                                                         |
| [`render`](#openloops.render)(session, verdict, \*, source)               | The markdown for one digest.                                                                                          |
| [`render_dashboard`](#openloops.render_dashboard)(owed, blocked, sessions, \*)      | The three envelopes as one self-contained HTML page.                                                                  |
| [`retained`](#openloops.retained)(store, sessions, \*[, source])            | Digest keys whose session no longer has a transcript — the retention surplus.                                         |
| [`scrub`](#openloops.scrub)(text, \*[, aliases, where])                  | Rewrite paths and raise on credentials.                                                                               |
| [`shell_predicate`](#openloops.shell_predicate)(command, \*[, timeout])            | The default `run_predicate`: run the command in a subshell, bounded in time.                                          |
| [`show`](#openloops.show)(session, \*[, source, digests_store])         | One digest in full, found by session id or by a unique prefix of one.                                                 |
| [`skills_dir`](#openloops.skills_dir)()                                       | The bundled skills directory, inside the installed package.                                                           |
| [`state_dir`](#openloops.state_dir)()                                        | Where per-machine caches and job logs go.                                                                             |
| [`status`](#openloops.status)(\*[, source, since_days, ...])              | Where everything is, how much of it there is, and how stale the cache is.                                             |
| [`sync`](#openloops.sync)(\*[, transcript_source, digests_store, ...])  | Bring the digest store up to date with the sessions, and say what changed.                                            |

### Classes

| [`Exchange`](#openloops.Exchange)(session, uuid, origin, asked_at, prompt)   | One prompt a session received and the reply its turn ended with.               |
|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`BlockedIssue`](#openloops.BlockedIssue)(repo, number, title, url, ...)         | One open issue that carries blocker edges, with the verdict those edges imply. |
| [`Blocker`](#openloops.Blocker)(repo, number[, state, url, closed_at])      | One edge: the issue, in whatever repository it lives, that blocks another.     |
| [`ClaudeCodeTranscripts`](#openloops.ClaudeCodeTranscripts)([root, since_days, ...])      | Claude Code's persisted sessions, as a `Mapping[str, Session]`.                |
| [`Digest`](#openloops.Digest)(key, text, session_key, source, state)       | One rendered digest: its store key and its markdown text.                      |
| [`Locator`](#openloops.Locator)(type[, url, text, at])                      | A typed, human-readable pointer to something outside the digest.               |
| [`Obligation`](#openloops.Obligation)(repo, number, title, url, ...[, ...])    | One open `manual-task` issue, with the verdict its own predicate returned.     |
| [`PredicateOutcome`](#openloops.PredicateOutcome)(status[, output])                  | What evaluating one predicate produced.                                        |
| [`Session`](#openloops.Session)(key[, title, ai_title, cwd, ...])           | What one Claude Code session's persisted state says, parsed but not judged.    |
| [`Verdict`](#openloops.Verdict)(state, reason[, cues, at, confidence])      | A loop-state judgement, with the rule that produced it and the cues it saw.    |

### Exceptions

| [`CredentialFound`](#openloops.CredentialFound)(pattern_name, offset, \*[, where])   | Raised when text about to be written matches a credential pattern.           |
|-------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`GhUnavailable`](#openloops.GhUnavailable)                                        | The world could not be read: no `gh`, no credentials, no network, a timeout. |

### *class* openloops.BlockedIssue(repo, number, title, url, created, age_days, state='unknown', blockers=(), cross_repo=False, unblocked_days=0, evidence='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One open issue that carries blocker edges, with the verdict those edges imply.

`blockers` is carried in full next to `state` so a reader can disagree with the
verdict rather than absorb it — the same rule `openloops.obligations.
Obligation` follows for its predicate.

```pycon
>>> BlockedIssue('acme/widget', 12, 't', 'u', '2026-01-01T00:00:00Z', 3).state
'unknown'
```

#### as_dict()

JSON-ready form, blockers included.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### cross_repo *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

At least one blocker lives in another repository — the shape this module is for.

#### unblocked_days *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 0*

how long the work
has been free while nobody was told. `0` for every other state.

* **Type:**
  Days since the last blocker closed, for an `unblocked` row

### *class* openloops.Blocker(repo, number, state='', url='', closed_at='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One edge: the issue, in whatever repository it lives, that blocks another.

`repo` is the *blocker’s* repository, and carrying it is the whole point — an
edge that did not name it would answer only the easy half of the question.

```pycon
>>> Blocker('acme/engine', 15, 'closed').ref
'acme/engine#15 [closed]'
>>> Blocker('acme/engine', 15).ref
'acme/engine#15 [?]'
>>> Blocker('', 15, 'closed').ref
'?#15 [closed]'
```

#### as_dict()

JSON-ready form, with [`ref`](#openloops.Blocker.ref) materialised for surfaces that print it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### *property* ref *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`owner/name#number [state]` — how a blocker is written down.

A `?` in either half is a fact about what could be read, never a shrug: an
edge whose repository the payload did not name says so rather than borrowing
the blocked issue’s own repository and inventing a same-repo dependency.

### *class* openloops.ClaudeCodeTranscripts(root=None, , since_days=None, projects=None, skip_scratchpads=True)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

Claude Code’s persisted sessions, as a `Mapping[str, Session]`.

`since_days` bounds the scan by file modification time (`None` scans
everything); `projects` keeps only project directories whose name contains one of
the given substrings; `skip_scratchpads` drops the throwaway directories the CLI
creates under a temp root, which hold agent scratch sessions rather than work.

ADR-010’s revision shape lives here: [`revision()`](#openloops.ClaudeCodeTranscripts.revision) returns an opaque token —
a file’s modification time for one session, a hash over all of them for the
collection — and [`changed_since()`](#openloops.ClaudeCodeTranscripts.changed_since) compares against it. mtime is a coarse
signal that both misses content-preserving rewrites and fires on touches; that
trade is accepted rather than reprocessing several thousand transcripts a tick.

```pycon
>>> src = ClaudeCodeTranscripts(root='/nonexistent-dir-for-doctest')
>>> list(src), src.changed_since('0')
([], False)
```

#### changed_since(token, key=None)

Whether the current [`revision()`](#openloops.ClaudeCodeTranscripts.revision) differs from *token*.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### path_of(key)

The transcript file backing *key*.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

#### revision(key=None)

An opaque change token: for one session, or for the whole collection.

For a single key it is the transcript’s modification time in nanoseconds. For
the collection it is a hash over every `(key, mtime)` pair, so a token can
be compared without holding the whole index.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### scratchpad_marker *= '-private-tmp'*

Project-directory names starting with this are scratchpads, not work.

### *exception* openloops.CredentialFound(pattern_name, offset, , where='')

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when text about to be written matches a credential pattern.

The message names the pattern class and the offset. It never contains the matched
text: an exception that quotes a secret has moved the secret into a log file.

### *class* openloops.Digest(key, text, session_key, source, state, verdict=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One rendered digest: its store key and its markdown text.

`text` is a pure function of the [`Session`](#openloops.Session) it was built from. It carries
no generation timestamp, which is what lets the regeneration test in
`tests/test_sync.py` compare bytes rather than fields.

#### as_dict()

JSON-ready form (without the markdown body).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *class* openloops.Exchange(session, uuid, origin, asked_at, prompt, reply='', replied_at='', sender='', questions=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One prompt a session received and the reply its turn ended with.

`uuid` is the prompt record’s own id, stable for the life of the transcript.
`origin` is `HUMAN`, `PEER` (`sender` names the session) or
`SYSTEM` (a notification, a headless `-p` run, or nothing typed).
`reply` is the last assistant text before the next prompt, `''` while the turn
is still running or ended without words. `questions` is filled for a human
prompt only.

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *exception* openloops.GhUnavailable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The world could not be read: no `gh`, no credentials, no network, a timeout.

Raised only by the listing path, and never propagated to a caller of [`owed()`](#openloops.owed) —
it becomes `listed: False` plus an `error`, which every surface must render as
`?`. Turning it into an empty list would be the one unrecoverable bug here.

### *class* openloops.Locator(type, url='', text='', at='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A typed, human-readable pointer to something outside the digest.

The exportable half of ADR-015’s evidence split: a short typed reference that
another tool (or a person) can resolve, never a content hash and never a byte
offset into a file that is garbage-collected after thirty days.

```pycon
>>> Locator("pr", url="https://github.com/o/r/pull/1").as_dict()["type"]
'pr'
```

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* openloops.Obligation(repo, number, title, url, created, age_days, state='open', verify='', predicate='', evidence='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One open `manual-task` issue, with the verdict its own predicate returned.

`verify` is the `**Verify:**` field exactly as the issue wrote it and
`predicate` is the runnable command extracted from it — both are carried so a
reader can disagree with `state` rather than absorb it.

```pycon
>>> Obligation('acme/widget', 7, 't', 'u', '2026-01-01T00:00:00Z', 3).state
'open'
```

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *class* openloops.PredicateOutcome(status, output='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What evaluating one predicate produced.

`status` is the shell exit status, or `None` for “could not be run” — the
difference between an answer and the absence of one.

```pycon
>>> PredicateOutcome(0).status, PredicateOutcome(None, 'timed out').output
(0, 'timed out')
```

### *class* openloops.Session(key, title='', ai_title='', cwd='', project='', git_branches=(), started_at='', ended_at='', last_turn_at='', last_user_prompt='', last_prompt_at='', last_assistant_text='', recap='', recap_at='', compaction='', compaction_at='', turn_count=0, model='', ended_mid_turn=False, ended_with_error=False, locators=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one Claude Code session’s persisted state says, parsed but not judged.

Every field is a *fact read from the transcript*, never an inference about the
world. `last_assistant_text` is what the session said last; it is not a claim
that the thing it describes is still true.

`key` is the session id. It is the only identifier openloops uses, and per
ADR-014 nothing in the model hangs off it: a digest is a view keyed by session,
not a record owned by one.

#### as_dict()

JSON-ready form (`asdict` already flattens the nested locators).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### compaction *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

The context-compaction summary, a different and much longer thing than the recap,
covering only the part of the session that preceded it.

#### ended_mid_turn *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

The transcript’s final conversational record is an unanswered human prompt, or an
assistant tool call whose result never arrived — i.e. the session stopped mid-turn.

#### ended_with_error *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

The last thing the session said is a usage-limit or API-error banner rather than
the assistant’s own words: it was cut off, not finished.

#### *property* git_branch *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The branch the session opened on — the one that names it, when several ran.

A third of sessions touch more than one branch, so a single value is a summary
rather than a fact; `git_branches` is what carries the truth.

#### *property* heading *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

its description, else its label.

* **Type:**
  What to call this session in prose

#### recap *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

Claude Code’s own end-of-turn recap (its `away_summary` record) — one to three
sentences it wrote itself, usually naming what it thought came next. Reading it
is retention, not duplication: it was generated and billed once already, and it
disappears with the transcript.

### *class* openloops.Verdict(state, reason, cues=(), at='', confidence='high')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A loop-state judgement, with the rule that produced it and the cues it saw.

`reason` and `cues` exist so a reader can disagree. A classification whose
grounds are not shown is an assertion, and openloops does not make assertions
about sessions — it reports what they said and why it read them that way.

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### at *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

When the text this verdict was read from was written. Usually the closing turn,
but the recap rule reads text written later, and a heading dated to the wrong
moment is exactly the thing ADR-005 forbids.

#### confidence *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'high'*

`"high"` when a rule actually fired, `"low"` when the state is the default
and nothing in the transcript supported it. A classifier that hides which of the
two it did is claiming knowledge it does not have.

### openloops.agents_dir()

The bundled subagent definitions, inside the installed package.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.asks_the_human(text, , ask_cues=('want me to', 'do you want', 'would you like', 'shall i', 'should i', 'let me know', 'say the word', 'your call', 'up to you', 'over to you', 'which would you', 'tell me which', "if you'd prefer", 'if you would prefer', 'needs your input', 'needs your review', 'needs your decision', 'needs your go-ahead', 'needs your call'), chars=1200)

The ask cues in the closing lines, if those lines put a question to the reader.

The primitive a retrospective measurement uses to ask “did this session end with a
question directed at the human” — defined once, here, rather than twice.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> asks_the_human('I fixed it. Want me to open the PR?')
('want me to',)
>>> asks_the_human('Was it broken? Yes, and I fixed it.')
()
>>> asks_the_human('All done.')
()
```

### openloops.blocked(, resolve=True, owners=None, repos=(), query='is:blocked', limit=50, timeout=30.0, now=None, issues_source=None, blockers_source=None)

Open issues that carry a blocker edge, with every edge resolved.

The row that matters sorts first: `unblocked` — every blocker closed, the work
free to proceed, and nothing anywhere has said so. `blocked` rows name what they
are waiting on, foreign repository included. `unknown` means the edges could not
be read, and it is never rounded into either of the others.

`owners=` scopes the fleet-wide search (default: `openloops.obligations.
configured_owners()`, the same fleet `ol owed` answers about, so two commands never
quietly disagree about which repositories exist). `repos=` instead enumerates the
repositories you name exactly, which is the audit path.

`resolve=False` lists candidates without spending one API call each; every row
then reads `unknown`, because that is what is true about it.

Two seams, each one keyword argument, each defaulting to a real implementation:
`issues_source=` (defaults to [`gh_blocked_candidates()`](#openloops.gh_blocked_candidates); a list of dicts
substitutes) and `blockers_source=` (defaults to [`gh_blocked_by()`](#openloops.gh_blocked_by); a mapping
from `'owner/name#number'` to edges, or any callable of `(repo, number)`,
substitutes). With both injected this reaches no network and needs no `gh`.

Returns one envelope, never a bare list, because a reader has to be able to tell
“nothing is waiting” from “I could not find out”:

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

`listed`
: `False` when *discovery itself* failed. Every surface must render that as
  `?`. The counts are zeros and they mean nothing.

`resolved`
: whether edges were resolved at all.

`truncated`
: the candidate list saturated `limit`, so the counts are a floor.

`counts`
: `unblocked` / `blocked` / `unknown`, plus `cross_repo`, `candidates`
  (how many discovery offered), `without_edges` (how many of those the
  dependency graph disagreed about) and `total` (how many rows).

`rows`
: one dict per issue, with every key in `BLOCKED_FIELDS`.

```pycon
>>> report = blocked(issues_source=[], blockers_source={})
>>> report['listed'], report['counts']['total'], report['rows']
(True, 0, [])
```

Discovery that could not run is not “nothing is waiting”:

```pycon
>>> def broken(**query):
...     raise GhUnavailable('gh: not logged in')
>>> report = blocked(issues_source=broken)
>>> report['listed'], report['error'], report['counts']['total']
(False, 'gh: not logged in', 0)
```

### openloops.classify(session, , ask_cues=('want me to', 'do you want', 'would you like', 'shall i', 'should i', 'let me know', 'say the word', 'your call', 'up to you', 'over to you', 'which would you', 'tell me which', "if you'd prefer", 'if you would prefer', 'needs your input', 'needs your review', 'needs your decision', 'needs your go-ahead', 'needs your call'), defer_cues=('still open', 'still owed', 'still outstanding', 'still pending', 'next step', 'next session', 'left off', 'waiting for you', 'waiting on', 'blocked on', 'blocked by', 'handoff', 'hand-off', 'pick it up', 'pick this up', 'pick that up', 'i left it', 'not yet done', 'not yet merged', 'not yet posted', 'open question', 'unresolved', 'i could not', "i couldn't", 'was unable to', 'were unable to', 'did not finish', "didn't finish", 'needs a human', 'needs you', 'still needs', "you'll need to", 'you will need to', 'requires you to'), close_cues=('nothing half-finished', 'nothing pending', 'nothing is pending', 'nothing left', 'nothing is blocking', 'nothing blocking', 'nothing to clean', 'nothing else outstanding', 'nothing outstanding', 'nothing further', 'no next action', 'no further action', 'no action needed', 'safe to close', 'safe to exit', "you're all set", 'you are all set', 'all done', 'everything is done', 'everything is green', 'everything is verified', 'not unfinished business', 'ready to close'), chars=1200)

Read a session’s loop state from its own last turn.

* **Return type:**
  [`Verdict`](openloops.base.md#openloops.base.Verdict)

```pycon
>>> from openloops.base import Session
>>> classify(Session(key='s', ended_with_error=True)).state
'open'
>>> v = classify(Session(key='s', last_assistant_text='Blocked on your deploy key.'))
>>> v.state, v.cues, v.confidence
('open', ('blocked on',), 'high')
```

### openloops.data_dir()

The project’s data root. Override with `OPENLOOPS_DATA_DIR`.

Per-kind subdirectories hang off this; nothing is written directly into it, so a
later kind of data needs no second migration.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.default_source(directory=None)

This machine’s label for its digest folder. Override with `OPENLOOPS_SOURCE`.

A short, filename-safe name. It exists so several machines can sync digests into one
place without colliding — not to identify anybody, though on a machine whose
hostname was never changed it may well do; every `ol sync` prints it, and
`OPENLOOPS_SOURCE` overrides it.

**It is sticky.** The hostname is a *seed*, written once to a file under the state
directory and read thereafter. macOS rewrites the hostname when it joins a network
where the name collides — appending `-2`, `-3` — and a label that moved would
fork the store into two complete copies with no dedup and no warning.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.digest_key(source, state, session_key)

The store key for one session’s digest.

Both segments are validated, not just the state. `transcript_source=` is a seam
whose documented purpose is “another machine’s synced transcripts”, so a session id
can come from a listing this process did not produce — and a key containing `..`
would make a file-backed store write outside its own root while `sync` reported
success. Validating here means every backend inherits the check.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> digest_key('mac', 'archive', 's1')
'mac/archive/s1.md'
>>> digest_key('mac', 'open', '../../etc/passwd')
Traceback (most recent call last):
    ...
ValueError: session key must be a single safe path segment, got '../../etc/passwd'
```

### openloops.digests_store(rootdir=None)

The default `digests_store`: markdown files under the data root.

Any `MutableMapping[str, str]` works in its place — a plain `dict` for tests,
a git-synced directory, an S3-backed store. The keys are what carry the layout, so
a different backend gets the same `{source}/{state}/{session}.md` structure for
free.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> store = digests_store(rootdir='/tmp/openloops-doctest-store')
>>> store['demo/open/s1.md'] = '# hi'
>>> sorted(store)
['demo/open/s1.md']
>>> del store['demo/open/s1.md']
```

### openloops.exchanges(records, , key='')

Every prompt of a transcript’s main thread, in order, each with its turn’s reply.

Records are ordered by timestamp (a transcript’s lines are not always written in
order), ties kept in file order. Sub-agent sidechains are left out: their “prompts”
were written by the session, not to it.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Exchange`](#openloops.Exchange), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> recs = [
...     {"type": "user", "sessionId": "s", "uuid": "u1", "timestamp": "T1",
...      "message": {"content": "Ship it. Is the cache still warm?"}},
...     {"type": "assistant", "timestamp": "T2", "message": {"content": [
...         {"type": "text", "text": "Shipped. Yes, warm for an hour."}]}},
... ]
>>> [(e.uuid, e.questions, e.reply) for e in exchanges(recs)]
[('u1', ('Is the cache still warm?',), 'Shipped. Yes, warm for an hour.')]
```

### openloops.gh_blocked_by(repo, number, , timeout=30.0)

The default `blockers_source`: the blocker edges out of one issue.

One request per issue — the N+1 [`blocked()`](#openloops.blocked) bounds with `limit=`. Returns the
rows GitHub sends, unparsed and unjudged; `_verdict()` is what reads a state
out of them. An issue with no edges answers `[]`, which is an answer.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.gh_blocked_candidates(, owners=(), repos=(), query='is:blocked', limit=50, timeout=30.0)

The default `issues_source`: open issues that *may* carry a blocker edge.

`repos=` chooses the exact per-repository enumeration; otherwise `owners=`
drives one fleet-wide search. Both return rows shaped the way `gh search issues`
shapes them — `createdAt`, `number`, `repository`, `title`, `url` — so
everything downstream reads one shape. Which one to use, and what each costs and
misses, is the “Discovery is a candidate list” section of this module’s docstring.

A large repository can take longer than `timeout` to paginate; that is a
[`GhUnavailable`](#openloops.GhUnavailable), which reads `?`, not an empty answer.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.gh_issues(, owners, label='manual-task', state='open', limit=50, timeout=30.0)

The default `issues_source`: the open `manual-task` issues, from `gh`.

This is a *filtered* search, not an enumeration — the label is applied server-side
and the result is capped — which is the only form of search this package is allowed
to use. Walking a whole fleet’s issues through the search API silently returns wrong
answers past its first thousand results; that job belongs to per-repo listing.

Returns whatever `gh` returned, unparsed and unjudged: a list of dicts with
`createdAt`, `number`, `repository`, `title`, `url` and `body`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.headline_counts(owed, blocked, sessions)

The four figures across the top of the page. `None` is `?`, never a zero.

Shared by the masthead and by [`openloops.tools.dashboard()`](openloops.tools.md#openloops.tools.dashboard), so the number a
caller reads back is the number the page printed.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

```pycon
>>> headline_counts({'listed': True, 'counts': {'open': 2}, 'rows': []},
...                 {'listed': False}, [])['free_to_proceed'] is None
True
```

### openloops.install_skills(, target=None, only=None, copy=False, force=False, dry_run=False)

Make the bundled skills and subagent visible to an agent host. Idempotent.

Links each one into `target` (default: `CLAUDE_CONFIG_DIR` or `~/.claude`) so
that upgrading the package upgrades the skill. `copy=True` takes a copy instead,
which is also what happens by itself where symlinks are unavailable.

Returns the plan it carried out – one row per asset, each carrying its verdict and
the reason for it. `dry_run=True` returns the same plan having touched nothing,
which is the only way to see what a run would do *before* it does it.

Nothing that is already there is overwritten: an occupied destination reads
`conflict` and is left exactly as it was until `force=True`.

`only=` installs a subset by name. The case it exists for: you already have your
own capture skill, adapted to your own fleet, and a second one competing for the same
triggers is worse than either alone – so take the reader and the subagent and leave
the capture skill out.

* **Return type:**
  dict[str, Any]

```pycon
>>> plan = install_skills(target='/nonexistent/host', only=['openloops'], dry_run=True)
>>> [row['name'] for row in plan['actions']]
['openloops']
```

```pycon
>>> plan = install_skills(target='/nonexistent/host', dry_run=True)
>>> plan['counts']['install'], plan['dry_run']
(3, True)
>>> sorted({row['action'] for row in plan['actions']})
['install']
```

### openloops.ls(, state='open', source=None, project=None, confidence=None, limit=20, digests_store=None)

The digests in the store, newest last-turn first.

`state` is `open`, `archive` or `all`. `source`, `project` and
`confidence` narrow by the digest’s own header fields. Each row is that front
matter plus its key.

`confidence='high'` is the one worth knowing about: most sessions land in `open`,
and a good few of those are open only because nothing said otherwise. Filtering to
`high` leaves the ones where the session itself said something.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

```pycon
>>> rows = ls(digests_store={'m/open/s1.md':
...     '---\nsession: s1\nstate: open\nlast_turn: T9\n---\n'})
>>> rows[0]['session'], rows[0]['key']
('s1', 'm/open/s1.md')
```

### openloops.make_digest(session, verdict, , source, aliases=None)

Render, scrub, and key one digest.

Raises [`CredentialFound`](openloops.egress.md#openloops.egress.CredentialFound) when the rendered text matches a
credential pattern — deliberately, so the caller skips that session loudly rather
than writing a secret into a store that may be synced.

* **Return type:**
  [`Digest`](openloops.base.md#openloops.base.Digest)

```pycon
>>> from openloops.base import Session, Verdict
>>> d = make_digest(Session(key='s1'), Verdict('open', 'why'), source='demo')
>>> d.key
'demo/open/s1.md'
```

### openloops.owed(, verify=True, owners=None, trusted_owners=None, label='manual-task', limit=50, timeout=30.0, predicate_timeout=20.0, now=None, issues_source=None, run_predicate=None)

The open `manual-task` obligations, each re-checked against the world.

`verify=False` lists without executing anything; every row that carries a
predicate then reads `unknown`, because that is what is true about it.

`owners=` scopes the search (default: `configured_owners()`).
`trusted_owners=` scopes what may *execute* and defaults to `owners`, so
widening the search never quietly widens what runs — pass it explicitly to search
wider than you trust.

Two seams, each one keyword argument, each defaulting to a real implementation:
`issues_source=` (defaults to [`gh_issues()`](#openloops.gh_issues); a list of dicts substitutes) and
`run_predicate=` (defaults to [`shell_predicate()`](#openloops.shell_predicate); any callable from command
to exit status substitutes). With both injected this reaches no network and needs no
`gh`.

Returns one envelope, never a bare list, because a reader has to be able to tell
“nothing is owed” from “I could not find out”:

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

`listed`
: `False` when the *listing itself* failed. Every surface must render that as
  `?`. The counts are zeros and they mean nothing.

`checked`
: whether predicates were evaluated at all.

`truncated`
: the result set saturated its own cap, so the count is a floor.

`counts`
: `open` / `discharged` / `unknown` / `with_predicate` / `total`.

`rows`
: one dict per obligation, with every key in `OBLIGATION_FIELDS`.

```pycon
>>> report = owed(issues_source=[], run_predicate=lambda command: 0)
>>> report['listed'], report['counts']['total'], report['rows']
(True, 0, [])
```

A listing that could not run is not “nothing owed”:

```pycon
>>> def broken(**query):
...     raise GhUnavailable('gh: not logged in')
>>> report = owed(issues_source=broken)
>>> report['listed'], report['error'], report['counts']['total']
(False, 'gh: not logged in', 0)
```

### openloops.parse_session(records, , key='')

Read one transcript’s records into a [`Session`](openloops.base.md#openloops.base.Session).

Pure: same records in, same session out. Everything it reports is a fact about the
document — no inference, no judgement, and nothing about running processes.

Three details are corpus-driven rather than obvious, and getting them wrong
mislabels a large fraction of real sessions:

- \*\*Start and end come from `min`/`max` over every timestamp\*\*, not from the
  first and last line. Transcript lines are not written in timestamp order; on real
  data the first line holds the earliest timestamp only about four times in five.
- \*\*The project comes from the *first* record’s `cwd`.\*\* Four sessions in five
  visit more than one working directory (scratchpads, sibling repos, task dirs), and
  the last or most-frequent one names a different repository about half the time.
- **Branches are a tuple.** A third of sessions touch more than one.

```pycon
>>> recs = [
...     {"type": "user", "sessionId": "s1", "cwd": "/w/proj", "timestamp": "T1",
...      "gitBranch": "main",
...      "message": {"role": "user", "content": [{"type": "text", "text": "do it"}]}},
...     {"type": "assistant", "sessionId": "s1", "timestamp": "T2",
...      "message": {"role": "assistant", "model": "m",
...                  "content": [{"type": "text", "text": "done"}]}},
... ]
>>> s = parse_session(recs)
>>> s.key, s.project, s.turn_count, s.last_assistant_text
('s1', 'proj', 1, 'done')
>>> s.started_at, s.ended_at, s.git_branch, s.ended_mid_turn
('T1', 'T2', 'main', False)
```

* **Return type:**
  [`Session`](openloops.base.md#openloops.base.Session)

### openloops.parse_verify(body)

`(predicate, verify_text)` for an issue body. Both are `''` when absent.

The predicate is the first code span in the field. Prose with no code span – the
documented “no predicate is possible here” answer – yields no command, and the
prose is kept so the row can say *why* rather than merely say nothing.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> parse_verify('**Verify:** `test -f x`')
('test -f x', '`test -f x`')
>>> parse_verify('no such field here')
('', '')
```

A field that says no predicate is possible yields no command \*\*even when its prose
contains a code span\*\* – the documented wording mentions `gh` and `true` naturally,
and both exit 0, which would report a live obligation as done:

```pycon
>>> parse_verify('**Verify:** none possible - no `gh` query observes a decision.')
('', 'none possible - no `gh` query observes a decision.')
```

A quoted example of the format is not this issue’s own predicate:

```pycon
>>> body = chr(10).join(['```', '**Verify:** `quoted`', '```', '**Verify:** `real`'])
>>> parse_verify(body)[0]
'real'
```

An unterminated code span is not a command – it is a malformed field, and saying so
is the difference between a row that reads `?` and one that silently reads open:

```pycon
>>> parse_verify('**Verify:** `echo one &&' + chr(10) + 'echo two`')
('', '`echo one &&')
```

### openloops.question_sentences(text)

The sentences of a person’s prompt that ask something, in order, at most
`MAX_QUESTIONS`.

A sentence asks when it ends with `?` or opens the way a question does (“why”,
“is there”, “I wonder”), and is not a request phrased as one (“can you fix it?”).
Code blocks, quoted lines and table rows are skipped.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> question_sentences("Can you add a test? Could you explain why it failed?")
('Could you explain why it failed?',)
>>> question_sentences("> Why is it slow?\nok?\nwhy does the page load twice")
('why does the page load twice',)
```

### openloops.render(session, verdict, , source)

The markdown for one digest. Pure, dated, and bounded.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from openloops.base import Session, Verdict
>>> s = Session(key='s1', project='proj', started_at='T0', last_turn_at='T1',
...             last_assistant_text='Shipped it.', turn_count=3)
>>> verdict = Verdict('archive', 'its closing lines declare it finished')
>>> text = render(s, verdict, source='demo')
>>> text.splitlines()[0]
'---'
>>> 'state: archive' in text
True
>>> render(s, verdict, source='demo') == text     # pure: same in, same out
True
```

### openloops.render_dashboard(owed, blocked, sessions, , made_at=None, source='', title='Open Loops Board', max_sessions=40, standalone=True, aliases=None)

The three envelopes as one self-contained HTML page. No network, no script.

`owed` and `blocked` are the envelopes [`openloops.owed()`](#openloops.owed) and
[`openloops.blocked()`](#openloops.blocked) return; `sessions` is the list [`openloops.ls()`](#openloops.ls)
returns. All three may be empty mappings, and an envelope whose `listed` is
`False` renders as `?` throughout rather than as zero.

`made_at` is the moment the snapshot was taken and is printed in the largest type
on the page. It defaults to now, but a caller that wants a byte-stable page passes
it — this is the one module in openloops that stamps a generation time, and it does
so because the whole claim of the page is *when*.

`standalone` wraps the output in a document scaffold for a file you open yourself.
Pass `False` for a host that supplies its own `<head>` — a published artifact
does — and the same page comes back as title, styles and content only.

`max_sessions` bounds the in-flight register; the true total is stated either way.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> page = render_dashboard(
...     {'listed': False, 'error': 'gh: not logged in', 'counts': {}},
...     {'listed': True, 'counts': {'unblocked': 0, 'total': 0}, 'rows': []},
...     [], made_at='2026-01-01T00:00:00Z')
>>> 'gh: not logged in' in page and 'could not' in page
True
```

### openloops.retained(store, sessions, , source=None)

Digest keys whose session no longer has a transcript — the retention surplus.

These are what makes openloops a retention device rather than a view: Claude Code
garbage-collects transcripts, and a digest outlives the thing it was derived from.
[`sync()`](#openloops.sync) never removes them, and they are the one part of the store that a
from-scratch rebuild does not reproduce.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> retained({'m/open/a.md': '', 'm/open/b.md': ''}, {'a': None})
['m/open/b.md']
```

### openloops.scrub(text, , aliases=None, where='')

Rewrite paths and raise on credentials. The only way text leaves openloops.

`where` is a caller-supplied label (a session id, a file name) carried into the
exception so a failed run can say *which* input tripped, without quoting it.

The path check runs on the **output**, not the input, because `aliases` is
caller-supplied: a rewrite can in principle produce a home path as easily as remove
one, and a postcondition that is only true of benign inputs is not a postcondition.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> scrub("built /nowhere/proj/x", aliases={"/nowhere/proj": "$PROJ"})
'built $PROJ/x'
```

### openloops.shell_predicate(command, , timeout=20.0)

The default `run_predicate`: run the command in a subshell, bounded in time.

The exit status is the answer and nothing else is interpreted. Anything that is not
an exit status — a timeout, a shell that would not start — comes back as
`status=None`, which is `unknown`, which is `?`.

* **Return type:**
  [`PredicateOutcome`](openloops.obligations.md#openloops.obligations.PredicateOutcome)

```pycon
>>> shell_predicate('exit 0').status
0
>>> shell_predicate('exit 3').status
3
>>> shell_predicate('   ').status is None
True
```

### openloops.show(session, , source=None, digests_store=None)

One digest in full, found by session id or by a unique prefix of one.

An exact id always wins over a prefix, so a session whose id happens to be a prefix
of another stays reachable. `source` narrows a store that several machines write
into, where the same session can legitimately appear more than once.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

```pycon
>>> store = {'m/open/abcdef.md': '---\nsession: abcdef\n---\nbody'}
>>> show('abc', digests_store=store)['key']
'm/open/abcdef.md'
```

### openloops.skills_dir()

The bundled skills directory, inside the installed package.

`Path(__file__).parent` rather than a configured root, so this answers correctly
from a wheel, an editable install, a zip and a virtualenv without being told which.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.state_dir()

Where per-machine caches and job logs go. Override with `OPENLOOPS_STATE_DIR`.

Deliberately not under [`data_dir()`](#openloops.data_dir): everything here is disposable, and keeping
it elsewhere means “clear the cache” can never be mistyped into “delete the digests”.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.status(, source=None, since_days=None, digests_store=None, transcript_source=None)

Where everything is, how much of it there is, and how stale the cache is.

Reports the cache’s age because a read served from a cache that nothing has
refreshed is the failure openloops is built to avoid — a periodic job that died
leaves a confident, months-old answer behind, and the only defence is saying how
old the answer is.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.sync(, transcript_source=None, digests_store=None, source=None, since_days=None, state_dir=None, force=False)

Bring the digest store up to date with the sessions, and say what changed.

`force` ignores the cache and re-derives everything; the result must be identical,
which is what makes it safe to suggest when someone suspects a stale digest.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

```pycon
>>> from openloops.base import STATES, Session
>>> sessions = {'s1': Session(key='s1',
...                               last_assistant_text='Shipped it. Nothing is pending.')}
>>> store = {}
>>> r = sync(transcript_source=sessions, digests_store=store, source='demo',
...          state_dir='/tmp/openloops-doctest-state', force=True)
>>> r['written'], sorted(store)
(1, ['demo/archive/s1.md'])
>>> sync(transcript_source=sessions, digests_store=store, source='demo',
...      state_dir='/tmp/openloops-doctest-state', force=True)['written']
0
```

### Modules

| [`base`](openloops.base.md#module-openloops.base)               | Data structures shared across openloops: what a session is, and what a digest is.       |
|-------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`blockers`](openloops.blockers.md#module-openloops.blockers)       | The other kind of open loop: the one that points at a repository, not at a person.      |
| [`dashboard`](openloops.dashboard.md#module-openloops.dashboard)     | One page you can look at instead of reading three command outputs.                      |
| [`digest`](openloops.digest.md#module-openloops.digest)           | Rendering one session into one dated markdown digest.                                   |
| [`egress`](openloops.egress.md#module-openloops.egress)           | The egress choke point: nothing leaves openloops carrying a home path or a secret.      |
| [`job`](openloops.job.md#module-openloops.job)                 | The periodic job: launchd runs `ol sync`, writes, and exits.                            |
| [`obligations`](openloops.obligations.md#module-openloops.obligations) | What you still owe your agents — re-checked against the world before it is shown.       |
| [`skills`](openloops.skills.md#module-openloops.skills)           | The agent-facing surface: two skills, one subagent, and the command that installs them. |
| [`store`](openloops.store.md#module-openloops.store)             | Where digests live, and where the change-detection cache lives — two different things.  |
| [`tools`](openloops.tools.md#module-openloops.tools)             | The package's single list of operations: plain functions, JSON-ready dicts.             |
| [`transcripts`](openloops.transcripts.md#module-openloops.transcripts) | The default `transcript_source`: a direct reader of Claude Code's on-disk state.        |
