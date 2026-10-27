# openloops.tools

The package’s single list of operations: plain functions, JSON-ready dicts.

Every surface openloops has or might grow — the `ol` command today, an MCP server or
an HTTP endpoint later — dispatches from this module and nothing else. The functions
here know nothing about argument parsers, transports or agent hosts; they take flat
serialisable arguments and return flat serialisable results, and printing is somebody
else’s job.

Keeping one list is what stops two surfaces from drifting apart. A parity test between
two surfaces is a sign that there are two implementations, and there is one here.

### Module Attributes

| [`ROW_FIELDS`](#openloops.tools.ROW_FIELDS)   | The keys every [`ls()`](#openloops.tools.ls) row carries, whatever the digest happens to record.   |
|---------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`sync`](#openloops.tools.sync)(\*[, source, since_days, force, ...])        | Read what changed in the sessions and write the digests.                                  |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`ls`](#openloops.tools.ls)(\*[, state, source, project, confidence, ...]) | The digests in the store, newest last-turn first.                                         |
| [`show`](#openloops.tools.show)(session, \*[, source, digests_store])        | One digest in full, found by session id or by a unique prefix of one.                     |
| [`status`](#openloops.tools.status)(\*[, source, since_days, ...])             | Where everything is, how much of it there is, and how stale the cache is.                 |
| [`owed`](#openloops.tools.owed)(\*[, verify, owners, trusted_owners, ...])   | What you still owe your agents, with each obligation re-checked against the world.        |
| [`blocked`](#openloops.tools.blocked)(\*[, resolve, owners, repos, query, ...]) | What your repositories are waiting on — and what is no longer waiting.                    |
| [`dashboard`](#openloops.tools.dashboard)(\*[, verify, resolve, owners, ...])     | All three answers as one self-contained HTML page, for looking at rather than reading.    |
| [`published`](#openloops.tools.published)(\*[, limit, session, source])           | What your agents handed you lately: recently published annals documents, per session.     |
| [`board_gather`](#openloops.tools.board_gather)(\*[, owners, exclude_owners, ...])   | Every open item that asks something of you, across owners: the board's input.             |
| [`board_classify`](#openloops.tools.board_classify)(\*, candidates[, enriched, out])   | Task records: the heuristic classifier over gathered candidates, overlaid by richer ones. |
| [`board_build`](#openloops.tools.board_build)(\*, records, out_dir[, ...])          | Write the phone task board (page, `tasks.json`, `runs.json`) into `out_dir`.              |

### openloops.tools.ROW_FIELDS *= ('session', 'source', 'state', 'title', 'ai_title', 'project', 'branches', 'started', 'ended', 'last_turn', 'turns', 'model', 'confidence', 'verified')*

The keys every [`ls()`](#openloops.tools.ls) row carries, whatever the digest happens to record.

### openloops.tools.blocked(, resolve=True, owners=None, repos=None, query='is:blocked', limit=50, timeout=30.0, issues_source=None, blockers_source=None)

What your repositories are waiting on — and what is no longer waiting.

The sibling of [`owed()`](#openloops.tools.owed): an obligation points at a person, a blocker edge
points at another repository, and both are commitments nothing is watching. Lists
the open issues carrying a `blocked_by` dependency across `owners` (or exactly
the `repos` you name), resolves every edge, and reports three states:
`unblocked` (every blocker closed — the work is free and nobody has been told),
`blocked` (naming the foreign repository it waits on) and `unknown` (nothing
could be resolved). Nothing is ever closed, relabelled or written; see
[`openloops.blockers`](openloops.blockers.html.md#module-openloops.blockers) for what discovery costs and what it is measured to miss.

The result is an envelope rather than a list, because `listed=False` — discovery
itself failed — must not be readable as “nothing is waiting”.

```pycon
>>> report = blocked(issues_source=[], blockers_source={})
>>> report['listed'], report['counts']['total']
(True, 0)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.board_build(, records, out_dir, candidates=None, run_specs=None, run_extras=None, title='Phone Task Board', session=None, read_only_orgs=None, machine=None)

Write the phone task board (page, `tasks.json`, `runs.json`) into `out_dir`.

`records` are task-record JSON files (globs allowed); `candidates` supply the
creation dates; `run_specs` replaces the packaged run specs and `run_extras` (a
JSON object keyed by run) overlays deployment-specific prompts and tables. Writes
only into `out_dir`; publishing and the receiving side are the skill’s job.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.board_classify(, candidates, enriched=None, out=None)

Task records: the heuristic classifier over gathered candidates, overlaid by richer ones.

`candidates` are JSON files from [`board_gather()`](#openloops.tools.board_gather); `enriched` are record
files written by the classifier brief (globs allowed), which win over the heuristic
record for the same item. `out` writes the merged records there.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.board_gather(, owners=None, exclude_owners=None, exclude_repos=None, label='manual-task', searches=None, review_prs=False, limit=1000, timeout=30.0, out=None, run_gh=None)

Every open item that asks something of you, across owners: the board’s input.

Sweeps the `label` (`manual-task`) per owner with no 50-row cap, plus the named
`searches` (`decide`, `needs-user`) and, with `review_prs`, the PRs waiting
on your review. `out` also writes the envelope there as JSON. Read-only.

```pycon
>>> board_gather(owners=['acme'], run_gh=lambda args, *, timeout: '[]')['listed']
True
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.dashboard(, verify=True, resolve=True, owners=None, repos=None, limit=50, candidate_limit=50, max_sessions=40, title='Open Loops Board', standalone=True, path=None, made_at=None, owed_report=None, blocked_report=None, sessions=None, digests_store=None, published_report=None, published_limit=50)

All three answers as one self-contained HTML page, for looking at rather than reading.

Runs [`owed()`](#openloops.tools.owed), [`blocked()`](#openloops.tools.blocked) and [`ls()`](#openloops.tools.ls), then renders
[`openloops.dashboard.render_dashboard()`](openloops.dashboard.html.md#openloops.dashboard.render_dashboard) over what they returned. The page is a
**snapshot**: it stamps the moment it was made and states, in its largest type, that
it has checked nothing since — because a published page cannot. Nothing is written
to GitHub, here or anywhere in openloops.

`path` also writes the page there, scrubbed, and reports where it went.
`standalone=False` returns the same page without the document scaffold, for a host
that supplies its own `<head>`.

Each read is a seam: pass `owed_report=`, `blocked_report=`, `sessions=` or
`published_report=` and that one is not performed. With all four passed this
reaches no network and needs no `gh` or `annals`, which is how the tests run.
The “Handed to you” register (recent annals documents per session) comes from
[`published()`](#openloops.tools.published); pass `published_report=False` to leave it off the page.

`counts` comes back alongside the page and carries `null` — not `0` — for any
figure that could not be established, so a caller reading the JSON is held to the
same three-state rule as a reader looking at the page.

```pycon
>>> result = dashboard(owed_report={'listed': True, 'counts': {'open': 0}, 'rows': []},
...                    blocked_report={'listed': False, 'error': 'no gh'},
...                    sessions=[], made_at='2026-01-01T00:00:00Z')
>>> result['counts']['free_to_proceed'] is None, result['counts']['unknown'] is None
(True, True)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.ls(, state='open', source=None, project=None, confidence=None, limit=20, digests_store=None)

The digests in the store, newest last-turn first.

`state` is `open`, `archive` or `all`. `source`, `project` and
`confidence` narrow by the digest’s own header fields. Each row is that front
matter plus its key.

`confidence='high'` is the one worth knowing about: most sessions land in `open`,
and a good few of those are open only because nothing said otherwise. Filtering to
`high` leaves the ones where the session itself said something.

```pycon
>>> rows = ls(digests_store={'m/open/s1.md':
...     '---\nsession: s1\nstate: open\nlast_turn: T9\n---\n'})
>>> rows[0]['session'], rows[0]['key']
('s1', 'm/open/s1.md')
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.tools.owed(, verify=True, owners=None, trusted_owners=None, label='manual-task', limit=50, timeout=30.0, predicate_timeout=20.0, issues_source=None, run_predicate=None)

What you still owe your agents, with each obligation re-checked against the world.

Lists the open `manual-task` issues across `owners` and evaluates the
`**Verify:**` predicate each one carries, reporting three states: `open`,
`discharged` (the predicate returned 0 — done, but the issue is still open) and
`unknown` (nothing could be checked). Nothing is ever closed, relabelled or
written; see [`openloops.obligations`](openloops.obligations.html.md#module-openloops.obligations) for the trust boundary that evaluating a
predicate crosses, and `verify=False` for the way to read without executing.

The result is an envelope rather than a list, because `listed=False` — the query
itself failed — must not be readable as “nothing owed”.

```pycon
>>> report = owed(issues_source=[], run_predicate=lambda command: 0)
>>> report['listed'], report['counts']['total']
(True, 0)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.published(, limit=50, session=None, source=None)

What your agents handed you lately: recently published annals documents, per session.

The sibling of [`owed()`](#openloops.tools.owed), read from the documents sessions published with
`annals publish --session <name>`. Nothing is written. `source` is the seam: the
documents themselves, or a callable returning them; by default `annals ls` is run,
and when annals is absent the result says `listed=False` rather than listing nothing.

```pycon
>>> published(source=[])['listed']
True
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.show(session, , source=None, digests_store=None)

One digest in full, found by session id or by a unique prefix of one.

An exact id always wins over a prefix, so a session whose id happens to be a prefix
of another stays reachable. `source` narrows a store that several machines write
into, where the same session can legitimately appear more than once.

```pycon
>>> store = {'m/open/abcdef.md': '---\nsession: abcdef\n---\nbody'}
>>> show('abc', digests_store=store)['key']
'm/open/abcdef.md'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.status(, source=None, since_days=None, digests_store=None, transcript_source=None)

Where everything is, how much of it there is, and how stale the cache is.

Reports the cache’s age because a read served from a cache that nothing has
refreshed is the failure openloops is built to avoid — a periodic job that died
leaves a confident, months-old answer behind, and the only defence is saying how
old the answer is.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tools.sync(, source=None, since_days=None, force=False, transcript_source=None, digests_store=None, state_dir=None)

Read what changed in the sessions and write the digests. Returns a summary.

`since_days` bounds the scan to recently-modified transcripts; `force`
re-derives everything, which must produce an identical store.

`state_dir` scopes the change-detection cache. It matters because the seams do
not isolate on their own: swapping `transcript_source` for a fixture and leaving
the cache alone writes the fixture’s revisions into the caller’s real one.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
