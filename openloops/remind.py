"""Reminders: loops kept in a store and delivered through a channel that holds the time.

The runner over :mod:`openloops.loops` (ADR-013). The core modules never import this
one: it is where a store, a clock and a delivery channel are composed, and it is the
only openloops code that sends anything for a reminder.

How a reminder survives a sleeping machine: when a loop comes within the horizon (three
days, ntfy's limit), it is **armed**, handed to ntfy as a scheduled message whose
sequence id is the loop's id. ntfy delivers it at ``remind_at`` whether or not this
machine is awake. Done or snoozed first, the scheduled copy is cancelled or replaced
by the same id, but ntfy.sh does not honour that today (:data:`UNCANCELLABLE_NOTE`), so
the result carries a ``warning`` that the original push may still arrive. A tick (``ol remind-tick``, hourly from a launchd job) arms loops that
came within the horizon, records the ones that fired, and delivers late, saying so,
anything that was never armed.

Three seams, each one keyword argument with a default that works:

- ``store``: a ``MutableMapping[str, Loop]``; default JSON files under
  ``~/.local/share/openloops/loops/`` (:func:`loops_store`).
- ``deliver``: an object with ``schedule``, ``now`` and ``cancel``; default
  :class:`NtfyDelivery`, through correspond's ntfy channel (``pip install
  openloops[remind]``).
- ``settings``: :class:`RemindSettings`; default from the environment.

**Privacy.** ntfy.sh is a public relay: anyone holding the topic reads the push. A
push says only that a reminder is due unless the loop was made with ``reveal=True``;
the title then travels too. Reveal short labels only, never names, clients or secrets.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openloops import loops as _loops
from openloops.loops import Loop
from openloops.store import AtomicTextFiles, data_dir

__all__ = [
    "RemindSettings",
    "NtfyDelivery",
    "DeliveryError",
    "LoopsStore",
    "loops_store",
    "parse_in",
    "parse_at",
    "parse_when",
    "attach",
    "local",
    "remind",
    "list_loops",
    "done",
    "snooze",
    "tick",
    "find",
    "UNCANCELLABLE_NOTE",
]


class DeliveryError(RuntimeError):
    """The channel refused or could not be reached; the loop is left to the next tick."""


@dataclass(frozen=True)
class RemindSettings:
    """What the owner sets once. ``from_env`` reads ``OPENLOOPS_REMIND_*`` and ``OPENLOOPS_TZ``.

    ``channel`` is a correspond reference (``ntfy:`` is the default topic). ``tz`` is an
    IANA zone for reading and echoing times; ``None`` uses the machine's own, with its
    daylight-saving rules applied per instant. ``horizon_hours`` is capped at 71 (ntfy
    schedules three days ahead at most).
    """

    channel: str = "ntfy:"
    horizon_hours: float = 71.0
    generic_title: str = "Reminder"
    generic_text: str = "A reminder you set is due."
    tz: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RemindSettings:
        env = os.environ if environ is None else environ
        kwargs: dict[str, Any] = {}
        if env.get("OPENLOOPS_REMIND_CHANNEL"):
            kwargs["channel"] = env["OPENLOOPS_REMIND_CHANNEL"]
        if env.get("OPENLOOPS_REMIND_HORIZON_HOURS"):
            kwargs["horizon_hours"] = float(env["OPENLOOPS_REMIND_HORIZON_HOURS"])
        if env.get("OPENLOOPS_TZ"):
            kwargs["tz"] = env["OPENLOOPS_TZ"]
        return cls(**kwargs)

    @property
    def horizon(self) -> timedelta:
        return min(timedelta(hours=self.horizon_hours), _loops.MAX_HORIZON)

    @property
    def zone(self):
        """A ``ZoneInfo``, or ``None`` for the machine's own zone (see :func:`attach`)."""
        return ZoneInfo(self.tz) if self.tz else None

    @property
    def channel_label(self) -> str:
        """The channel's name only: a topic in the reference is a bearer secret."""
        return self.channel.partition(":")[0] + ":"


def attach(naive: datetime, zone) -> datetime:
    """``naive`` read in ``zone``; ``None`` means this machine's zone, DST rules included.

    >>> attach(datetime(2026, 7, 1, 9, 0), timezone.utc).isoformat()
    '2026-07-01T09:00:00+00:00'
    """
    return naive.replace(tzinfo=zone) if zone is not None else naive.astimezone()


def local(when: datetime, zone) -> datetime:
    """``when`` shown in ``zone``, or in this machine's zone (DST-aware) when ``None``."""
    return when.astimezone(zone) if zone is not None else when.astimezone()


