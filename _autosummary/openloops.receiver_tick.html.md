# openloops.receiver_tick

One tick of the board-receiver job: check for work without a model, then hand over.

ADR-011. A launchd `StartInterval` job runs this every few minutes. Starting a Claude
session on every tick would cost money while nothing is pending, so the tick first asks
the board store, with plain HTTP and no model, whether anything needs the receiver.
Only if something does (or the question cannot be answered) does it replace itself with
the real command, `claude -p <the receiver prompt>`.

**Liveness.** Every successful check writes the board’s `meta/receiver` heartbeat
(the receiver’s own document, under the session name from `board/board.json`), so an
idle board stays green and a dead job turns it amber after 20 minutes. It also touches a
local `board-receiver.lastcheck` stamp, which `ol receiver-job-status` reports as
“last check”, separately from “last work” (the log, written only by ticks with work).

**Fail closed on configuration, open on anything else.** A configuration error (no
credentials file, a missing key, a cleartext origin, a refused sign-in, a 403 from the
store) cannot be fixed by a session, so the tick starts none and says so in the log on
every tick; the stale heartbeat turns the board amber. Any other failure (the store
down, a malformed answer, a bug here) starts the session anyway, because a check that
silently suppressed the receiver would be the failure this package exists to prevent.
Repeated failures back off exponentially: one hour, then two, four, capped at six.

This is the one module that talks to the network, to the owner’s own board store (the
HTTP API of ADR-009). Nothing imports it; `import openloops` never loads it.

The work set is the one `references/receiver.md` defines: events with no receipt,
`processing` receipts older than 15 minutes, and `queued` receipts and `failed`
receipts marked transient. Those last two are retried only once they are an hour old
([`RETRY_AFTER`](#openloops.receiver_tick.RETRY_AFTER)): a receipt that waits on another machine, a busy worker or a
lasting GitHub error would otherwise start a paid session every tick, all day, to change
nothing. The sign-in is the one in `references/receiver-http.md`.

### Module Attributes

| [`STALE_CLAIM`](#openloops.receiver_tick.STALE_CLAIM)       | A `processing` receipt older than this is a sweep that died (receiver.md, section 0).                                                                                                             |
|--------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`RETRY_AFTER`](#openloops.receiver_tick.RETRY_AFTER)       | A `queued` or transiently `failed` receipt is retried only once it is this old.                                                                                                                   |
| [`FAIL_OPEN_BACKOFF`](#openloops.receiver_tick.FAIL_OPEN_BACKOFF) | After a failed check starts a session, the next one waits this long, doubling with each further failure up to `FAIL_OPEN_CAP`: a lasting fault must not start a paid session every tick, all day. |

### Functions

| [`check`](#openloops.receiver_tick.check)([env_file, heartbeat_by, now])           | Ask the store whether anything needs the receiver.                              |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`pending_work`](#openloops.receiver_tick.pending_work)(outbox, receipts, \*[, now, ...]) | What needs the receiver, from the store's two collections (`id -> data`).       |
| [`read_env_file`](#openloops.receiver_tick.read_env_file)(path)                            | `KEY=VALUE` / `export KEY=VALUE` lines of an env file, parsed, never executed.  |
| [`main`](#openloops.receiver_tick.main)([argv])                                   | `python -m openloops.receiver_tick [--check-only] [--env-file F] [-- CMD ...]`. |

### Classes

| [`Pending`](#openloops.receiver_tick.Pending)([iterable])   | The reasons the receiver is needed; empty means nothing to do.   |
|------------------------------------------------------------------------|------------------------------------------------------------------|

### Exceptions

| [`ConfigError`](#openloops.receiver_tick.ConfigError)   | The check cannot run as configured, and a session could not fix that either.   |
|----------------------------------------------------------------|--------------------------------------------------------------------------------|

### *exception* openloops.receiver_tick.ConfigError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The check cannot run as configured, and a session could not fix that either.

### openloops.receiver_tick.FAIL_OPEN_BACKOFF *= datetime.timedelta(seconds=3600)*

After a failed check starts a session, the next one waits this long, doubling with
each further failure up to `FAIL_OPEN_CAP`: a lasting fault must not start a
paid session every tick, all day.

### *class* openloops.receiver_tick.Pending(iterable=(),)

Bases: [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

The reasons the receiver is needed; empty means nothing to do.

`total` counts the items behind those reasons (the heartbeat’s `pending`);
`heartbeat` says what [`check()`](#openloops.receiver_tick.check) did with the heartbeat.

#### keys *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({})*

The ids behind the reasons, so a start that would see the same set again backs off.

#### other_live *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

a session started now would stop at once.

* **Type:**
  Another receiver whose heartbeat is live

### openloops.receiver_tick.RETRY_AFTER *= datetime.timedelta(seconds=3600)*

A `queued` or transiently `failed` receipt is retried only once it is this old.

### openloops.receiver_tick.STALE_CLAIM *= datetime.timedelta(seconds=900)*

A `processing` receipt older than this is a sweep that died (receiver.md, section 0).

### openloops.receiver_tick.check(env_file=PosixPath('~/.config/openloops/board-receiver.env'), , heartbeat_by=None, now=None)

Ask the store whether anything needs the receiver. Raises if it cannot ask:
[`ConfigError`](#openloops.receiver_tick.ConfigError) when no session could fix it, anything else otherwise.

With *heartbeat_by* (the board’s session name) it also writes the `meta/receiver`
heartbeat, and says what happened in the result’s `heartbeat`. A failed heartbeat
never fails the check: the board turning amber is how that shows.

* **Return type:**
  [`Pending`](#openloops.receiver_tick.Pending)

### openloops.receiver_tick.main(argv=None)

`python -m openloops.receiver_tick [--check-only] [--env-file F] [-- CMD ...]`.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### openloops.receiver_tick.pending_work(outbox, receipts, , now=None, retry_after=datetime.timedelta(seconds=3600))

What needs the receiver, from the store’s two collections (`id -> data`).

`queued` and transiently `failed` receipts count only once their `at` (or,
lacking one, `claimedAt`) is older than *retry_after*; one with neither counts.

```pycon
>>> pending_work({'e1': {}}, {})
['1 event(s) without a receipt']
>>> pending_work({'e1': {}}, {'e1': {'status': 'posted'}})
[]
```

* **Return type:**
  [`Pending`](#openloops.receiver_tick.Pending)

### openloops.receiver_tick.read_env_file(path)

`KEY=VALUE` / `export KEY=VALUE` lines of an env file, parsed, never executed.

```pycon
>>> import tempfile, pathlib
>>> f = pathlib.Path(tempfile.mkdtemp()) / 'e'
>>> _ = f.write_text("# c\nexport A='x y'\nB=2\n\nbad line\n")
>>> read_env_file(f)
{'A': 'x y', 'B': '2'}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
