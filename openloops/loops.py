"""Loops: the one record of a commitment, and the pure function that says what is due.

A **loop** is an open loop in David Allen's sense: a commitment held somewhere other
than your head. It is one record whatever GTD list it sits on, so every list (In, Next,
Waiting For, Someday, the tickler) is a view over loops rather than a separate store.

Two vocabularies, kept apart on purpose (ADR-013):

- ``state`` is the **lifecycle**, in A2A's seven names, the same ones equerry's desk
  ``Item`` uses, so a loop is a desk item without translation. A reminder that is
  scheduled is ``submitted`` with a ``remind_at``; once it fires it is
  ``input-required``; done is ``completed``; dismissed is ``rejected``; withdrawn is
  ``canceled``.
- ``list`` is the **GTD list**: ``in``, ``next``, ``waiting``, ``someday``,
  ``reference``. "Scheduled" (the tickler) is not a list; it is a loop with a future
  ``remind_at``.

Three times, never conflated: ``remind_at`` (when it comes back to you: the tickler,
GTD's defer date), ``due`` (a deadline, a promise to someone) and ``created``. All are
stored as UTC ISO strings.

Nothing here reads a clock, a file or the network: :func:`evaluate` takes ``now`` and
returns the actions a runner should take (:mod:`openloops.remind` is that runner).

>>> now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
>>> loop = new_loop("Send the signed draft", remind_at=now + timedelta(hours=3), now=now, id="loop-a")
>>> loop.state, loop.list
('submitted', 'next')
>>> [a["action"] for a in evaluate([loop], now)]
['arm']
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "STATES",
    "TERMINAL",
    "LISTS",
    "DFLT_HORIZON",
    "MIN_SCHEDULE_LEAD",
    "Loop",
    "new_loop",
    "evaluate",
    "complete",
    "snooze",
    "cancel",
    "mark",
    "to_utc",
    "iso",
]

#: The lifecycle, in A2A's names (the same as equerry's desk Item).
STATES = (
    "submitted",
    "working",
    "input-required",
    "completed",
    "failed",
    "canceled",
    "rejected",
)
#: Nothing leaves these.
TERMINAL = frozenset({"completed", "failed", "canceled", "rejected"})
#: The GTD lists a loop can sit on.
LISTS = ("in", "next", "waiting", "someday", "reference")
#: How far ahead a reminder is handed to the delivery channel's own scheduler. ntfy
#: holds a scheduled message for at most three days.
DFLT_HORIZON = timedelta(hours=72)
#: Below this lead a scheduled delivery is refused by ntfy (10 s), so it is sent now.
MIN_SCHEDULE_LEAD = timedelta(seconds=15)


def to_utc(when: datetime | str) -> datetime:
    """A timezone-aware UTC datetime; a naive one is read as the machine's local time.

    >>> to_utc("2026-11-19T12:00:00Z").isoformat()
    '2026-11-19T12:00:00+00:00'
    """
    if isinstance(when, str):
        when = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.astimezone()
    return when.astimezone(timezone.utc)


def iso(when: datetime | None) -> str | None:
    """UTC ISO with a ``Z``, to the second.

    >>> iso(datetime(2026, 11, 19, 12, 0, 30, 999, tzinfo=timezone.utc))
    '2026-11-19T12:00:30Z'
    """
    if when is None:
        return None
    return to_utc(when).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Loop:
    """One commitment. Most fields are optional; GTD-complete, v1 uses a few.

    ``source`` is where it came from (``{kind, ref, quote, said_by}``): every loop an
    agent makes is traceable. ``proposed_by`` is set when an agent proposed it and the
    person has not accepted it; a proposal never pushes. ``reveal`` says whether a push
    may carry the title (pushes cross a public relay by default). ``armed`` records the
    delivery the channel holds (``{sequence_id, at}``), so it can be replaced or
    cancelled. ``log`` is append-only.
    """

    id: str
    title: str
    created: str
    state: str = "submitted"
    list: str = "next"
    remind_at: str | None = None
    due: str | None = None
    reveal: bool = False
    source: Mapping[str, Any] | None = None
    proposed_by: str | None = None
    project: str | None = None
    area: str | None = None
    contexts: tuple[str, ...] = ()
    energy: str | None = None
    minutes: int | None = None
    waiting: Mapping[str, Any] | None = None
    available_when: Mapping[str, Any] | None = None
    done_when: Mapping[str, Any] | None = None
    snoozes: int = 0
    carried: int = 0
    armed: Mapping[str, Any] | None = None
    log: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError(f"unknown state {self.state!r}; expected one of {STATES}")
        if self.list not in LISTS:
            raise ValueError(f"unknown list {self.list!r}; expected one of {LISTS}")
        if not self.title.strip():
            raise ValueError("a loop needs a title")
        object.__setattr__(self, "contexts", tuple(self.contexts))
        object.__setattr__(self, "log", tuple(self.log))

    @property
    def open(self) -> bool:
        return self.state not in TERMINAL

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["contexts"] = list(self.contexts)
        d["log"] = [dict(e) for e in self.log]
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Loop:
        """Read a stored loop; keys this version does not know are ignored, not fatal."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _event(now: datetime, event: str, by: str, **extra: Any) -> dict[str, Any]:
    return {"at": iso(now), "event": event, "by": by, **extra}


