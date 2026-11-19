# openloops.loops

Loops: the one record of a commitment, and the pure function that says what is due.

A **loop** is an open loop in David Allen’s sense: a commitment held somewhere other
than your head. It is one record whatever GTD list it sits on, so every list (In, Next,
Waiting For, Someday, the tickler) is a view over loops rather than a separate store.

Two vocabularies, kept apart on purpose (ADR-013):

- `state` is the **lifecycle**, in A2A’s seven names, the same ones equerry’s desk
  `Item` uses, so a loop is a desk item without translation. A reminder that is
  scheduled is `submitted` with a `remind_at`; once it fires it is
  `input-required`; done is `completed`; dismissed is `rejected`; withdrawn is
  `canceled`.
- `list` is the **GTD list**: `in`, `next`, `waiting`, `someday`,
  `reference`. “Scheduled” (the tickler) is not a list; it is a loop with a future
  `remind_at`.

Three times, never conflated: `remind_at` (when it comes back to you: the tickler,
GTD’s defer date), `due` (a deadline, a promise to someone) and `created`. All are
stored as UTC ISO strings.

Nothing here reads a clock, a file or the network: [`evaluate()`](#openloops.loops.evaluate) takes `now` and
returns the actions a runner should take ([`openloops.remind`](openloops.remind.html.md#module-openloops.remind) is that runner).

```pycon
>>> now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
>>> loop = new_loop("Send the signed draft", remind_at=now + timedelta(hours=3), now=now, id="loop-a")
>>> loop.state, loop.list
('submitted', 'next')
>>> [a["action"] for a in evaluate([loop], now)]
['arm']
```

### Module Attributes

| [`STATES`](#openloops.loops.STATES)            | The lifecycle, in A2A's names (the same as equerry's desk Item).                   |
|--------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`TERMINAL`](#openloops.loops.TERMINAL)          | Nothing leaves these.                                                              |
| [`LISTS`](#openloops.loops.LISTS)             | The GTD lists a loop can sit on.                                                   |
| [`MAX_HORIZON`](#openloops.loops.MAX_HORIZON)       | How far ahead a reminder is handed to the delivery channel's own scheduler.        |
| [`MIN_SCHEDULE_LEAD`](#openloops.loops.MIN_SCHEDULE_LEAD) | Below this lead a scheduled delivery is refused by ntfy (10 s), so it is sent now. |

### Functions

| [`new_loop`](#openloops.loops.new_loop)(title, \*[, remind_at, due, reveal, ...])   | A new loop, logged as created.                                                  |
|-------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`evaluate`](#openloops.loops.evaluate)(loops, now, \*[, horizon])                  | What a runner should do now, as data.                                           |
| [`complete`](#openloops.loops.complete)(loop, now, \*[, by, note])                  | Done.                                                                           |
| [`snooze`](#openloops.loops.snooze)(loop, until, now, \*[, by])                   | Bring it back at `until`: scheduled again, one more snooze counted.             |
| [`cancel`](#openloops.loops.cancel)(loop, now, \*[, by, note])                    | Withdrawn: it will not fire.                                                    |
| [`mark`](#openloops.loops.mark)(loop, now, event, \*[, by])                     | A copy with `changes` applied and one log entry appended.                       |
| [`to_utc`](#openloops.loops.to_utc)(when)                                         | A timezone-aware UTC datetime; a naive one is read as the machine's local time. |
| [`iso`](#openloops.loops.iso)(when)                                            | UTC ISO with a `Z`, to the second.                                              |

### Classes

| [`Loop`](#openloops.loops.Loop)(id, title, created[, state, list, ...])   | One commitment.   |
|-------------------------------------------------------------------------------------------------|-------------------|

### openloops.loops.LISTS *= ('in', 'next', 'waiting', 'someday', 'reference')*

The GTD lists a loop can sit on.

### *class* openloops.loops.Loop(id, title, created, state='submitted', list='next', remind_at=None, due=None, reveal=False, source=None, proposed_by=None, project=None, area=None, contexts=(), energy=None, minutes=None, waiting=None, available_when=None, done_when=None, snoozes=0, carried=0, armed=None, log=tuple(), extra=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One commitment. Most fields are optional; GTD-complete, v1 uses a few.

`source` is where it came from (`{kind, ref, quote, said_by}`): every loop an
agent makes is traceable. `proposed_by` is set when an agent proposed it and the
person has not accepted it; a proposal never pushes. `reveal` says whether a push
may carry the title (pushes cross a public relay by default). `armed` records the
delivery the channel holds (`{sequence_id, at}`), so it can be replaced or
cancelled. `log` is append-only.

#### extra *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

kept and written back.

* **Type:**
  Keys a newer writer added that this version does not know

#### *classmethod* from_dict(data)

Read a stored loop; keys this version does not know are kept in `extra`.

* **Return type:**
  [`Loop`](#openloops.loops.Loop)

### openloops.loops.MAX_HORIZON *= datetime.timedelta(days=2, seconds=82800)*

How far ahead a reminder is handed to the delivery channel’s own scheduler. ntfy
holds a scheduled message for at most three days; an hour’s margin absorbs a clock
that runs ahead of the server’s.

### openloops.loops.MIN_SCHEDULE_LEAD *= datetime.timedelta(seconds=15)*

Below this lead a scheduled delivery is refused by ntfy (10 s), so it is sent now.

### openloops.loops.STATES *= ('submitted', 'working', 'input-required', 'completed', 'failed', 'canceled', 'rejected')*

The lifecycle, in A2A’s names (the same as equerry’s desk Item).

### openloops.loops.TERMINAL *= frozenset({'canceled', 'completed', 'failed', 'rejected'})*

Nothing leaves these.

### openloops.loops.cancel(loop, now, , by='owner', note=None)

Withdrawn: it will not fire. A reason belongs in `note`.

* **Return type:**
  [`Loop`](#openloops.loops.Loop)

### openloops.loops.complete(loop, now, , by='owner', note=None)

Done. Refused on a loop already closed, so a second `done` is visible, not silent.

* **Return type:**
  [`Loop`](#openloops.loops.Loop)

### openloops.loops.evaluate(loops, now, , horizon=datetime.timedelta(days=2, seconds=82800))

What a runner should do now, as data. Pure: same loops and `now`, same actions.

For each open, accepted loop with a `remind_at`:

- `arm`: due within `horizon` and not yet handed to the channel at that time.
  The channel delivers it at `remind_at` even if this machine is asleep then.
- `deliver`: due and never armed (created late, or arming failed, or the machine
  slept past the horizon). Sent now, saying how late.
- `woke`: due and armed, so the channel has delivered it; the loop now needs its
  owner (`input-required`).
- `disarm`: closed but still armed, or moved (snoozed) outside the horizon while
  armed at its old time: cancel the channel’s copy.

Proposals (`proposed_by` set) never produce a delivery.

```pycon
>>> now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
>>> far = new_loop("x", remind_at=now + timedelta(days=5), now=now, id="far")
>>> late = new_loop("y", remind_at=now - timedelta(minutes=5), now=now, id="late")
>>> [(a["action"], a["id"]) for a in evaluate([far, late], now)]
[('deliver', 'late')]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.loops.iso(when)

UTC ISO with a `Z`, to the second.

```pycon
>>> iso(datetime(2026, 11, 19, 12, 0, 30, 999, tzinfo=timezone.utc))
'2026-11-19T12:00:30Z'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### openloops.loops.mark(loop, now, event, , by='tick', \*\*changes)

A copy with `changes` applied and one log entry appended.

* **Return type:**
  [`Loop`](#openloops.loops.Loop)

### openloops.loops.new_loop(title, , remind_at=None, due=None, reveal=False, source=None, by='owner', now=None, id=None, \*\*extra)

A new loop, logged as created. `extra` takes any other [`Loop`](#openloops.loops.Loop) field.

A loop the owner asked for goes on `next`; `list` in `extra` overrides it.

* **Return type:**
  [`Loop`](#openloops.loops.Loop)

### openloops.loops.snooze(loop, until, now, , by='owner')

Bring it back at `until`: scheduled again, one more snooze counted.

* **Return type:**
  [`Loop`](#openloops.loops.Loop)

### openloops.loops.to_utc(when)

A timezone-aware UTC datetime; a naive one is read as the machine’s local time.

```pycon
>>> to_utc("2026-11-19T12:00:00Z").isoformat()
'2026-11-19T12:00:00+00:00'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)
