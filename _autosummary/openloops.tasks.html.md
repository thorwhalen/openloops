# openloops.tasks

Everything you could act on, as one list of task records: gather, classify, merge.

[`openloops.owed()`](openloops.html.md#openloops.owed) answers  *“what do I owe, and is it still owed?”* for one label.
A task board needs a wider net and a different answer: every open item across a fleet
that asks something of the human (the `manual-task` issues, the issues titled
“Decide…”, the PRs waiting on their review), each turned into a **task record** saying
what to do, where to do it, how long it takes and on which device.

Three steps, each a plain function:

1. [`gather()`](#openloops.tasks.gather) sweeps several owners with `gh search`, one query per owner and
   kind so no owner’s results crowd out another’s, with no 50-row cap (the search
   API’s own ceiling of 1000 per query is the limit, and a query that reaches it is
   *reported* as saturated, never truncated quietly). Exclusions are keyword arguments.
2. [`classify()`](#openloops.tasks.classify) turns each candidate into a record through a `classifier=`. The
   default, [`heuristic_classify()`](#openloops.tasks.heuristic_classify), is deterministic: label, title and body
   patterns decide the tier, the pattern and the minutes, and the deep-link builders
   point at the exact settings page. No model is called, here or anywhere in
   openloops. The richer path is the classifier brief shipped with the
   `openloops-phone-board` skill: a subagent reads each item and writes records in
   the same schema, which [`merge_records()`](#openloops.tasks.merge_records) lays over the heuristic ones.
3. [`merge_records()`](#openloops.tasks.merge_records) combines record sources by URL, later sources winning, and
   normalises every record to [`TASK_FIELDS`](#openloops.tasks.TASK_FIELDS).

The record schema is [`Task`](#openloops.tasks.Task), defined once, here. The board page, the build
step and the classifier brief all read it; a field added anywhere else is a field the
others do not know about.

**Read-only, like the rest of openloops.** Gathering runs `gh search`; nothing here
comments, closes, labels or approves anything.

```pycon
>>> candidate = {
...     'url': 'https://github.com/acme/widget/issues/7', 'repo': 'acme/widget',
...     'number': 7, 'title': 'Add the NPM_TOKEN secret so CI can publish',
...     'body': '', 'labels': ['manual-task'], 'created': '2026-08-01',
... }
>>> record = heuristic_classify(candidate)
>>> record['tier'], record['pattern'], record['id']
('browser', 'github-settings', 'acme/widget#7')
>>> [link['label'] for link in record['links']]
['GitHub: Actions secrets', 'Issue']
```

### Module Attributes

| [`TIERS`](#openloops.tasks.TIERS)         | Where the human does the thing, cheapest first.    |
|----------------------------------------------------------------|----------------------------------------------------|
| [`STATUSES`](#openloops.tasks.STATUSES)      | Whether the item still asks anything of the human. |
| [`PATTERNS`](#openloops.tasks.PATTERNS)      | The controlled vocabulary of repeated chores.      |
| [`TASK_FIELDS`](#openloops.tasks.TASK_FIELDS)   | Every key on every record, in schema order.        |
| [`DFLT_SEARCHES`](#openloops.tasks.DFLT_SEARCHES) | (search terms, the field they match).              |

### Functions

| [`classify`](#openloops.tasks.classify)(candidates, \*[, classifier])          | One normalised record per candidate, through `classifier`.                       |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`gather`](#openloops.tasks.gather)(\*[, owners, exclude_owners, ...])       | Every open item that asks something of the human, across `owners`, deduplicated. |
| [`github_settings_url`](#openloops.tasks.github_settings_url)(repo, section)              | A repository settings page (a key of `GITHUB_SETTINGS`).                         |
| [`heuristic_classify`](#openloops.tasks.heuristic_classify)(candidate, \*[, rules, ...]) | A task record from a gathered candidate, by patterns alone.                      |
| [`load_records`](#openloops.tasks.load_records)(paths)                             | The records in JSON files (each a list, or an envelope with `candidates`).       |
| [`merge_records`](#openloops.tasks.merge_records)(\*sources)                        | Records from several sources, one per item, later sources winning.               |
| [`npm_access_url`](#openloops.tasks.npm_access_url)(package)                         | npm package settings: trusted publisher, publishing access, 2FA requirement.     |
| [`pypi_publishing_url`](#openloops.tasks.pypi_publishing_url)([project])                  | PyPI trusted publishers: a project's page, or the pending-publisher page.        |

### Classes

| [`Rule`](#openloops.tasks.Rule)(pattern, tier, minutes, regex)               | A heuristic: when `regex` matches title + body, the item is this pattern.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`Task`](#openloops.tasks.Task)(id[, url, kind, org, repo, title, ask, ...]) | One thing the human could act on.                                           |

### openloops.tasks.DFLT_SEARCHES *= {'decide': ('Decide', 'title'), 'needs-user': ('"Needs the user"', 'body')}*

(search terms, the field they match).

* **Type:**
  Extra searches beyond the label, by name

### openloops.tasks.PATTERNS *= ('npm-trusted-publisher', 'npm-first-publish', 'npm-scope', 'npm-other', 'pypi-trusted-publisher', 'pypi-release', 'api-key', 'github-settings', 'server-chore', 'decision', 'review-pr', 'merge-bot-pr', 'record', 'device-test', 'listen-look', 'live-check', 'purchase', 'mac-only', 'other')*

The controlled vocabulary of repeated chores. A run on the board groups one pattern.

### *class* openloops.tasks.Rule(pattern, tier, minutes, regex)

Bases: [`NamedTuple`](https://docs.python.org/3/library/typing.html#typing.NamedTuple)

A heuristic: when `regex` matches title + body, the item is this pattern.

#### minutes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Alias for field number 2

#### pattern *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Alias for field number 0

#### regex *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Alias for field number 3

#### tier *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Alias for field number 1

### openloops.tasks.STATUSES *= ('open', 'likely-done', 'not-for-user', 'stale')*

Whether the item still asks anything of the human.

### openloops.tasks.TASK_FIELDS *= ('id', 'url', 'kind', 'org', 'repo', 'title', 'ask', 'tier', 'minutes', 'links', 'decision', 'prompt', 'machine', 'unblocks', 'pattern', 'pattern_key', 'status', 'note', 'source', 'created')*

Every key on every record, in schema order.

### openloops.tasks.TIERS *= ('tap', 'browser', 'session', 'physical', 'mac-only')*

Where the human does the thing, cheapest first. The board sorts and filters on it.

### *class* openloops.tasks.Task(id, url=None, kind='issue', org=None, repo=None, title='', ask='', tier='session', minutes=None, links=list(), decision=None, prompt=None, machine=None, unblocks=list(), pattern='other', pattern_key=None, status='open', note=None, source=None, created=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One thing the human could act on. Every record carries every field.

`decision` is `{question, options, recommendation}` or `None`; `links` are
`{label, url}` with the item itself last; `prompt` is a paste-ready request for
a coding session (session tier). `source` says how the item was found and
`created` when it was opened (`YYYY-MM-DD`).

```pycon
>>> Task.from_mapping({'id': 'a/b#1', 'tier': 'nope', 'pattern': 'x'}).tier
'session'
```

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### *classmethod* from_mapping(record)

Normalise a record from any source: unknown keys dropped, bad vocabulary fixed.

A value outside its vocabulary becomes the field’s safe default (`session`
tier, `other` pattern, `open` status) rather than an error, because one
sloppy classifier record must not sink a board of three hundred.

* **Return type:**
  [`Task`](#openloops.tasks.Task)

### openloops.tasks.classify(candidates, \*, classifier=<function heuristic_classify>)

One normalised record per candidate, through `classifier`.

```pycon
>>> classify([{'url': 'https://github.com/a/b/issues/1', 'title': 'Decide the name'}])[0]['tier']
'tap'
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.tasks.gather(, owners=None, exclude_owners=(), exclude_repos=None, label='manual-task', searches=(), review_prs=False, limit=1000, timeout=30.0, run_gh=None)

Every open item that asks something of the human, across `owners`, deduplicated.

One query per owner and per kind: the `label` (`manual-task`), each named
search in `searches` (keys of [`DFLT_SEARCHES`](#openloops.tasks.DFLT_SEARCHES)), and with `review_prs` the
open PRs requesting your review. `owners` defaults to
[`openloops.obligations.configured_owners()`](openloops.obligations.html.md#openloops.obligations.configured_owners); `exclude_repos` (owner/name
globs) defaults to `OPENLOOPS_EXCLUDE_REPOS`. `run_gh` replaces the `gh`
runner (`run_gh(args, timeout=...) -> stdout`).

The result is an envelope: `listed` is `False` with an `error` when any query
failed, because a partial sweep presented as a whole one is the failure that
matters. `saturated` names the queries that hit `limit`.

```pycon
>>> def fake(args, *, timeout):
...     return json.dumps([{'number': 1, 'title': 'Add a key',
...         'url': 'https://github.com/acme/w/issues/1',
...         'repository': {'nameWithOwner': 'acme/w'}, 'labels': [], 'body': ''}])
>>> report = gather(owners=['acme'], run_gh=fake)
>>> report['listed'], [c['id'] for c in report['candidates']]
(True, ['acme/w#1'])
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tasks.github_settings_url(repo, section)

A repository settings page (a key of `GITHUB_SETTINGS`).

```pycon
>>> github_settings_url('acme/widget', 'pages')
'https://github.com/acme/widget/settings/pages'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.tasks.heuristic_classify(candidate, , rules=(('mac-only', 'mac-only', 10, '\\\\b(macos|mac app|keychain|xcode|launchd|on the mac)\\\\b'), ('npm-first-publish', 'session', 10, 'npm.\*(first publish|not (yet )?on npm|does not exist)|first publish.\*npm'), ('npm-trusted-publisher', 'browser', 3, 'npm.\*trusted publish|trusted publish.\*npm'), ('npm-scope', 'browser', 3, 'npm (org|scope)|claim .\*scope'), ('pypi-trusted-publisher', 'browser', 3, 'pypi.\*(trusted|pending) publish|(trusted|pending) publish.\*pypi'), ('pypi-release', 'session', 5, 'pypi.\*(release|upload)|(release|upload).\*pypi'), ('decision', 'tap', 2, '\\\\A\\\\s\*(decision|decide|confirm|should|reopen|choose|pick)\\\\b|\\\\A[^\\\\n]\*\\\\?|\\\\A[^\\\\n]\*\\\\bdecide\\\\b'), ('github-settings', 'browser', 3, '\\\\b(secret|deploy key|github pages|environment|actions settings|repo(sitory)? settings)\\\\b'), ('api-key', 'browser', 5, '\\\\b(api key|api token|access token|create (an )?account|sign up)\\\\b'), ('purchase', 'browser', 5, '\\\\b(purchase|buy|paid plan|subscription|invoice|billing)\\\\b'), ('record', 'physical', 15, '\\\\brecord (yourself|a|an|audio|video|your)\\\\b|\\\\bvoice sample\\\\b'), ('device-test', 'physical', 10, '\\\\b(on (a|your) (phone|device)|test on (ios|android|a device))\\\\b'), ('listen-look', 'physical', 10, '\\\\b(listen to|look at|judge|eyeball)\\\\b'), ('live-check', 'session', 5, '\\\\blive (check|test|run)\\\\b|\\\\breal (api )?key\\\\b'), ('server-chore', 'session', 5, '\\\\b(deploy|install|ssh|sudo|server|cron|systemd)\\\\b'), ('decision', 'tap', 2, '\\\\b(go-ahead|which option|options?:|recommend(ation|ed)?:?\\\\\*\\\\\*)')), machines=None)

A task record from a gathered candidate, by patterns alone. No model, no network.

`rules` are tried in order against the title and body; `machines` maps an owner
to the machine its session-tier prompts name. Status is always `open`: whether an
ask was already done is a judgement only a reader of the thread can make (the
classifier brief’s job).

```pycon
>>> pr = {'url': 'https://github.com/acme/w/pull/3', 'repo': 'acme/w',
...       'title': 'Bump lodash from 4.17.20 to 4.17.21', 'body': ''}
>>> heuristic_classify(pr)['pattern'], heuristic_classify(pr)['links'][0]['url']
('merge-bot-pr', 'https://github.com/acme/w/pull/3/files')
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.tasks.load_records(paths)

The records in JSON files (each a list, or an envelope with `candidates`).

Globs are expanded, in sorted order, so `out_*.json` reads a batch directory. A
glob that matches nothing raises: the batches a subagent failed to write must not
quietly turn into a board built from the heuristic alone.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.tasks.merge_records(\*sources)

Records from several sources, one per item, later sources winning.

Keyed by `id` (derived from the URL for a GitHub item, so the two sources agree);
a record with no id and no URL is dropped. A later record replaces the
earlier one whole, except that an empty `url` or `created` is filled from it:
the classifier brief reads threads, the gatherer knows dates.

```pycon
>>> heuristic = [{'id': 'a/b#1', 'url': 'u1', 'tier': 'browser', 'created': '2026-01-02'}]
>>> enriched = [{'id': 'a/b#1', 'url': 'u1', 'tier': 'tap', 'ask': 'Say yes'}]
>>> [(r['tier'], r['ask'], r['created']) for r in merge_records(heuristic, enriched)]
[('tap', 'Say yes', '2026-01-02')]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.tasks.npm_access_url(package)

npm package settings: trusted publisher, publishing access, 2FA requirement.

```pycon
>>> npm_access_url('@acme/widget')
'https://www.npmjs.com/package/@acme/widget/access'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.tasks.pypi_publishing_url(project=None)

PyPI trusted publishers: a project’s page, or the pending-publisher page.

```pycon
>>> pypi_publishing_url()
'https://pypi.org/manage/account/publishing/'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