class NtfyDelivery:
    """The default ``deliver``: correspond's ntfy channel, one sequence id per loop.

    ``send`` and ``get_channel`` default to correspond's, imported when first used, so
    ``import openloops.remind`` costs nothing and tests inject fakes.
    """

    def __init__(self, ref: str = "ntfy:", *, send=None, get_channel=None):
        self.ref = ref
        self._send = send
        self._get_channel = get_channel

    def _correspond(self):
        if self._send is None or self._get_channel is None:
            try:
                import correspond
            except ImportError as exc:  # pragma: no cover - depends on the extra
                raise DeliveryError(
                    "reminders deliver through correspond, which needs Python 3.11+: "
                    "pip install 'openloops[remind]'"
                ) from exc
            self._send = self._send or correspond.send
            self._get_channel = self._get_channel or correspond.get_channel
        return self._send, self._get_channel

    def _publish(self, loop: Loop, *, title: str, text: str, at: datetime | None):
        send, _ = self._correspond()
        native: dict[str, Any] = {"sequence_id": loop.id}
        if at is not None:
            native["at"] = int(at.timestamp())
        try:
            result = send(self.ref, text, title=title, priority="high", native=native)
        except Exception as exc:  # correspond raises its own error types
            raise DeliveryError(f"{type(exc).__name__}: {exc}") from exc
        if not result.ok:
            raise DeliveryError(result.error or "the channel refused the message")

    def schedule(self, loop: Loop, *, at: datetime, title: str, text: str) -> None:
        self._publish(loop, title=title, text=text, at=at)

    def now(self, loop: Loop, *, title: str, text: str) -> None:
        self._publish(loop, title=title, text=text, at=None)

    def cancel(self, loop: Loop) -> None:
        send, get_channel = self._correspond()
        channel_name, _, topic = self.ref.partition(":")
        try:
            channel = get_channel(channel_name)
            channel.cancel(channel.parse_ref(topic), loop.id)
        except Exception as exc:  # correspond raises its own error types
            raise DeliveryError(str(exc)) from exc


class LoopsStore(MutableMapping):
    """``Loop`` records as ``<id>.json`` files, each write atomic."""

    def __init__(self, files: MutableMapping[str, str]):
        self.files = files

    def __getitem__(self, key: str) -> Loop:
        return Loop.from_dict(json.loads(self.files[f"{key}.json"]))

    def __setitem__(self, key: str, loop: Loop) -> None:
        if key != loop.id:
            raise KeyError(f"key {key!r} is not the loop's id {loop.id!r}")
        self.files[f"{key}.json"] = json.dumps(loop.to_dict(), indent=1) + "\n"

    def __delitem__(self, key: str) -> None:
        del self.files[f"{key}.json"]

    def __iter__(self) -> Iterator[str]:
        for name in self.files:
            if name.endswith(".json") and "/" not in name:
                yield name[: -len(".json")]

    def __len__(self) -> int:
        return sum(1 for _ in self)


def loops_store(rootdir: str | Path | None = None) -> LoopsStore:
    """The default store: ``~/.local/share/openloops/loops/<id>.json``."""
    root = Path(rootdir).expanduser() if rootdir else data_dir() / "loops"
    return LoopsStore(AtomicTextFiles(root))


_ISO = r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?)?"
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*([smhdw])")
_UNIT = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_in(text: str) -> timedelta:
    """A duration such as ``20m``, ``3h``, ``2d`` or ``1h30m``.

    >>> parse_in("1h30m")
    datetime.timedelta(seconds=5400)
    """
    cleaned = text.strip().lower().replace(" ", "")
    parts = _DURATION.findall(cleaned)
    if not parts or "".join(n + u for n, u in parts) != cleaned:
        raise ValueError(f"not a duration: {text!r} (use e.g. 20m, 3h, 2d, 1h30m)")
    return sum((timedelta(**{_UNIT[u]: float(n)}) for n, u in parts), timedelta())


def parse_at(text: str, *, now: datetime, zone) -> datetime:
    """An ISO date-time (naive means ``zone``), an ISO date (09:00 that day) or ``HH:MM``
    (the next one). Natural language is the calling agent's job, not this function's.

    >>> z = timezone.utc
    >>> now = datetime(2026, 11, 19, 12, 0, tzinfo=z)
    >>> parse_at("09:30", now=now, zone=z).isoformat()
    '2026-11-20T09:30:00+00:00'
    >>> parse_at("2026-11-21", now=now, zone=z).isoformat()
    '2026-11-21T09:00:00+00:00'
    """
    raw = text.strip()
    hint = f"not a time: {text!r} (use HH:MM, YYYY-MM-DD, or YYYY-MM-DDTHH:MM)"
    if re.fullmatch(r"\d{1,2}:\d{2}", raw):
        hour, minute = map(int, raw.split(":"))
        if hour > 23 or minute > 59:
            raise ValueError(hint)
        today = local(now, zone).replace(tzinfo=None)
        naive = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if attach(naive, zone) <= now:
            naive += timedelta(days=1)
        return attach(naive, zone)
    if not re.fullmatch(_ISO, raw):
        raise ValueError(hint)
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        raise ValueError(hint) from None
    if len(raw) == 10:  # a date alone: 09:00 that day
        when = when.replace(hour=9)
    return when if when.tzinfo else attach(when, zone)


