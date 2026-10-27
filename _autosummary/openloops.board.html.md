# openloops.board

The phone task board: task records in, a static page and its data files out.

[`build_board()`](#openloops.board.build_board) writes five files into a directory the caller names:

The page is meant to be published as a claude.ai Artifact with a `db` capability.
Its persistence model (immutable `outbox/<eventId>` events written by the page,
`receipts/<eventId>` written only by the receiving session) is documented at the
top of its `<script>`.

**What openloops does not do** (ADR-008): post the comments, close the issues or
dispatch the workers that the board’s events ask for. That write side is a
procedure a Claude session follows, shipped as the `openloops-phone-board` skill.
This module writes files into `out_dir` and nothing else, and it never puts the
data anywhere near the repository: where the board lives is the caller’s choice.

```pycon
>>> tasks = [
...     {'id': 'a/x#1', 'tier': 'browser', 'pattern': 'api-key', 'minutes': 3},
...     {'id': 'a/y#2', 'tier': 'browser', 'pattern': 'api-key', 'minutes': 5},
...     {'id': 'a/z#3', 'tier': 'tap', 'pattern': 'other', 'status': 'likely-done'},
... ]
>>> [(r['key'], r['ids']) for r in group_runs(tasks)]
[('cleanup', ['a/z#3']), ('api-key', ['a/x#1', 'a/y#2'])]
```

### Functions

| [`board_dir`](#openloops.board.board_dir)()                              | Where the page template and the default run specs ship, inside the package.    |
|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`build_board`](#openloops.board.build_board)(records, out_dir, \*[, ...]) | Write the board's five files into `out_dir` and say what went in.              |
| [`group_runs`](#openloops.board.group_runs)(tasks, \*[, specs, extras])   | Repeated chores grouped into runs, ordered as the specs are.                   |
| [`join_created`](#openloops.board.join_created)(tasks, candidates)          | Fill each record's missing `created` from the gathered candidate with its URL. |
| [`run_specs`](#openloops.board.run_specs)([path])                        | The run specs: one per pattern, in display order.                              |
| [`sort_tasks`](#openloops.board.sort_tasks)(tasks)                        | Cheapest first: by tier, then by minutes per thing the item unblocks.          |

### openloops.board.board_dir()

Where the page template and the default run specs ship, inside the package.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.board.build_board(records, out_dir, , candidates=(), specs=None, extras=None, title='Phone Task Board', session=None, read_only_orgs=(), machine=None, store='artifact', api=None, moved_to=None)

Write the board’s five files into `out_dir` and say what went in.

`session` is the name of the Claude session that receives the board’s events (the
page names it in the prompts it copies); `read_only_orgs` are organisations whose
items the page never offers to close or comment on; `machine` is the default
machine named by a run’s “have an agent start this run”.

`store` picks where the page keeps its state: `artifact` (the claude.ai
Artifact `db` capability) or `http` (a self-hosted board store API at `api`,
same origin as the page, served by anything wrapping [`openloops.board_store`](openloops.board_store.html.md#module-openloops.board_store)).
`moved_to` (an `https://` URL) builds the page as a forwarding notice: it
flushes what a phone already queued and takes no new taps.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.board.group_runs(tasks, , specs=None, extras=None)

Repeated chores grouped into runs, ordered as the specs are.

Open items go to their pattern’s run (a `mac-only` tier goes to `mac-only`);
`likely-done` and `stale` items go to `cleanup`. A pattern with no spec, or
with fewer items than its `min_items`, has no run.

`extras` overlays a run by key, for what only this deployment knows (a prompt, a
package table, a better title). Its `absorb` names other runs whose items move
into this one, and those runs disappear: two chores done in one session run.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.board.join_created(tasks, candidates)

Fill each record’s missing `created` from the gathered candidate with its URL.

```pycon
>>> join_created([{'url': 'u', 'created': None}], [{'url': 'u', 'created': '2026-01-02'}])
[{'url': 'u', 'created': '2026-01-02'}]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.board.run_specs(path=None)

The run specs: one per pattern, in display order. Packaged ones by default.

Each spec is `{key, title, why, steps, tier?, min_items?, prompt?, machine?}`;
`key` is a pattern from [`openloops.tasks.PATTERNS`](openloops.tasks.html.md#openloops.tasks.PATTERNS), or `cleanup`.

```pycon
>>> run_specs()[0]['key']
'cleanup'
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.board.sort_tasks(tasks)

Cheapest first: by tier, then by minutes per thing the item unblocks.

```pycon
>>> [t['id'] for t in sort_tasks([{'id': 'b', 'tier': 'session'}, {'id': 'a', 'tier': 'tap'}])]
['a', 'b']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]
