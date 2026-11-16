# openloops.board_refresh

Keep the phone board within a day of GitHub, without a session remembering to.

The board ([`openloops.board`](openloops.board.html.md#module-openloops.board)) is built by hand once: gather, classify, build. Left
alone it goes stale (a board built 2026-10-27 was still that build on 2026-11-09, with
210 of its 420 cards closed and 222 new items missing). [`refresh_board()`](#openloops.board_refresh.refresh_board) is the
rebuild as one deterministic, model-free step meant to run from a timer (`ol
install-refresh-job`) or by hand (`ol board-refresh WORK`):

1. gather the open items ([`openloops.tasks.gather()`](openloops.tasks.html.md#openloops.tasks.gather)) over the scope saved in
   `WORK/refresh.json` (flags given on the command line are saved there first, and
   what `OPENLOOPS_OWNERS`/`OPENLOOPS_EXCLUDE_REPOS` or the default owners resolve
   to is saved as explicit lists, so a timer without that environment sweeps the same
   scope: [`pin_env_scope()`](#openloops.board_refresh.pin_env_scope));
2. merge them with the live `WORK/board/tasks.json` ([`merge_refresh()`](#openloops.board_refresh.merge_refresh), pure):
   the earlier record of every id still open is kept, with its title and url
   refreshed from GitHub and nothing re-classified; each new id gets the free
   heuristic record;
3. if nothing opened, closed or was retitled, stop (`rebuilt: False`);
4. otherwise rebuild into a temporary directory and move each file into place
   (`os.replace`: the receiver job reads `tasks.json` at any moment); the new ids
   accumulate in `WORK/new-items.json` for a session’s classifier brief;
5. publish (a directory, or `host:dir` through `scp`) whenever the local board’s
   files differ from the last ones published, and only then record it.

Guards, because a wrong rebuild is worse than a stale one:

* an incomplete sweep (`listed: false`) never rebuilds;
* a saturated sweep (some search hit its cap) adds but never closes;
* closing more than `max_close_fraction` of a board of at least
  [`GUARD_MIN_LIVE`](#openloops.board_refresh.GUARD_MIN_LIVE) cards is refused unless `force`: those closes are withheld
  > (and named in `refresh.json`), while additions and retitles still go through, so
  > a refusal never freezes the board;
* a `tasks.json`, `board.json` or `refresh.json` that exists but does not parse
  (or, for `refresh.json`, holds a value of the wrong shape) raises rather than being
  read as empty, and a first run with no `board.json` raises rather than publishing
  default settings;
* an owner-edited `kit.html` (one that differs from the packaged template) is kept.

A board whose page keeps its state in a claude.ai Artifact cannot be republished from
here: the result says `needs_republish: True` and a session republishes it.

What it touches: GitHub through `gather` (read-only); files under `WORK`; and, when
publishing, the destination directory or the remote host (`scp` with the user’s own
keys). It never calls a model.

### Module Attributes

| [`NEW_ITEMS_FILE`](#openloops.board_refresh.NEW_ITEMS_FILE)          | Where the items that got only the heuristic record are listed, for a classifier brief.                 |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| [`STATE_FILE`](#openloops.board_refresh.STATE_FILE)              | the gather scope, run specs/extras, where to publish, and the hash of the `tasks.json` last published. |
| [`DFLT_MAX_CLOSE_FRACTION`](#openloops.board_refresh.DFLT_MAX_CLOSE_FRACTION) | A rebuild may close at most this fraction of the live cards without `force`...                         |
| [`GUARD_MIN_LIVE`](#openloops.board_refresh.GUARD_MIN_LIVE)          | ...once the board has at least this many cards (a small board may empty legitimately).                 |

### Functions

| [`dir_publisher`](#openloops.board_refresh.dir_publisher)(destination, \*[, timeout])   | A publisher that copies the board's files to `destination`.                                                                  |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| [`is_remote_destination`](#openloops.board_refresh.is_remote_destination)(destination)          | Whether `destination` names `host:dir` (for `scp`) rather than a local path.                                                 |
| [`load_state`](#openloops.board_refresh.load_state)(work_dir)                        | `WORK/refresh.json`: `{}` when missing, an error when it exists but is unreadable or holds a scope value of the wrong shape. |
| [`merge_refresh`](#openloops.board_refresh.merge_refresh)(live, candidates, \*[, ...])  | The rebuild's records, the new candidates, and the plan.                                                                     |
| [`pin_env_scope`](#openloops.board_refresh.pin_env_scope)(work_dir, \*[, environ, ...]) | Save what the environment makes the sweep's scope into `WORK/refresh.json`.                                                  |
| [`plan_refresh`](#openloops.board_refresh.plan_refresh)(current, previous)             | Diff the ids now open against the ids on the live board.                                                                     |
| [`refresh_board`](#openloops.board_refresh.refresh_board)(work_dir, \*[, owners, ...])  | Rebuild `WORK/board` when the set of open items changed.                                                                     |
| [`remember_scope`](#openloops.board_refresh.remember_scope)(work_dir, \*\*given)         | Save the `given` scope values (`None` = not given) into `WORK/refresh.json`.                                                 |

### Classes

| [`RefreshPlan`](#openloops.board_refresh.RefreshPlan)(kept, added, closed[, withheld, ...])   | What a fresh sweep changes relative to the live board.   |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------|

### Exceptions

| [`PublishError`](#openloops.board_refresh.PublishError)   | Publishing the rebuilt board failed.   |
|-----------------------------------------------------------------|----------------------------------------|

### openloops.board_refresh.DFLT_MAX_CLOSE_FRACTION *= 0.5*

A rebuild may close at most this fraction of the live cards without `force`…

### openloops.board_refresh.GUARD_MIN_LIVE *= 10*

…once the board has at least this many cards (a small board may empty legitimately).

### openloops.board_refresh.NEW_ITEMS_FILE *= 'new-items.json'*

Where the items that got only the heuristic record are listed, for a classifier brief.

### *exception* openloops.board_refresh.PublishError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Publishing the rebuilt board failed. The local board is in place; the next run
retries, because the published marker is recorded only after a success.

### *class* openloops.board_refresh.RefreshPlan(kept, added, closed, withheld=(), updated=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a fresh sweep changes relative to the live board.

`withheld` are ids missing from a saturated sweep, kept rather than closed;
`updated` are kept ids whose title or url changed on GitHub.

### openloops.board_refresh.STATE_FILE *= 'refresh.json'*

the gather scope, run specs/extras, where to publish, and
the hash of the `tasks.json` last published.

* **Type:**
  The refresh’s own state

### openloops.board_refresh.dir_publisher(destination, , timeout=300)

A publisher that copies the board’s files to `destination`.

`destination` is a directory, or `host:dir` (see
[`is_remote_destination()`](#openloops.board_refresh.is_remote_destination)), which goes through `scp -o BatchMode=yes` (never a
password prompt that would hang a timer) with `timeout` seconds. A local copy
replaces each file atomically; the remote copy does not (`scp` writes in place),
so a reader on the host can, for a moment, see a partly written file. A failure
raises, so a timer’s log says the board did not move.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### openloops.board_refresh.is_remote_destination(destination)

Whether `destination` names `host:dir` (for `scp`) rather than a local path.

Remote only when the text before the first colon is a plausible host (non-empty, no
`/` or `\`, not a one-letter Windows drive such as `C:`) and the whole thing
is not an existing local path.

```pycon
>>> [is_remote_destination(d) for d in ('tw:/srv/board', 'me@host:board')]
[True, True]
>>> [is_remote_destination(d) for d in (r'C:\Users\x\dest', '/tmp/a:b', 'board')]
[False, False, False]
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### openloops.board_refresh.load_state(work_dir)

`WORK/refresh.json`: `{}` when missing, an error when it exists but is
unreadable or holds a scope value of the wrong shape.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.board_refresh.merge_refresh(live, candidates, , saturated=(), withhold_closes=False)

The rebuild’s records, the new candidates, and the plan. No I/O.

Every id still open keeps its earlier record (never re-classified), with
`REFRESHED_FIELDS` taken from the sweep; new ids get the heuristic record. A
`saturated` sweep did not list everything, so an id it did not see is kept
(`withheld`), never closed; `withhold_closes` does the same for a sweep whose
closes were refused.

```pycon
>>> live = [{'id': 'a/b#1', 'title': 'Old', 'ask': 'ENRICHED'}, {'id': 'a/b#2'}]
>>> seen = [{'id': 'a/b#1', 'title': 'New', 'url': 'https://github.com/a/b/issues/1'}]
>>> records, fresh, plan = merge_refresh(live, seen)
>>> [(r['id'], r['title'], r['ask']) for r in records], plan.closed, plan.updated
([('a/b#1', 'New', 'ENRICHED')], ('a/b#2',), ('a/b#1',))
>>> records, _, plan = merge_refresh(live, seen, saturated=['label:manual-task'])
>>> [r['id'] for r in records], plan.closed, plan.withheld
(['a/b#1', 'a/b#2'], (), ('a/b#2',))
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]], [`RefreshPlan`](#openloops.board_refresh.RefreshPlan)]

### openloops.board_refresh.pin_env_scope(work_dir, , environ=None, resolve_owners=None)

Save what the environment makes the sweep’s scope into `WORK/refresh.json`.

A launchd timer does not get the shell’s `OPENLOOPS_OWNERS` or
`OPENLOOPS_EXCLUDE_REPOS`, so a scope that lives only there would make the timer
sweep a different set of repositories than a run by hand (and could put an excluded
client repo on the board). Each is written as an explicit list, but only where
`refresh.json` has no value yet (a flag given earlier, or an earlier pin, wins).
With no `OPENLOOPS_OWNERS`, `resolve_owners` (e.g.
[`openloops.obligations.configured_owners()`](openloops.obligations.html.md#openloops.obligations.configured_owners)) supplies the default owners; when
it is not given they stay unset here and the first sweep’s resolved owners are
pinned instead. Returns what was saved.

```pycon
>>> import tempfile
>>> with tempfile.TemporaryDirectory() as tmp:
...     env = {'OPENLOOPS_OWNERS': 'me, org', 'OPENLOOPS_EXCLUDE_REPOS': 'org/x-*'}
...     first = pin_env_scope(tmp, environ=env)
...     second = pin_env_scope(tmp, environ={'OPENLOOPS_OWNERS': 'other'})
>>> first, second
({'owners': ['me', 'org'], 'exclude_repos': ['org/x-*']}, {})
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### openloops.board_refresh.plan_refresh(current, previous)

Diff the ids now open against the ids on the live board.

```pycon
>>> plan = plan_refresh(['a#1', 'a#2', 'a#4'], ['a#1', 'a#3'])
>>> plan.kept, plan.added, plan.closed, plan.changed
(('a#1',), ('a#2', 'a#4'), ('a#3',), True)
>>> plan_refresh(['a#1'], ['a#1']).changed
False
```

* **Return type:**
  [`RefreshPlan`](#openloops.board_refresh.RefreshPlan)

### openloops.board_refresh.refresh_board(work_dir, \*, owners=None, exclude_owners=None, exclude_repos=None, searches=None, review_prs=None, run_specs=None, run_extras=None, publish_to=None, force=False, max_close_fraction=0.5, publish=None, gather=<function gather>, settings=None)

Rebuild `WORK/board` when the set of open items changed. Returns what happened.

The scope keywords (`owners` to `publish_to`) are saved into
`WORK/refresh.json` when given and read from it when not ([`remember_scope()`](#openloops.board_refresh.remember_scope));
their defaults are every kind of item and PRs awaiting review, like
`board-gather --all-kinds`. `run_specs`/`run_extras` are passed to every
rebuild, as `board-build` takes them. `force` rebuilds even when nothing
changed and overrides the close guard (never the incomplete-sweep one). What the
environment sets (`OPENLOOPS_OWNERS`, `OPENLOOPS_EXCLUDE_REPOS`) and, failing
that, the owners the sweep resolved, are pinned into `refresh.json` where it has no
value yet ([`pin_env_scope()`](#openloops.board_refresh.pin_env_scope)).
`publish` replaces the publisher built from `publish_to` (see
[`dir_publisher()`](#openloops.board_refresh.dir_publisher)); `gather` replaces the sweep; `settings` override the
existing `board.json` (and are required when there is none).

`status` is `rebuilt`, `unchanged`, `incomplete`, `partial` (rebuilt with
additions/retitles while a mass close was refused) or `refused` (a mass close was
refused and nothing else changed). Refused closes are withheld, never dropped:
`refused_closes` (a count) and `refused_close_ids` are returned and kept in
`refresh.json` until a run no longer refuses, and `remedy` is the command that
applies them. A publish failure raises [`PublishError`](#openloops.board_refresh.PublishError) after the local rebuild
is in place.

```pycon
>>> import tempfile
>>> item = {'id': 'a/b#1', 'url': 'https://github.com/a/b/issues/1',
...         'repo': 'a/b', 'title': 'Add a key', 'src': 'label:manual-task'}
>>> sweep = lambda **kw: {'listed': True, 'candidates': [item], 'error': None}
>>> with tempfile.TemporaryDirectory() as tmp:
...     first = refresh_board(tmp, gather=sweep, settings={'title': 'Mine'})
...     again = refresh_board(tmp, gather=sweep)
>>> first['rebuilt'], first['added'], again['status']
(True, 1, 'unchanged')
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.board_refresh.remember_scope(work_dir, \*\*given)

Save the `given` scope values (`None` = not given) into `WORK/refresh.json`.

Returns the full scope: what was saved, then defaults. Both `ol board-refresh`
and `ol install-refresh-job` go through here, so the timer needs only `WORK`.

```pycon
>>> import tempfile
>>> with tempfile.TemporaryDirectory() as tmp:
...     _ = remember_scope(tmp, owners=['me'])
...     scope = remember_scope(tmp, exclude_repos=None)
>>> scope['owners'], scope['review_prs']
(['me'], True)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
