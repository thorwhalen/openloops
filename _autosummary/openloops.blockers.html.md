# openloops.blockers

The other kind of open loop: the one that points at a repository, not at a person.

An agent working in repo X finds that the real fix belongs in repo Y. It files in Y,
writes a workaround in X, and moves on. Y gets fixed. **X is never told.** Nobody was
blocking, nothing waited on a human, so the loop is invisible to [`openloops.owed()`](openloops.html.md#openloops.owed)
— and the workaround in X quietly becomes architecture, noticeable months later only
when somebody asks why the code looks like that.

GitHub already models the edge, and it is already cross-repo: the
`dependencies/blocked_by` collection on an issue answers with each blocker’s own
repository, number and state. The representation costs nothing and exists today.
**What is missing is the harvest** — nothing notices when a blocker is resolved,
because the edge is queryable, not eventful. Closing an issue in Y emits no event that
anything in X is listening to, exactly as setting a secret emits none that
[`openloops.obligations`](openloops.obligations.html.md#module-openloops.obligations) could hear. This module is that harvest and nothing else.

[`blocked()`](#openloops.blockers.blocked) lists the open issues across a fleet that carry a `blocked_by` edge,
resolves every edge, and reports **three** states — never two:

| `unblocked`   | every blocker is closed. *This is the row that matters*: the work<br/>can proceed and nobody has been told. It sorts first, and it<br/>carries `unblocked_days` — how long it has been free.   |
|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `blocked`     | at least one blocker is still open. The row names which, with the<br/>foreign repository, because “who am I waiting on” is the second<br/>question a reader has.                               |
| `unknown`     | the edges could not be resolved. Displayed as `?`.                                                                                                                                             |

`?` is not a rounding error, it is the whole point. A run that could not reach the
dependency graph must not report a clean board, so nothing here is allowed to collapse
`unknown` into `unblocked` or into `blocked`.

**Nothing here mutates anything.** An `unblocked` row is a finding, not an
instruction: the workaround in X may still be the right code, and only a human knows.
You are shown the edge, the blocker’s state and the date it closed, and you decide.

## Discovery is a candidate list, not an answer

Finding the blocked issues in the first place has two implementations here, and which
runs is decided by whether `repos=` is given.

**Across a fleet** (`owners=`, the default): one `gh search issues` call carrying
GitHub’s own `is:blocked` qualifier. One request answers for every repository, which
is what makes this cheap enough to run at the start of a session. But the qualifier is
a *search index*, and a search index is not the dependency graph. Measured on one real
fleet on 2026-08-27, scoped to three owners: `is:blocked` returned 15 open issues, of
which \*\*10 carried a `blocked_by` edge and 5 carried no dependency edge of any kind\*\*
— not a stale edge, and four of the five carry no sub-issue relation either (the fifth, checked, has two sub-issues, which is a correlation rather than an explanation, since its parent has no dependency edges), simply none. Recall
was perfect on that fleet: all 10 were found, checked against a full per-repository
enumeration of 821 open issues across 148 repositories. Precision was 10/15.

So a candidate is a *candidate*. Every one is re-resolved against
`dependencies/blocked_by`, which is the graph rather than an index of it, and one
with no edge is dropped and counted as `without_edges` — visible in the envelope and
printed by the CLI, because a discovery step that quietly disagrees with reality is the
same class of defect as a count that cannot say `?`. The recall figure is one
measurement on one fleet on one day and nothing here treats it as a guarantee, which
is what the second implementation is for.

**Per repository** (`repos=`): one paginated REST listing per repository, filtered on
the `issue_dependencies_summary` GitHub already returns on every row of it — its
`blocked_by` count is the blockers still open and `total_blocked_by` is all of
them. This reads the dependency counts themselves rather than an index of them, so it
cannot over-report and cannot miss; it is the per-repo enumeration ADR-005
`github-authoritative` requires of anything that must not lose a row, since the
search API is hard-capped at 1000 results. It costs one request per hundred open
issues in each repository you name, so it is the audit, not the daily command.

## The N+1, and what bounds it

Resolving edges is **one API call per candidate** — there is no batch form. `limit=`
is that bound and it defaults to `DFLT_CANDIDATE_LIMIT`; one more than it is
requested, so a candidate list that saturates its own cap comes back `truncated:
True` and every surface says so. When the bound is hit the count is a **floor**, never
a total: rows past the cap are not resolved, not guessed at, and not counted. At the
default that is at most 51 requests against a 5000/hour core limit, which per ADR-005
is read from each response’s own `X-Ratelimit-*` headers rather than from the
rate-limit endpoint — a claim this module keeps by never asking for the number at all.

**Kill criterion** (this ships on an argument, so it names in advance what would retire
it): if, ninety days after this ships, `counts['unblocked']` has never once been
non-zero on a real run, delete it. Its entire reason to exist over `gh search issues
-- 'is:blocked'` is finding the row that became free while nobody watched; with no
such row it is a slower alias that draws a table. Removal is one command — delete this
module and `tests/test_blockers.py`, and drop `blocked` from
`openloops.tools._dispatch_funcs`, from `openloops.__main__._commands` and from
`openloops.__init__`. Nothing imports it, nothing persists, and no other module
changes.

**What this is not.** It is a *reader*, like everything else here. No store, no schema,
no history, no event log, no local copy of the dependency graph: the edge on GitHub
**is** the record. Deleting this module loses no data.

```pycon
>>> from datetime import datetime, timezone
>>> candidates = [
...     {'number': 12, 'title': 'Drop the workaround once the engine lands',
...      'url': 'https://github.com/acme/widget/issues/12',
...      'createdAt': '2026-07-01T00:00:00Z',
...      'repository': {'nameWithOwner': 'acme/widget'}},
...     {'number': 13, 'title': 'Waiting on the parser rewrite',
...      'url': 'https://github.com/acme/widget/issues/13',
...      'createdAt': '2026-08-01T00:00:00Z',
...      'repository': {'nameWithOwner': 'acme/widget'}},
... ]
>>> edges = {
...     'acme/widget#12': [{'number': 15, 'state': 'closed',
...                         'closed_at': '2026-08-20T00:00:00Z',
...                         'repository': {'full_name': 'acme/engine'}}],
...     'acme/widget#13': [{'number': 7, 'state': 'open',
...                         'repository': {'full_name': 'acme/parser'}}],
... }
>>> report = blocked(                    # a dict and a dict: no gh, no network
...     issues_source=candidates,
...     blockers_source=edges,
...     now=datetime(2026, 8, 27, tzinfo=timezone.utc),
... )
>>> report['counts']['unblocked'], report['counts']['blocked']
(1, 1)
>>> for row in report['rows']:
...     print(row['state'], f"{row['repo']}#{row['number']}",
...           ' '.join(b['ref'] for b in row['blockers']))
unblocked acme/widget#12 acme/engine#15 [closed]
blocked acme/widget#13 acme/parser#7 [open]
```

The unblocked row says how long it has been free — the number nobody currently has:

```pycon
>>> report['rows'][0]['unblocked_days']
7
```

A candidate the dependency graph does not agree with is dropped, and the disagreement
is counted rather than hidden:

```pycon
>>> quiet = blocked(issues_source=candidates, blockers_source={},
...                 now=datetime(2026, 8, 27, tzinfo=timezone.utc))
>>> quiet['counts']['without_edges'], quiet['counts']['total']
(2, 0)
```

A run that could not resolve is never a clean board:

```pycon
>>> def unreachable(repo, number):
...     raise GhUnavailable('gh: not logged in')
>>> dark = blocked(issues_source=candidates, blockers_source=unreachable,
...                now=datetime(2026, 8, 27, tzinfo=timezone.utc))
>>> dark['counts']['unknown'], dark['counts']['unblocked']
(2, 0)
```

### Module Attributes

| [`UNBLOCKED`](#openloops.blockers.UNBLOCKED)      | every blocker is closed.                                            |
|-----------------------------------------------------------------|---------------------------------------------------------------------|
| [`BLOCKED`](#openloops.blockers.BLOCKED)        | at least one blocker is still open, and the row names which.        |
| [`BLOCKER_STATES`](#openloops.blockers.BLOCKER_STATES) | The three states, in the order a reader cares about them.           |
| [`BLOCKED_FIELDS`](#openloops.blockers.BLOCKED_FIELDS) | Every key on every row, whatever the issue's edges happened to say. |

### Functions

| [`blocked`](#openloops.blockers.blocked)(\*[, resolve, owners, repos, query, ...])   | Open issues that carry a blocker edge, with every edge resolved.          |
|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`gh_blocked_by`](#openloops.blockers.gh_blocked_by)(repo, number, \*[, timeout])          | The default `blockers_source`: the blocker edges out of one issue.        |
| [`gh_blocked_candidates`](#openloops.blockers.gh_blocked_candidates)(\*[, owners, repos, ...])     | The default `issues_source`: open issues that *may* carry a blocker edge. |

### Classes

| [`BlockedIssue`](#openloops.blockers.BlockedIssue)(repo, number, title, url, ...)    | One open issue that carries blocker edges, with the verdict those edges imply.   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`Blocker`](#openloops.blockers.Blocker)(repo, number[, state, url, closed_at]) | One edge: the issue, in whatever repository it lives, that blocks another.       |

### Exceptions

| [`GhUnavailable`](#openloops.blockers.GhUnavailable)   | The world could not be read: no `gh`, no credentials, no network, a timeout.   |
|------------------------------------------------------------------|--------------------------------------------------------------------------------|

### openloops.blockers.BLOCKED *= 'blocked'*

at least one blocker is still open, and the row names which.

* **Type:**
  Loop state

### openloops.blockers.BLOCKED_FIELDS *= ('repo', 'number', 'title', 'url', 'created', 'age_days', 'state', 'blockers', 'cross_repo', 'unblocked_days', 'evidence')*

Every key on every row, whatever the issue’s edges happened to say. A row shape that
varies by issue makes `row["blockers"]` a coin flip and a JSON schema a lie.

### openloops.blockers.BLOCKER_STATES *= ('unblocked', 'blocked', 'unknown')*

The three states, in the order a reader cares about them. `unknown` is
[`openloops.obligations.UNKNOWN`](openloops.obligations.html.md#openloops.obligations.UNKNOWN): not-checked means the same thing either way.

### *class* openloops.blockers.BlockedIssue(repo, number, title, url, created, age_days, state='unknown', blockers=(), cross_repo=False, unblocked_days=0, evidence='')

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

### *class* openloops.blockers.Blocker(repo, number, state='', url='', closed_at='')

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

JSON-ready form, with [`ref`](#openloops.blockers.Blocker.ref) materialised for surfaces that print it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### *property* ref *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`owner/name#number [state]` — how a blocker is written down.

A `?` in either half is a fact about what could be read, never a shrug: an
edge whose repository the payload did not name says so rather than borrowing
the blocked issue’s own repository and inventing a same-repo dependency.

### *exception* openloops.blockers.GhUnavailable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The world could not be read: no `gh`, no credentials, no network, a timeout.

Raised only by the listing path, and never propagated to a caller of `owed()` —
it becomes `listed: False` plus an `error`, which every surface must render as
`?`. Turning it into an empty list would be the one unrecoverable bug here.

### openloops.blockers.UNBLOCKED *= 'unblocked'*

every blocker is closed. The work can proceed and nobody has been told.

* **Type:**
  Loop state

### openloops.blockers.blocked(, resolve=True, owners=None, repos=(), query='is:blocked', limit=50, timeout=30.0, now=None, issues_source=None, blockers_source=None)

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
`issues_source=` (defaults to [`gh_blocked_candidates()`](#openloops.blockers.gh_blocked_candidates); a list of dicts
substitutes) and `blockers_source=` (defaults to [`gh_blocked_by()`](#openloops.blockers.gh_blocked_by); a mapping
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
: one dict per issue, with every key in [`BLOCKED_FIELDS`](#openloops.blockers.BLOCKED_FIELDS).

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

### openloops.blockers.gh_blocked_by(repo, number, , timeout=30.0)

The default `blockers_source`: the blocker edges out of one issue.

One request per issue — the N+1 [`blocked()`](#openloops.blockers.blocked) bounds with `limit=`. Returns the
rows GitHub sends, unparsed and unjudged; `_verdict()` is what reads a state
out of them. An issue with no edges answers `[]`, which is an answer.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.blockers.gh_blocked_candidates(, owners=(), repos=(), query='is:blocked', limit=50, timeout=30.0)

The default `issues_source`: open issues that *may* carry a blocker edge.

`repos=` chooses the exact per-repository enumeration; otherwise `owners=`
drives one fleet-wide search. Both return rows shaped the way `gh search issues`
shapes them — `createdAt`, `number`, `repository`, `title`, `url` — so
everything downstream reads one shape. Which one to use, and what each costs and
misses, is the “Discovery is a candidate list” section of this module’s docstring.

A large repository can take longer than `timeout` to paginate; that is a
[`GhUnavailable`](#openloops.blockers.GhUnavailable), which reads `?`, not an empty answer.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]