def parse_when(text: str, *, now: datetime, zone) -> datetime:
    """A duration from ``now`` (``3h``, ``1h30m``) or a time (:func:`parse_at`): the one form a CLI flag takes.

    >>> now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    >>> parse_when("3h", now=now, zone=timezone.utc).isoformat()
    '2026-11-19T15:00:00+00:00'
    """
    try:
        return now + parse_in(text)
    except ValueError:
        return parse_at(text, now=now, zone=zone)


def _as_time(value: str | datetime, *, now: datetime, zone) -> datetime:
    """A string through :func:`parse_when`; a naive datetime read in ``zone``."""
    if isinstance(value, str):
        return parse_when(value, now=now, zone=zone)
    return value if value.tzinfo else attach(value, zone)


def _load(store: Mapping[str, Loop]) -> tuple[list[Loop], list[str]]:
    """Every loop that reads; the keys of those that do not (one bad file must not stop the rest)."""
    loops, skipped = [], []
    for key in list(store):
        try:
            loop = store[key]
        except (KeyError, ValueError, TypeError) as exc:
            skipped.append(f"{key}: {type(exc).__name__}")
            continue
        if loop.id != key:
            skipped.append(f"{key}: holds {loop.id}")
            continue
        loops.append(loop)
    return loops, skipped


def _resolve(store, deliver, settings):
    settings = settings or RemindSettings.from_env()
    store = loops_store() if store is None else store
    deliver = NtfyDelivery(settings.channel) if deliver is None else deliver
    return store, deliver, settings


def find(store: Mapping[str, Loop], ref: str) -> Loop:
    """A loop by id, by a unique prefix (with or without ``loop-``), or by its hex suffix."""
    ref = (ref or "").strip()
    if not ref:
        raise KeyError("name a loop: its id, a unique prefix, or its last part")
    if ref in store:
        return store[ref]
    matches = [
        k
        for k in store
        if k.startswith(ref) or k.startswith(f"loop-{ref}") or k.endswith(f"-{ref}")
    ]
    if len(matches) == 1:
        return store[matches[0]]
    if not matches:
        raise KeyError(f"no loop {ref!r}")
    raise KeyError(
        f"{ref!r} matches {len(matches)} loops: {', '.join(sorted(matches))}"
    )


def _push_text(loop: Loop, settings: RemindSettings, *, late_minutes: int = 0):
    title = loop.title if loop.reveal else settings.generic_title
    text = loop.title if loop.reveal else settings.generic_text
    if late_minutes > 1:
        text += f" (late by {late_minutes} min)"
    return title[:120], text


def _apply(
    loop: Loop, action: Mapping[str, Any], *, deliver, settings, now: datetime
) -> Loop:
    """Carry out one evaluator action; a channel failure is logged and left for the next tick."""
    kind = action["action"]
    try:
        if kind == "arm":
            at = _loops.to_utc(action["at"])
            title, text = _push_text(loop, settings)
            if at - now < _loops.MIN_SCHEDULE_LEAD:
                deliver.now(loop, title=title, text=text)
                return _loops.mark(
                    loop, now, "woke", state="input-required", armed=None
                )
            deliver.schedule(loop, at=at, title=title, text=text)
            return _loops.mark(
                loop,
                now,
                "armed",
                armed={"sequence_id": loop.id, "at": action["at"]},
                note=f"scheduled on {settings.channel_label} for {action['at']}",
            )
        if kind == "deliver":
            title, text = _push_text(
                loop, settings, late_minutes=action["late_minutes"]
            )
            deliver.now(loop, title=title, text=text)
            return _loops.mark(
                loop,
                now,
                "woke",
                state="input-required",
                armed=None,
                note=f"delivered late by {action['late_minutes']} min"
                if action["late_minutes"] > 1
                else None,
            )
        if kind == "woke":
            return _loops.mark(loop, now, "woke", state="input-required")
        if kind == "disarm":
            deliver.cancel(loop)
            return _loops.mark(loop, now, "disarmed", armed=None)
    except DeliveryError as exc:
        return _failed(loop, now, f"{kind}: {exc}")
    raise ValueError(f"unknown action {kind!r}")


