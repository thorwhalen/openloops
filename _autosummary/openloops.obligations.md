# openloops.obligations

What you still owe your agents — re-checked against the world before it is shown.

When an agent gets blocked on something only you can do — a secret it cannot write, a
permission it does not have, a decision that is yours — it files a `manual-task` issue
in the affected repo and says so in its closing message. The closing message dies with
the session. The issue does not, and one query lists every one of them across a fleet.

That query has one failure mode, and it is the one that matters: \*\*obligations get
discharged out of band.\*\* Someone adds a deploy key in a web UI, pays an invoice,
answers in chat. None of that emits an event anyone is listening to, so the issue sits
open for months describing something that was done in five minutes. A stale increment
annoys; a phantom row destroys the count, and the count is the product.

So each obligation carries its own answer, in its body, as a shell command whose \*\*exit
status is the question\*\*:

```default
**Verify:** `gh secret list --repo OWNER/REPO --json name -q '.[].name' | grep -qx NAME`
```

[`owed()`](#openloops.obligations.owed) lists the open ones, runs each predicate, and reports **three** states —
never two:

| `open`       | no predicate at all, or the predicate ran and returned non-zero                                   |
|--------------|---------------------------------------------------------------------------------------------------|
| `discharged` | the predicate ran and returned `0`: the ask is done, the issue<br/>is merely still open           |
| `unknown`    | the predicate could *not* be run, or errored in a way that is not<br/>an answer. Displayed as `?` |

`?` is not a rounding error, it is the whole point. A surface that says “nothing
owed” because it failed to check is worse than no surface at all, so nothing here is
ever allowed to collapse `unknown` into `open` or into `discharged`.

**Nothing here mutates anything.** A passing predicate is evidence, not authority: it
never closes, reopens or relabels an issue, and it never will — the standing rule is
that a human obligation is not closed on a model’s judgement. You are shown the
command, its exit status and what it printed, and you decide.

## Trust boundary — stated here because it should be read, not discovered

Evaluating a predicate means **executing text that came from a GitHub issue body**.
That is a real capability and it is bounded here in five ways, each of them visible:

1. **Only owners you named.** A predicate is run only when the issue’s repository owner
   is in `trusted_owners=`, which defaults to the same `owners=` the search was
   scoped to. A row outside that set reads `?` — never `open`, because nothing
   checked it, and never `discharged`, because nothing ran.
2. **The command is always shown next to its verdict.** Every row carries the predicate
   verbatim, so nothing executes invisibly and you can disagree with the answer.
3. **An explicit way not to execute at all.** `owed(verify=False)` (`ol owed
   --no-verify`) lists without running anything; every row that has a predicate then
   reads `?`, because that is the truth about it.
4. **Every evaluation is time-bounded**, by `predicate_timeout=`. A timeout is
   `unknown`, never an answer. On POSIX the predicate runs in its own process group
   and the timeout kills the group, so anything it started dies with it. On Windows only
   the shell itself is killed — a predicate that backgrounds work can outlive its
   timeout there, which is a platform limit worth knowing rather than a promise broken
   quietly.
5. **The whole thing is one keyword argument away from being someone else’s code.**
   `run_predicate=` replaces the evaluator; `issues_source=` replaces the reader.

One honest limit: predicates are POSIX shell. On a shell that cannot parse one, the
command exits non-zero and the row reads `open`. That is the safe direction to be
wrong in — a stale increment annoys, a wrong decrement destroys the count — and it is
why the exit status and the command text are always on screen.

**Kill criterion** (this module ships on an argument, so it names in advance what would
retire it): if, ninety days after this ships, `counts['with_predicate']` is below half
of `counts['total']` on a normal run, or nobody has run `ol owed` in a fortnight,
delete it. Its entire reason to exist over a one-line `gh search issues` alias is the
predicate; with no predicates to run it is a slower alias that draws a table. Removal is
one command — delete this module and `tests/test_obligations.py`, and drop `owed`
from `openloops.tools._dispatch_funcs` and `openloops.__main__._commands`. Nothing
imports it, nothing persists, and no other module changes.

**What this is not.** It is a *reader*. There is no store, no schema, no history, no
event log, no cross-repo linking, no session model and no local copy of anything: the
`manual-task` label **is** the record, and a second writable home for the same record
type is the drift this deliberately does not build. State lives in first-class GitHub
fields that a plain `gh` command can query, so deleting this module loses no data.

```pycon
>>> from datetime import datetime, timezone
>>> issues = [
...     {'number': 7, 'title': 'Add a deploy key so CI can clone',
...      'url': 'https://github.com/acme/widget/issues/7',
...      'createdAt': '2026-08-01T00:00:00Z',
...      'repository': {'nameWithOwner': 'acme/widget'},
...      'body': '**Verify:** `[ "$(gh api repos/acme/widget/keys --jq length)" -gt 0 ]`'},
...     {'number': 8, 'title': 'Decide whether to publish this at all',
...      'url': 'https://github.com/acme/widget/issues/8',
...      'createdAt': '2026-08-10T00:00:00Z',
...      'repository': {'nameWithOwner': 'acme/widget'},
...      'body': '**Verify:** none possible - a judgement call.'},
... ]
>>> report = owed(
...     issues_source=issues,               # a list of dicts: no gh, no network
...     run_predicate=lambda command: 0,    # canned: the ask turns out to be done
...     trusted_owners=('acme',),
...     now=datetime(2026, 8, 20, tzinfo=timezone.utc),
... )
>>> report['counts']['discharged'], report['counts']['open']
(1, 1)
>>> for row in report['rows']:
...     print(row['state'], row['age_days'], f"{row['repo']}#{row['number']}")
open 10 acme/widget#8
discharged 19 acme/widget#7
```

The discharged row is reported, not closed:

```pycon
>>> report['rows'][1]['predicate']
'[ "$(gh api repos/acme/widget/keys --jq length)" -gt 0 ]'
```

An owner you did not name is never executed, and never silently believed:

```pycon
>>> quiet = owed(issues_source=issues, run_predicate=lambda command: 0,
...              trusted_owners=(), now=datetime(2026, 8, 20, tzinfo=timezone.utc))
>>> [(row['number'], row['state']) for row in quiet['rows']]
[(8, 'open'), (7, 'unknown')]
>>> next(r['evidence'] for r in quiet['rows'] if r['number'] == 7)
"not evaluated: owner 'acme' is not in trusted_owners"
```

### Module Attributes

| [`DISCHARGED`](#openloops.obligations.DISCHARGED)        | The predicate ran and returned 0.                           |
|--------------------------------------------------------------------|-------------------------------------------------------------|
| [`UNKNOWN`](#openloops.obligations.UNKNOWN)           | Nothing could be checked.                                   |
| [`OBLIGATION_STATES`](#openloops.obligations.OBLIGATION_STATES) | The three states, in the order a reader cares about them.   |
| [`OBLIGATION_FIELDS`](#openloops.obligations.OBLIGATION_FIELDS) | Every key on every row, whatever the issue happened to say. |

### Functions

| [`configured_owners`](#openloops.obligations.configured_owners)(\*[, timeout])                  | Whose repositories to search, resolved once.                                 |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`gh_issues`](#openloops.obligations.gh_issues)(\*, owners[, label, state, limit, ...]) | The default `issues_source`: the open `manual-task` issues, from `gh`.       |
| [`owed`](#openloops.obligations.owed)(\*[, verify, owners, trusted_owners, ...])   | The open `manual-task` obligations, each re-checked against the world.       |
| [`parse_verify`](#openloops.obligations.parse_verify)(body)                                | `(predicate, verify_text)` for an issue body.                                |
| [`shell_predicate`](#openloops.obligations.shell_predicate)(command, \*[, timeout])           | The default `run_predicate`: run the command in a subshell, bounded in time. |

### Classes

| [`Obligation`](#openloops.obligations.Obligation)(repo, number, title, url, ...[, ...])   | One open `manual-task` issue, with the verdict its own predicate returned.   |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`PredicateOutcome`](#openloops.obligations.PredicateOutcome)(status[, output])                 | What evaluating one predicate produced.                                      |

### Exceptions

| [`GhUnavailable`](#openloops.obligations.GhUnavailable)   | The world could not be read: no `gh`, no credentials, no network, a timeout.   |
|------------------------------------------------------------------|--------------------------------------------------------------------------------|

### openloops.obligations.DISCHARGED *= 'discharged'*

The predicate ran and returned 0. The ask is done; the issue is just still open.

### *exception* openloops.obligations.GhUnavailable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The world could not be read: no `gh`, no credentials, no network, a timeout.

Raised only by the listing path, and never propagated to a caller of [`owed()`](#openloops.obligations.owed) —
it becomes `listed: False` plus an `error`, which every surface must render as
`?`. Turning it into an empty list would be the one unrecoverable bug here.

### openloops.obligations.OBLIGATION_FIELDS *= ('repo', 'number', 'title', 'url', 'created', 'age_days', 'state', 'verify', 'predicate', 'evidence')*

Every key on every row, whatever the issue happened to say. A row shape that varies
by issue makes `row["predicate"]` a coin flip and makes a JSON schema a lie.

### openloops.obligations.OBLIGATION_STATES *= ('open', 'discharged', 'unknown')*

The three states, in the order a reader cares about them. `open` is
[`openloops.base.OPEN`](openloops.base.md#openloops.base.OPEN): a loop that is still open is the same idea either way.

### *class* openloops.obligations.Obligation(repo, number, title, url, created, age_days, state='open', verify='', predicate='', evidence='')

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

### *class* openloops.obligations.PredicateOutcome(status, output='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What evaluating one predicate produced.

`status` is the shell exit status, or `None` for “could not be run” — the
difference between an answer and the absence of one.

```pycon
>>> PredicateOutcome(0).status, PredicateOutcome(None, 'timed out').output
(0, 'timed out')
```

### openloops.obligations.UNKNOWN *= 'unknown'*

Nothing could be checked. Rendered `?`. Never collapsed into either other state.

### openloops.obligations.configured_owners(, timeout=30.0)

Whose repositories to search, resolved once.

Three sources, in order, first one wins: `OPENLOOPS_OWNERS` (comma- or
space-separated); the owners named by the `gh owe` alias if one is installed,
because a fleet is usually already written down there and disagreeing with it is
how a count goes quietly wrong; and failing both, the login `gh` is authenticated
as. The resolved list is reported back on every result, so a partial answer is a
visible one rather than a silent one.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> import os
>>> os.environ['OPENLOOPS_OWNERS'] = 'acme, widgets co'
>>> configured_owners()
('acme', 'widgets', 'co')
>>> del os.environ['OPENLOOPS_OWNERS']
```

### openloops.obligations.gh_issues(, owners, label='manual-task', state='open', limit=50, timeout=30.0)

The default `issues_source`: the open `manual-task` issues, from `gh`.

This is a *filtered* search, not an enumeration — the label is applied server-side
and the result is capped — which is the only form of search this package is allowed
to use. Walking a whole fleet’s issues through the search API silently returns wrong
answers past its first thousand results; that job belongs to per-repo listing.

Returns whatever `gh` returned, unparsed and unjudged: a list of dicts with
`createdAt`, `number`, `repository`, `title`, `url` and `body`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.obligations.owed(, verify=True, owners=None, trusted_owners=None, label='manual-task', limit=50, timeout=30.0, predicate_timeout=20.0, now=None, issues_source=None, run_predicate=None)

The open `manual-task` obligations, each re-checked against the world.

`verify=False` lists without executing anything; every row that carries a
predicate then reads `unknown`, because that is what is true about it.

`owners=` scopes the search (default: [`configured_owners()`](#openloops.obligations.configured_owners)).
`trusted_owners=` scopes what may *execute* and defaults to `owners`, so
widening the search never quietly widens what runs — pass it explicitly to search
wider than you trust.

Two seams, each one keyword argument, each defaulting to a real implementation:
`issues_source=` (defaults to [`gh_issues()`](#openloops.obligations.gh_issues); a list of dicts substitutes) and
`run_predicate=` (defaults to [`shell_predicate()`](#openloops.obligations.shell_predicate); any callable from command
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
: one dict per obligation, with every key in [`OBLIGATION_FIELDS`](#openloops.obligations.OBLIGATION_FIELDS).

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

### openloops.obligations.parse_verify(body)

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

### openloops.obligations.shell_predicate(command, , timeout=20.0)

The default `run_predicate`: run the command in a subshell, bounded in time.

The exit status is the answer and nothing else is interpreted. Anything that is not
an exit status — a timeout, a shell that would not start — comes back as
`status=None`, which is `unknown`, which is `?`.

* **Return type:**
  [`PredicateOutcome`](#openloops.obligations.PredicateOutcome)

```pycon
>>> shell_predicate('exit 0').status
0
>>> shell_predicate('exit 3').status
3
>>> shell_predicate('   ').status is None
True
```
