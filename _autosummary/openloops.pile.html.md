# openloops.pile

The pile: GTD’s In list, kept as GitHub issues in a private repo, and its clarify step.

A capture (an Apple Shortcut, the `gh` CLI, anything that can send a request to the issues
API) is one open issue labelled `pile` in the owner’s pile repo. This module is the one
place that reads and changes that pile, so the agent skill (`openloops-pile`), the
`ol pile-*` commands and a voice surface (bosun) all do the same thing:

- [`items()`](#openloops.pile.items) / [`show()`](#openloops.pile.show): what is on the pile, read-only;
- [`propose()`](#openloops.pile.propose): a first proposal per item, from a model-free heuristic by default
  (`proposer=` is the seam an agent’s own reading replaces);
- [`plan()`](#openloops.pile.plan): the steps that carry out one decision the owner said yes to (a loop, an
  idea, an issue in another repo, work handed to a session, done, dropped), ending with
  a signed comment on the pile item saying where it went. \*\*openloops never writes to
  GitHub\*\* (ADR-008, ADR-014): the caller runs the steps with its own tools;
- [`signed()`](#openloops.pile.signed): a signed progress note, for a session working on an item;
- [`nudge()`](#openloops.pile.nudge): keep one reminder loop pending while items wait too long. It never
  acts on an item.

**Every write is signed** ([`signature()`](#openloops.pile.signature)): the agent’s name and, on private repos, a
link to its session, so an idea’s development can always be traced back to who did it.
**Public destinations get no private content**: an issue filed in a public repo carries
only the text the caller wrote for it, no dictation, no pile link and no session link.

Nothing here runs on capture and nothing acts without being called: no Action, no
webhook (the owner’s rule). GitHub is only read, through `gh` (`run_gh=`); the one
write is [`nudge()`](#openloops.pile.nudge)’s reminder loop, through openloops’ own reminder runner.

```pycon
>>> parse_item({"number": 7, "title": "call about zodal", "body": "call about zodal\n\n— pile: inbox",
...             "labels": [{"name": "pile"}, {"name": "inbox"}], "createdAt": "2026-11-20T10:00:00Z",
...             "url": "https://github.com/o/_pile/issues/7"}).hint
'inbox'
```

### Module Attributes

| [`PILE_LABEL`](#openloops.pile.PILE_LABEL)      | The label every untriaged capture carries.                                                                                |
|------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| [`KINDS`](#openloops.pile.KINDS)           | What `apply()` can do with an item.                                                                                       |
| [`DFLT_STALE_DAYS`](#openloops.pile.DFLT_STALE_DAYS) | An item older than this many days makes [`nudge()`](#openloops.pile.nudge) keep a reminder pending. |
| [`NUDGE_SOURCE`](#openloops.pile.NUDGE_SOURCE)    | one per pile, found again by this.                                                                                        |
| [`RESULT`](#openloops.pile.RESULT)          | The placeholder a plan's later steps carry for what the first step produced (an issue URL, a loop id, an idea id).        |

### Functions

| [`pile_repo`](#openloops.pile.pile_repo)([repo, run_gh])                        | The pile repo: `repo`, else `OPENLOOPS_PILE_REPO`, else `<gh login>/_pile`.                 |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| [`parse_item`](#openloops.pile.parse_item)(raw)                                  | A [`PileItem`](#openloops.pile.PileItem) from `gh`'s JSON for one issue. |
| [`items`](#openloops.pile.items)(\*[, repo, label, limit, run_gh])          | The open items carrying `label` (default: untriaged), oldest first.                         |
| [`show`](#openloops.pile.show)(number, \*[, repo, run_gh])                 | One item with its comments (any state).                                                     |
| [`heuristic_propose`](#openloops.pile.heuristic_propose)(item)                          | A first guess from the words alone.                                                         |
| [`propose`](#openloops.pile.propose)(found, \*[, proposer])                   | One proposal per item.                                                                      |
| [`signature`](#openloops.pile.signature)(by[, session, public])                 | The last lines of every comment an agent writes here.                                       |
| [`agent_identity`](#openloops.pile.agent_identity)([by, session, env])               | Who is writing: `by` (an agent or session name) and `session` (a URL or address).           |
| [`signed`](#openloops.pile.signed)(text, \*[, by, session, to_repo, run_gh]) | `text` with the writer's signature, for a comment on `to_repo` (default: the pile).         |
| [`plan`](#openloops.pile.plan)(number, kind, \*[, reading, by, ...])       | The steps that carry out one decision the owner said yes to, as data.                       |
| [`is_own_private`](#openloops.pile.is_own_private)(repo, \*, owner[, run_gh])        | True only for a `PRIVATE` repo of `owner`: anything else is treated as public.              |
| [`nudge`](#openloops.pile.nudge)(\*[, stale_days, at, repo, run_gh, ...])   | Keep one reminder coming while any pile item waits longer than `stale_days`.                |

### Classes

| [`PileItem`](#openloops.pile.PileItem)(number, title, said, hint, labels, ...)   | One capture.   |
|-----------------------------------------------------------------------------------------------------|----------------|

### openloops.pile.DFLT_STALE_DAYS *= 3.0*

An item older than this many days makes [`nudge()`](#openloops.pile.nudge) keep a reminder pending.

### openloops.pile.KINDS *= ('loop', 'idea', 'issue', 'work', 'done', 'drop', 'ask')*

What `apply()` can do with an item.

### openloops.pile.NUDGE_SOURCE *= 'pile-nudge'*

one per pile, found again by this.

* **Type:**
  The `source` of the nudge loop

### openloops.pile.PILE_LABEL *= 'pile'*

The label every untriaged capture carries.

### *class* openloops.pile.PileItem(number, title, said, hint, labels, created, url, state='open', comments=tuple())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One capture. `said` is the dictation, with the Shortcut’s hint line removed.

### openloops.pile.RESULT *= '{result}'*

The placeholder a plan’s later steps carry for what the first step produced (an
issue URL, a loop id, an idea id). The caller substitutes it.

### openloops.pile.agent_identity(by=None, session=None, , env=None)

Who is writing: `by` (an agent or session name) and `session` (a URL or address).

Defaults: `OPENLOOPS_AGENT`; then Claude Code’s own variables, the Remote Control
session (`https://claude.ai/code/<CLAUDE_CODE_BRIDGE_SESSION_ID>`) or the local
session id (`claude-code:<CLAUDE_CODE_SESSION_ID>`). `session="none"` signs with
the name alone (a surface that is not this Claude Code session, such as a connector
started from one, passes it rather than borrow the session it inherited).

```pycon
>>> agent_identity(env={"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01X"})["session"]
'https://claude.ai/code/session_01X'
>>> agent_identity("bosun@tw", "none", env={"CLAUDE_CODE_SESSION_ID": "abc"})
{'by': 'bosun@tw', 'session': None}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### openloops.pile.heuristic_propose(item)

A first guess from the words alone. An agent’s reading replaces it (`proposer=`).

```pycon
>>> it = parse_item({"number": 3, "title": "x", "body": "Remind me to call Ana tomorrow",
...                  "labels": [], "createdAt": "2026-11-20T10:00:00Z", "url": "u"})
>>> heuristic_propose(it)["kind"]
'loop'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.pile.is_own_private(repo, , owner, run_gh=None)

True only for a `PRIVATE` repo of `owner`: anything else is treated as public.

Fails closed: an internal repo, another owner’s private repo (a client’s, shared with
other people), or a visibility that cannot be read all get the public treatment.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### openloops.pile.items(, repo=None, label='pile', limit=200, run_gh=None)

The open items carrying `label` (default: untriaged), oldest first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`PileItem`](#openloops.pile.PileItem)]

### openloops.pile.nudge(, stale_days=3.0, at='09:00', repo=None, run_gh=None, loops_api=None, now=None)

Keep one reminder coming while any pile item waits longer than `stale_days`.

Idempotent; run it from a timer. An item counts while it is on the pile (`pile`)
or handed to a session (`working`): a session that died leaves it there. When
something is stale, no nudge is still to come, and none was made in the last
`NUDGE_EVERY_HOURS`, it closes the nudges that already fired and makes one loop
(source `pile-nudge`) for the next `at` in the owner’s zone. The push says only the
count and the oldest age (it crosses a public relay). When nothing is stale, every
open nudge is withdrawn. It never touches a pile item.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.pile.parse_item(raw)

A [`PileItem`](#openloops.pile.PileItem) from `gh`’s JSON for one issue. Pure.

The hint is the first label that is not a status label, else the body’s
`— pile: <hint>` line (kept by the Shortcut in case a label is dropped).

```pycon
>>> parse_item({"number": 1, "title": "t", "body": "no hint here", "labels": [],
...             "createdAt": "2026-11-20T10:00:00Z", "url": "u"}).hint is None
True
```

* **Return type:**
  [`PileItem`](#openloops.pile.PileItem)

### openloops.pile.pile_repo(repo=None, , run_gh=None)

The pile repo: `repo`, else `OPENLOOPS_PILE_REPO`, else `<gh login>/_pile`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.pile.plan(number, kind, , reading=None, by=None, session=None, title=None, when=None, reveal=False, target_repo=None, issue_body=None, tags=None, reason=None, force=False, repo=None, run_gh=None)

The steps that carry out one decision the owner said yes to, as data. Changes nothing.

openloops never writes to GitHub (ADR-008, ADR-014): the caller runs the steps in
order, with its own tools (`gh` in a Claude Code session, the connector’s comment
and create tools on a voice surface), substituting [`RESULT`](#openloops.pile.RESULT) in later steps
with what the first step produced. `reading` is the agent’s interpretation, and
opens the signed comment. Per `kind`:

- `loop`: `remind` (`ol remind`; source = the item’s URL), then close as routed;
  `title` is required with `reveal` (the push crosses a public relay);
- `idea`: `idea` (`ideadump add` with the dictation verbatim), then close as routed;
- `issue`: `create_issue` in `target_repo` (`title` + `issue_body`
  required); anything but a private repo of the pile’s owner gets that text only,
  no pile link and no session link;
- `work`: hand-off to a session; labelled `working` and left open; the session
  posts [`signed()`](#openloops.pile.signed) notes and finishes with `done`;
- `done`: close as routed, `reason` = the evidence;
- `drop`: close as not planned, `reason` required (never silent);
- `ask`: stays on the pile, labelled `needs-owner`, `reason` = the question.

A destination already recorded on the item (a `→ issue/loop/idea` line from an
earlier, half-run plan) refuses a second one unless `force`: finish that plan’s
remaining steps instead. The pile itself must be a private repo of its owner.

Step ops: `remind`, `idea`, `create_issue`, `comment`, `labels`, `close`
(`reason` in `gh`’s spelling, `rest_reason` in the REST API’s).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.pile.propose(found, \*, proposer=<function heuristic_propose>)

One proposal per item. Proposals change nothing; `apply()` acts on a yes.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.pile.show(number, , repo=None, run_gh=None)

One item with its comments (any state).

* **Return type:**
  [`PileItem`](#openloops.pile.PileItem)

### openloops.pile.signature(by, session=None, , public=False)

The last lines of every comment an agent writes here.

On a public repo only the name: a session link is private context.

```pycon
>>> print(signature("gtd-capture@mac", "https://claude.ai/code/session_01X"))

—
Agent: gtd-capture@mac
Claude-Session: https://claude.ai/code/session_01X
>>> signature("gtd-capture@mac", "https://claude.ai/code/session_01X", public=True).splitlines()[-1]
'Agent: gtd-capture@mac'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.pile.signed(text, , by=None, session=None, to_repo=None, run_gh=None)

`text` with the writer’s signature, for a comment on `to_repo` (default: the pile).

The session link is kept only when `to_repo` is a private repo of the pile’s owner;
anywhere else (public, internal, a client’s, unreadable) the name alone.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