def _failed(loop: Loop, now: datetime, note: str) -> Loop:
    """Log a channel failure; a repeat of the last one is counted, not appended again."""
    last = loop.log[-1] if loop.log else {}
    if last.get("event") == "delivery-failed" and last.get("note") == note:
        again = {**last, "count": last.get("count", 1) + 1, "last_at": _loops.iso(now)}
        return replace(loop, log=(*loop.log[:-1], again))
    return _loops.mark(loop, now, "delivery-failed", by="tick", note=note)


def _settle(loop: Loop, *, store, deliver, settings, now: datetime) -> Loop:
    """Evaluate one loop now, apply what it needs, save it."""
    for action in _loops.evaluate([loop], now, horizon=settings.horizon):
        loop = _apply(loop, action, deliver=deliver, settings=settings, now=now)
    store[loop.id] = loop
    return loop


def _echo(loop: Loop, settings: RemindSettings, now: datetime) -> str:
    if not loop.remind_at:
        return "no time set: listed by `ol loops`, never pushed"
    when = _loops.to_utc(loop.remind_at)
    shown = local(when, settings.zone)
    delta = when - now
    hours, rest = divmod(-(-int(delta.total_seconds()) // 60), 60)  # round up
    days, hours = divmod(hours, 24)
    ahead = (
        f"{days}d {hours}h" if days else (f"{hours}h {rest}m" if hours else f"{rest}m")
    )
    failed = loop.log and loop.log[-1].get("event") == "delivery-failed"
    if failed:
        how = "NOT scheduled (the channel failed; the next tick retries)"
    elif loop.armed:
        how = f"push via {settings.channel_label}"
    elif loop.state == "input-required":
        how = f"pushed now via {settings.channel_label}"
    else:
        how = "pushed once it is within 3 days (the hourly tick arms it)"
    reveal = "" if loop.reveal else " (title not sent)"
    return f"{shown:%a %d %b %H:%M %Z} (in {ahead}), {how}{reveal}"


#: Measured on ntfy.sh, 2026-11-19: a DELETE (or a replacement under the same sequence
#: id) of a *scheduled* message is acknowledged with a ``message_delete`` event, yet the
#: original is still delivered at its time. ntfy's documentation says otherwise; until
#: the server honours it, an early ``done`` or ``snooze`` is said, not hidden.
UNCANCELLABLE_NOTE = (
    "ntfy.sh still delivers a scheduled push that was cancelled or replaced, so the "
    "original push may arrive at {at} anyway"
)


def _pending_push(loop: Loop, now: datetime) -> str | None:
    """The time of a scheduled push still ahead of ``now``, if the loop had one armed."""
    armed_at = (loop.armed or {}).get("at")
    if armed_at and _loops.to_utc(armed_at) > now:
        return armed_at
    return None


def _warning(pending: str | None, settings: RemindSettings) -> dict[str, str]:
    if not pending:
        return {}
    shown = local(_loops.to_utc(pending), settings.zone)
    return {"warning": UNCANCELLABLE_NOTE.format(at=f"{shown:%a %d %b %H:%M}")}


def _summary(loop: Loop) -> dict[str, Any]:
    last = loop.log[-1] if loop.log else {}
    return {
        "id": loop.id,
        "title": loop.title,
        "state": loop.state,
        "list": loop.list,
        "remind_at": loop.remind_at,
        "due": loop.due,
        "armed": bool(loop.armed),
        "reveal": loop.reveal,
        "snoozes": loop.snoozes,
        "last_event": last.get("event"),
        "last_note": last.get("note"),
    }


def remind(
    title: str,
    *,
    at: str | datetime | None = None,
    in_: str | timedelta | None = None,
    due: str | datetime | None = None,
    reveal: bool = False,
    source: Mapping[str, Any] | None = None,
    by: str = "owner",
    store: MutableMapping[str, Loop] | None = None,
    deliver: Any = None,
    settings: RemindSettings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Make a loop that comes back at ``at`` (or after ``in_``), arm it, and say when.

    Give at most one of ``at`` and ``in_``; with neither, the loop is listed but never
    pushed. Returns the loop's summary and ``echo``, the one line to repeat to the owner.
    """
    store, deliver, settings = _resolve(store, deliver, settings)
    now = _loops.to_utc(now or datetime.now(timezone.utc))
    if at is not None and in_ is not None:
        raise ValueError("give a time (at) or a delay (in), not both")
    when = None
    if in_ is not None:
        when = now + (parse_in(in_) if isinstance(in_, str) else in_)
    elif at is not None:
        when = _as_time(at, now=now, zone=settings.zone)
    if when is not None and _loops.to_utc(when) <= now:
        shown = local(_loops.to_utc(when), settings.zone)
        raise ValueError(f"{shown:%a %d %b %H:%M} is not in the future")
    if due is not None:
        due = _as_time(due, now=now, zone=settings.zone)
    loop = _loops.new_loop(
        title, remind_at=when, due=due, reveal=reveal, source=source, by=by, now=now
    )
    loop = _settle(loop, store=store, deliver=deliver, settings=settings, now=now)
    return {**_summary(loop), "echo": _echo(loop, settings, now)}


def list_loops(
    *,
    state: str = "open",
    store: Mapping[str, Loop] | None = None,
) -> list[dict[str, Any]]:
    """Loops as summaries, soonest first. ``state``: ``open``, ``closed``, ``all`` or one A2A state."""
    store = loops_store() if store is None else store
    rows = []
    for loop in _load(store)[0]:
        if (
            state == "all"
            or (state == "open" and loop.open)
            or (state == "closed" and not loop.open)
            or loop.state == state
        ):
            rows.append(_summary(loop))
    far = "9999"
    return sorted(rows, key=lambda r: (r["remind_at"] or far, r["id"]))


def done(
    ref: str,
    *,
    note: str | None = None,
    by: str = "owner",
    store: MutableMapping[str, Loop] | None = None,
    deliver: Any = None,
    settings: RemindSettings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Close a loop as done and cancel its scheduled push, if any."""
    store, deliver, settings = _resolve(store, deliver, settings)
    now = _loops.to_utc(now or datetime.now(timezone.utc))
    before = find(store, ref)
    pending = _pending_push(before, now)
    loop = _loops.complete(before, now, by=by, note=note)
    loop = _settle(loop, store=store, deliver=deliver, settings=settings, now=now)
    return {**_summary(loop), **_warning(pending, settings)}


def snooze(
    ref: str,
    *,
    until: str | datetime | None = None,
    for_: str | timedelta | None = None,
    by: str = "owner",
    store: MutableMapping[str, Loop] | None = None,
    deliver: Any = None,
    settings: RemindSettings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bring a loop back later (``until`` a time, or ``for_`` a duration); re-arms its push."""
    store, deliver, settings = _resolve(store, deliver, settings)
    now = _loops.to_utc(now or datetime.now(timezone.utc))
    if (until is None) == (for_ is None):
        raise ValueError("give either until (a time) or for (a duration)")
    if for_ is not None:
        when = now + (parse_in(for_) if isinstance(for_, str) else for_)
    else:
        when = _as_time(until, now=now, zone=settings.zone)
    before = find(store, ref)
    pending = _pending_push(before, now)
    loop = _loops.snooze(before, when, now, by=by)
    loop = _settle(loop, store=store, deliver=deliver, settings=settings, now=now)
    return {
        **_summary(loop),
        "echo": _echo(loop, settings, now),
        **_warning(pending, settings),
    }


def tick(
    *,
    store: MutableMapping[str, Loop] | None = None,
    deliver: Any = None,
    settings: RemindSettings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Arm what came within the horizon, record what fired, deliver late what was missed.

    Model-free and idempotent: run it as often as you like (the launchd job runs it
    hourly). Returns counts per action and the loops whose channel call failed.
    """
    store, deliver, settings = _resolve(store, deliver, settings)
    now = _loops.to_utc(now or datetime.now(timezone.utc))
    loops, skipped = _load(store)
    counts: dict[str, int] = {}
    failed: list[str] = []
    by_id = {loop.id: loop for loop in loops}
    for action in _loops.evaluate(loops, now, horizon=settings.horizon):
        seen = by_id[action["id"]]
        try:
            current = store[seen.id]
        except (KeyError, ValueError, TypeError):
            continue
        if current != seen:
            # Changed since this tick read it (an `ol done` meanwhile): judge it afresh.
            redo = _loops.evaluate([current], now, horizon=settings.horizon)
            if not redo:
                continue
            action = redo[0]
        loop = _apply(current, action, deliver=deliver, settings=settings, now=now)
        store[loop.id] = loop
        if loop.log[-1].get("event") == "delivery-failed":
            failed.append(loop.id)
        else:
            counts[action["action"]] = counts.get(action["action"], 0) + 1
    return {
        "at": _loops.iso(now),
        "loops": len(loops),
        "open": sum(1 for loop in loops if loop.open),
        "actions": counts,
        "failed": failed,
        "skipped": skipped,
    }
