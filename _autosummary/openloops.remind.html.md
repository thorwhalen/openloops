# openloops.remind

Reminders: loops kept in a store and delivered through a channel that holds the time.

The runner over [`openloops.loops`](openloops.loops.html.md#module-openloops.loops) (ADR-013). The core modules never import this
one: it is where a store, a clock and a delivery channel are composed, and it is the
only openloops code that sends anything for a reminder.

How a reminder survives a sleeping machine: when a loop comes within the horizon (three
days, ntfy’s limit), it is **armed**, handed to ntfy as a scheduled message whose
sequence id is the loop’s id. ntfy delivers it at `remind_at` whether or not this
machine is awake. Done or snoozed first, the scheduled copy is cancelled or replaced
by the same id, but ntfy.sh does not honour that today ([`UNCANCELLABLE_NOTE`](#openloops.remind.UNCANCELLABLE_NOTE)), so
the result carries a `warning` that the original push may still arrive. A tick (`ol remind-tick`, hourly from a launchd job) arms loops that
came within the horizon, records the ones that fired, and delivers late, saying so,
anything that was never armed.

Three seams, each one keyword argument with a default that works:

- `store`: a `MutableMapping[str, Loop]`; default JSON files under
  `~/.local/share/openloops/loops/` ([`loops_store()`](#openloops.remind.loops_store)).
- `deliver`: an object with `schedule`, `now` and `cancel`; default
  [`NtfyDelivery`](#openloops.remind.NtfyDelivery), through correspond’s ntfy channel (

  ```
  ``
  ```

  pip install
  > openloops[remind]\`\`).
- `settings`: [`RemindSettings`](#openloops.remind.RemindSettings); default from the environment.

**Privacy.** ntfy.sh is a public relay: anyone holding the topic reads the push. A
push says only that a reminder is due unless the loop was made with `reveal=True`;
the title then travels too. Reveal short labels only, never names, clients or secrets.

### Module Attributes

| [`UNCANCELLABLE_NOTE`](#openloops.remind.UNCANCELLABLE_NOTE)   | a DELETE (or a replacement under the same sequence id) of a *scheduled* message is acknowledged with a `message_delete` event, yet the original is still delivered at its time.   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`loops_store`](#openloops.remind.loops_store)([rootdir])                         | The default store: `~/.local/share/openloops/loops/<id>.json`.                                                                                |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| [`parse_in`](#openloops.remind.parse_in)(text)                                 | A duration such as `20m`, `3h`, `2d` or `1h30m`.                                                                                              |
| [`parse_at`](#openloops.remind.parse_at)(text, \*, now, zone)                  | An ISO date-time (naive means `zone`), an ISO date (09:00 that day) or `HH:MM` (the next one).                                                |
| [`parse_when`](#openloops.remind.parse_when)(text, \*, now, zone)                | A duration from `now` (`3h`, `1h30m`) or a time ([`parse_at()`](#openloops.remind.parse_at)): the one form a CLI flag takes. |
| [`attach`](#openloops.remind.attach)(naive, zone)                            | `naive` read in `zone`; `None` means this machine's zone, DST rules included.                                                                 |
| [`local`](#openloops.remind.local)(when, zone)                              | `when` shown in `zone`, or in this machine's zone (DST-aware) when `None`.                                                                    |
| [`remind`](#openloops.remind.remind)(title, \*[, at, in_, due, reveal, ...]) | Make a loop that comes back at `at` (or after `in_`), arm it, and say when.                                                                   |
| [`list_loops`](#openloops.remind.list_loops)(\*[, state, store])                 | Loops as summaries, soonest first.                                                                                                            |
| [`done`](#openloops.remind.done)(ref, \*[, note, by, store, deliver, ...]) | Close a loop as done and cancel its scheduled push, if any.                                                                                   |
| [`snooze`](#openloops.remind.snooze)(ref, \*[, until, for_, by, store, ...]) | Bring a loop back later (`until` a time, or `for_` a duration); re-arms its push.                                                             |
| [`tick`](#openloops.remind.tick)(\*[, store, deliver, settings, now])      | Arm what came within the horizon, record what fired, deliver late what was missed.                                                            |
| [`find`](#openloops.remind.find)(store, ref)                               | A loop by id, by a unique prefix (with or without `loop-`), or by its hex suffix.                                                             |

### Classes

| [`RemindSettings`](#openloops.remind.RemindSettings)([channel, horizon_hours, ...])   | What the owner sets once.                                                   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`NtfyDelivery`](#openloops.remind.NtfyDelivery)([ref, send, get_channel])          | The default `deliver`: correspond's ntfy channel, one sequence id per loop. |
| [`LoopsStore`](#openloops.remind.LoopsStore)(files)                               | `Loop` records as `<id>.json` files, each write atomic.                     |

### Exceptions

| [`DeliveryError`](#openloops.remind.DeliveryError)   | The channel refused or could not be reached; the loop is left to the next tick.   |
|------------------------------------------------------------------|-----------------------------------------------------------------------------------|

### *exception* openloops.remind.DeliveryError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The channel refused or could not be reached; the loop is left to the next tick.

### *class* openloops.remind.LoopsStore(files)

Bases: [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

`Loop` records as `<id>.json` files, each write atomic.

### *class* openloops.remind.NtfyDelivery(ref='ntfy:', , send=None, get_channel=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default `deliver`: correspond’s ntfy channel, one sequence id per loop.

`send` and `get_channel` default to correspond’s, imported when first used, so
`import openloops.remind` costs nothing and tests inject fakes.

### *class* openloops.remind.RemindSettings(channel='ntfy:', horizon_hours=71.0, generic_title='Reminder', generic_text='A reminder you set is due.', tz=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the owner sets once. `from_env` reads `OPENLOOPS_REMIND_*` and `OPENLOOPS_TZ`.

`channel` is a correspond reference (`ntfy:` is the default topic). `tz` is an
IANA zone for reading and echoing times; `None` uses the machine’s own, with its
daylight-saving rules applied per instant. `horizon_hours` is capped at 71 (ntfy
schedules three days ahead at most).

#### *property* channel_label *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

a topic in the reference is a bearer secret.

* **Type:**
  The channel’s name only

#### *property* zone

A `ZoneInfo`, or `None` for the machine’s own zone (see [`attach()`](#openloops.remind.attach)).

### openloops.remind.UNCANCELLABLE_NOTE *= 'ntfy.sh still delivers a scheduled push that was cancelled or replaced, so the original push may arrive at {at} anyway'*

a DELETE (or a replacement under the same sequence
id) of a *scheduled* message is acknowledged with a `message_delete` event, yet the
original is still delivered at its time. ntfy’s documentation says otherwise; until
the server honours it, an early `done` or `snooze` is said, not hidden.

* **Type:**
  Measured on ntfy.sh, 2026-11-19

### openloops.remind.attach(naive, zone)

`naive` read in `zone`; `None` means this machine’s zone, DST rules included.

```pycon
>>> attach(datetime(2026, 7, 1, 9, 0), timezone.utc).isoformat()
'2026-07-01T09:00:00+00:00'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### openloops.remind.done(ref, , note=None, by='owner', store=None, deliver=None, settings=None, now=None)

Close a loop as done and cancel its scheduled push, if any.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.remind.find(store, ref)

A loop by id, by a unique prefix (with or without `loop-`), or by its hex suffix.

* **Return type:**
  [`Loop`](openloops.loops.html.md#openloops.loops.Loop)

### openloops.remind.list_loops(, state='open', store=None)

Loops as summaries, soonest first. `state`: `open`, `closed`, `all` or one A2A state.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### openloops.remind.local(when, zone)

`when` shown in `zone`, or in this machine’s zone (DST-aware) when `None`.

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### openloops.remind.loops_store(rootdir=None)

The default store: `~/.local/share/openloops/loops/<id>.json`.

* **Return type:**
  [`LoopsStore`](#openloops.remind.LoopsStore)

### openloops.remind.parse_at(text, , now, zone)

An ISO date-time (naive means `zone`), an ISO date (09:00 that day) or `HH:MM`
(the next one). Natural language is the calling agent’s job, not this function’s.

```pycon
>>> z = timezone.utc
>>> now = datetime(2026, 11, 19, 12, 0, tzinfo=z)
>>> parse_at("09:30", now=now, zone=z).isoformat()
'2026-11-20T09:30:00+00:00'
>>> parse_at("2026-11-21", now=now, zone=z).isoformat()
'2026-11-21T09:00:00+00:00'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### openloops.remind.parse_in(text)

A duration such as `20m`, `3h`, `2d` or `1h30m`.

```pycon
>>> parse_in("1h30m")
datetime.timedelta(seconds=5400)
```

* **Return type:**
  [`timedelta`](https://docs.python.org/3/library/datetime.html#datetime.timedelta)

### openloops.remind.parse_when(text, , now, zone)

A duration from `now` (`3h`, `1h30m`) or a time ([`parse_at()`](#openloops.remind.parse_at)): the one form a CLI flag takes.

```pycon
>>> now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
>>> parse_when("3h", now=now, zone=timezone.utc).isoformat()
'2026-11-19T15:00:00+00:00'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### openloops.remind.remind(title, , at=None, in_=None, due=None, reveal=False, source=None, by='owner', store=None, deliver=None, settings=None, now=None)

Make a loop that comes back at `at` (or after `in_`), arm it, and say when.

Give at most one of `at` and `in_`; with neither, the loop is listed but never
pushed. Returns the loop’s summary and `echo`, the one line to repeat to the owner.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.remind.snooze(ref, , until=None, for_=None, by='owner', store=None, deliver=None, settings=None, now=None)

Bring a loop back later (`until` a time, or `for_` a duration); re-arms its push.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.remind.tick(, store=None, deliver=None, settings=None, now=None)

Arm what came within the horizon, record what fired, deliver late what was missed.

Model-free and idempotent: run it as often as you like (the launchd job runs it
hourly). Returns counts per action and the loops whose channel call failed.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