def new_loop(
    title: str,
    *,
    remind_at: datetime | str | None = None,
    due: datetime | str | None = None,
    reveal: bool = False,
    source: Mapping[str, Any] | None = None,
    by: str = "owner",
    now: datetime | None = None,
    id: str | None = None,
    **extra: Any,
) -> Loop:
    """A new loop, logged as created. ``extra`` takes any other :class:`Loop` field.

    A loop the owner asked for goes on ``next``; ``list`` in ``extra`` overrides it.
    """
    now = to_utc(now or datetime.now(timezone.utc))
    loop_id = id or f"loop-{now:%Y%m%d}-{secrets.token_hex(3)}"
    extra.setdefault("list", "next")
    return Loop(
        id=loop_id,
        title=" ".join(title.split()),
        created=iso(now),
        remind_at=iso(to_utc(remind_at)) if remind_at else None,
        due=iso(to_utc(due)) if due else None,
        reveal=reveal,
        source=dict(source) if source else None,
        log=(_event(now, "created", by),),
        **extra,
    )


def mark(
    loop: Loop, now: datetime, event: str, *, by: str = "tick", **changes: Any
) -> Loop:
    """A copy with ``changes`` applied and one log entry appended."""
    note = changes.pop("note", None)
    entry = _event(to_utc(now), event, by, **({"note": note} if note else {}))
    return replace(loop, log=(*loop.log, entry), **changes)


def complete(
    loop: Loop, now: datetime, *, by: str = "owner", note: str | None = None
) -> Loop:
    """Done. Refused on a loop already closed, so a second ``done`` is visible, not silent."""
    if not loop.open:
        raise ValueError(f"{loop.id} is already {loop.state}")
    return mark(loop, now, "completed", by=by, state="completed", note=note)


def cancel(
    loop: Loop, now: datetime, *, by: str = "owner", note: str | None = None
) -> Loop:
    """Withdrawn: it will not fire. A reason belongs in ``note``."""
    if not loop.open:
        raise ValueError(f"{loop.id} is already {loop.state}")
    return mark(loop, now, "canceled", by=by, state="canceled", note=note)


def snooze(
    loop: Loop, until: datetime | str, now: datetime, *, by: str = "owner"
) -> Loop:
    """Bring it back at ``until``: scheduled again, one more snooze counted."""
    if not loop.open:
        raise ValueError(f"{loop.id} is already {loop.state}")
    until_utc = to_utc(until)
    if until_utc <= to_utc(now):
        raise ValueError("a snooze must end in the future")
    return mark(
        loop,
        now,
        "snoozed",
        by=by,
        state="submitted",
        remind_at=iso(until_utc),
        snoozes=loop.snoozes + 1,
        note=f"until {iso(until_utc)}",
    )


def evaluate(
    loops: Iterable[Loop],
    now: datetime,
    *,
    horizon: timedelta = DFLT_HORIZON,
) -> list[dict[str, Any]]:
    """What a runner should do now, as data. Pure: same loops and ``now``, same actions.

    For each open, accepted loop with a ``remind_at``:

    - ``arm``: due within ``horizon`` and not yet handed to the channel at that time.
      The channel delivers it at ``remind_at`` even if this machine is asleep then.
    - ``deliver``: due and never armed (created late, or arming failed, or the machine
      slept past the horizon). Sent now, saying how late.
    - ``woke``: due and armed, so the channel has delivered it; the loop now needs its
      owner (``input-required``).
    - ``disarm``: closed but still armed: cancel the channel's copy.

    Proposals (``proposed_by`` set) never produce a delivery.

    >>> now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    >>> far = new_loop("x", remind_at=now + timedelta(days=5), now=now, id="far")
    >>> late = new_loop("y", remind_at=now - timedelta(minutes=5), now=now, id="late")
    >>> [(a["action"], a["id"]) for a in evaluate([far, late], now)]
    [('deliver', 'late')]
    """
    now = to_utc(now)
    actions: list[dict[str, Any]] = []
    for loop in loops:
        armed_at = (loop.armed or {}).get("at")
        if not loop.open:
            if loop.armed:
                actions.append({"action": "disarm", "id": loop.id})
            continue
        if loop.proposed_by or not loop.remind_at or loop.state != "submitted":
            continue
        when = to_utc(loop.remind_at)
        if when <= now:
            if armed_at == loop.remind_at:
                actions.append({"action": "woke", "id": loop.id})
            else:
                late = int((now - when).total_seconds() // 60)
                actions.append(
                    {"action": "deliver", "id": loop.id, "late_minutes": late}
                )
        elif when - now <= horizon and armed_at != loop.remind_at:
            actions.append({"action": "arm", "id": loop.id, "at": loop.remind_at})
    return actions
