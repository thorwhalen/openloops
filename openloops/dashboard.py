"""One page you can look at instead of reading three command outputs.

:func:`render_dashboard` takes what :func:`openloops.owed`, :func:`openloops.blocked`
and :func:`openloops.ls` returned and renders a single self-contained HTML document —
no stylesheet, no script, no font and no request to anywhere. That is not decoration:
the page is meant to be published, and a published page runs no ``gh``, shells out to
nothing and reaches no network.

So **the page is a snapshot, and it says so in its largest type.** This module inverts
the one rule :mod:`openloops.digest` holds to — a digest deliberately stamps no
generation time so that regenerating it is byte-stable — because here the generation
time is the whole claim. ``made_at`` is a required-in-practice argument rather than a
hidden ``now()``, which is also what lets a test compare bytes.

The four registers are ordered the way a person needs them, and the fourth is the one
the package exists for:

1. **Needs you now** — obligations still open, each printing the predicate that decided
   it, unabbreviated, so a reader can disagree with the verdict rather than absorb it.
2. **Free to proceed** — blocker edges that have all closed, led by how many days the
   work has been free while nothing anywhere said so.
3. **In flight** — what the sessions left open, newest last turn first.
4. **Unknown** — every ``?``, with why. It carries the envelope-level failures too: an
   ``owed`` that could not list is not "nothing owed", and rendering it as ``0`` would
   make this page worse than no page. When the count really is zero the section says
   which checks earned that, because a clean board with no provenance is the same lie
   told quietly.

Everything printed goes through :class:`_Sanitizer`, which is :func:`openloops.egress
.scrub` plus HTML escaping plus a scheme allowlist on every link. A page that carries a
repository name and an issue title is fine; one that carries a home path or a token is
the failure ``openloops.egress`` exists to prevent, and this renderer scrubs its input
rather than trusting it. A credential-shaped field is *withheld and counted*, never
silently dropped — the count is printed in the footer.

    >>> html = render_dashboard({}, {}, [], made_at='2026-01-01T00:00:00Z')
    >>> '<title>' in html and 'snapshot' in html
    True
"""

from __future__ import annotations

import html as _html
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from openloops.base import OPEN
from openloops.blockers import BLOCKED, UNBLOCKED
from openloops.egress import CredentialFound, scrub
from openloops.obligations import DISCHARGED, UNKNOWN

__all__ = [
    "DFLT_MAX_SESSIONS",
    "DFLT_TITLE",
    "GAUGE_FULL_DAYS",
    "headline_counts",
    "render_dashboard",
    "unchecked_count",
    "unknown_count",
]

#: What the page is called — in the tab, in a gallery, and in its own masthead.
DFLT_TITLE = "Open Loops Board"

#: How many session rows are printed. The register states the true total either way; a
#: page that showed all 150-odd would bury the two registers above it.
DFLT_MAX_SESSIONS = 40

#: How many low-confidence sessions the unknown register names one by one before it
#: switches to counting them. Every one of them is still counted.
MAX_NAMED_SESSIONS = 8

#: Where the age gauge tops out. Ninety days is the point past which the length of the
#: bar stops being informative and the number beside it is doing all the work.
GAUGE_FULL_DAYS = 90

#: How much of a predicate's output is printed. The predicate itself is never clipped —
#: it is the reason to believe the verdict — but its output can be a pytest run.
MAX_EVIDENCE = 260

#: Only these schemes become links. Every URL on this page comes out of a GitHub API
#: payload, and a payload is input.
_LINK_SCHEMES = ("https://", "http://")

_SECONDS_PER_DAY = 86400.0


# --------------------------------------------------------------------------------
# The egress choke point. Nothing reaches the page except through here.
# --------------------------------------------------------------------------------


class _Sanitizer:
    """Scrub, then escape. The single path from an envelope to the document.

    Two failures are possible and they are treated differently, exactly as
    :mod:`openloops.egress` prescribes. A home path is *rewritten* — it is an identifier
    and the tail is the part a reader needs. A credential is *withheld and counted*: the
    field is replaced by a visible notice naming the pattern class, never the text, and
    :attr:`withheld` is printed in the footer so the run reports it rather than quietly
    losing a field.

    >>> s = _Sanitizer()
    >>> s.text('a < b')
    'a &lt; b'
    >>> s.text('token=' + 'ghp_' + 'A' * 36)
    '[withheld: credential-shaped text (github_token)]'
    >>> s.withheld
    ['github_token']
    """

    def __init__(self, aliases: Mapping[str, str] | None = None):
        self.aliases = aliases
        self.withheld: list[str] = []

    def text(self, value: Any) -> str:
        """One field, safe to place in the document."""
        try:
            clean = scrub("" if value is None else str(value), aliases=self.aliases)
        except CredentialFound as found:
            self.withheld.append(found.pattern_name)
            return f"[withheld: credential-shaped text ({found.pattern_name})]"
        return _html.escape(clean, quote=True)

    def url(self, value: Any) -> str:
        """A link target, or ``''`` when it is not one this page will follow."""
        raw = "" if value is None else str(value).strip()
        if not raw.lower().startswith(_LINK_SCHEMES):
            return ""
        return self.text(raw)


# --------------------------------------------------------------------------------
# Small readings of the data. None of them guess; all of them can answer "?".
# --------------------------------------------------------------------------------


def _moment(value: Any) -> datetime | None:
    """An ISO timestamp as a UTC datetime, or ``None`` when it will not parse.

    Claude Code writes a trailing ``Z`` that ``fromisoformat`` refused until 3.11, and
    every date on this page comes from a payload rather than from us.

    >>> _moment('2026-01-01T00:00:00Z').year
    2026
    >>> _moment('sometime') is None
    True
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _days_between(then: Any, now: datetime | None) -> int | None:
    """Whole days from *then* to *now*, or ``None`` when either cannot be read.

    >>> _days_between('2026-01-01T00:00:00Z', _moment('2026-01-04T06:00:00Z'))
    3
    """
    start = _moment(then)
    if start is None or now is None:
        return None
    return max(0, int((now - start).total_seconds() // _SECONDS_PER_DAY))


def _figure(value: Any) -> str:
    """How a count prints. ``None`` is ``?`` and is never rounded to a number."""
    return "?" if value is None else str(value)


def _plural(count: int, noun: str, plural: str = "") -> str:
    """``3 issues`` / ``1 issue``. A count that reads ``1 issues`` reads as generated.

    >>> _plural(1, 'issue'), _plural(2, 'issue')
    ('1 issue', '2 issues')
    """
    return f"{count} {noun if count == 1 else (plural or noun + 's')}"


def _clip(text: str, limit: int = MAX_EVIDENCE) -> str:
    """Bound a field, saying so when it bites — the idiom :mod:`openloops.digest` uses.

    >>> _clip('abcdef', 3)
    'abc … clipped at 3 characters'
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()} … clipped at {limit} characters"


def _counts(envelope: Mapping[str, Any], key: str) -> int | None:
    """One count from an envelope, or ``None`` when the envelope never got to read.

    ``listed: False`` means the counts are zeros that mean nothing — ADR-013's rule, and
    the single most important line in this module.

    >>> _counts({'listed': False, 'counts': {'open': 0}}, 'open') is None
    True
    >>> _counts({'listed': True, 'counts': {'open': 4}}, 'open')
    4
    """
    if not envelope.get("listed", False):
        return None
    return int(envelope.get("counts", {}).get(key, 0))


def _rows(envelope: Mapping[str, Any], *states: str) -> list[dict[str, Any]]:
    """The rows of an envelope in the given states, in the order the envelope sorted."""
    if not envelope.get("listed", False):
        return []
    return [row for row in envelope.get("rows", []) if row.get("state") in states]


# --------------------------------------------------------------------------------
# Fragments. Each returns a string; none of them touch the outside world.
# --------------------------------------------------------------------------------


def _gauge(days: int | None, tone: str) -> str:
    """A hairline bar whose length is how long this has been sitting.

    The number beside it is the fact; the bar is what makes a register scannable, which
    is the difference between a page you read and a page you glance at.
    """
    if days is None:
        return '<p class="gauge gauge--unsure"><span style="width:100%"></span></p>'
    width = min(100, round(100 * days / GAUGE_FULL_DAYS))
    return f'<p class="gauge gauge--{tone}"><span style="width:{max(2, width)}%"></span></p>'


def _rail(chip: str, tone: str, days: int | None, unit: str = "d") -> str:
    """The fixed left column of every row: what state it is in, and for how long."""
    figure = "?" if days is None else str(days)
    return (
        f'<div class="rail">'
        f'<span class="chip chip--{tone}">{chip}</span>'
        f'<span class="age"><b>{figure}</b><i>{unit}</i></span>'
        f"</div>"
    )


def _ref(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """``owner/name#number``, linked when the payload gave a URL this page will follow."""
    ref = f"{safe.text(row.get('repo'))}#{safe.text(row.get('number'))}"
    url = safe.url(row.get("url"))
    return (
        f'<a class="ref" href="{url}">{ref}</a>'
        if url
        else f'<span class="ref">{ref}</span>'
    )


def _obligation_row(
    safe: _Sanitizer, row: Mapping[str, Any], *, tone: str, chip: str
) -> str:
    days = row.get("age_days")
    days = int(days) if isinstance(days, (int, float)) else None
    predicate = safe.text(row.get("predicate")) or "(none — nothing to re-check)"
    evidence = safe.text(_clip(str(row.get("evidence") or "")))
    lines = [
        f'<li class="row row--{tone}">',
        _rail(chip, tone, days),
        '<div class="body">',
        f'<p class="ask">{safe.text(row.get("title"))}</p>',
        f'<p class="where">{_ref(safe, row)} <span class="sep">·</span> opened '
        f"{safe.text(str(row.get('created') or '')[:10]) or '?'}</p>",
        # Never abbreviated. It is the reason to believe the verdict, and a predicate
        # you cannot read is a verdict you cannot disagree with.
        f'<p class="line"><span class="tag">verify</span><code>{predicate}</code></p>',
    ]
    if evidence:
        lines.append(
            f'<p class="line"><span class="tag">said</span><code>{evidence}</code></p>'
        )
    lines += ["</div>", _gauge(days, tone), "</li>"]
    return "".join(lines)


def _unblocked_row(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    free = row.get("unblocked_days")
    free = int(free) if isinstance(free, (int, float)) else None
    refs = " ".join(safe.text(b.get("ref")) for b in row.get("blockers", ()))
    age = row.get("age_days")
    age = int(age) if isinstance(age, (int, float)) else None
    return "".join(
        [
            '<li class="row row--free">',
            _rail("free", "free", free),
            '<div class="body">',
            f'<p class="ask">{safe.text(row.get("title"))}</p>',
            f'<p class="where">{_ref(safe, row)} <span class="sep">·</span> open '
            f"{_figure(age)}d</p>",
            # The number nobody currently has, and the reason this register leads.
            f'<p class="verdict">Free to proceed for {_figure(free)} days, and nothing '
            "anywhere has said so.</p>",
            f'<p class="line"><span class="tag">was on</span><code>{refs or "(unresolved)"}'
            "</code></p>",
            "</div>",
            _gauge(free, "free"),
            "</li>",
        ]
    )


def _waiting_row(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """A still-blocked edge, one dense line. The foreign repo is the whole content."""
    open_refs = [
        safe.text(b.get("ref"))
        for b in row.get("blockers", ())
        if b.get("state") != "closed"
    ]
    days = row.get("age_days")
    days = int(days) if isinstance(days, (int, float)) else None
    return "".join(
        [
            '<li class="thin">',
            f'<span class="thin-age">{_figure(days)}d</span>',
            # Ref and title share one flowing line rather than two fixed columns: a
            # `owner/name#number` is as long as the repository is, and a column sized
            # for the short ones silently overlaps the title on the long ones.
            f'<p class="thin-ask">{_ref(safe, row)} <span class="sep">·</span> '
            f"{safe.text(row.get('title'))}</p>",
            f'<code class="thin-on">{" ".join(open_refs) or "(unresolved)"}</code>',
            "</li>",
        ]
    )


def _session_row(safe: _Sanitizer, row: Mapping[str, Any], now: datetime | None) -> str:
    days = _days_between(row.get("last_turn"), now)
    low = (row.get("confidence") or "high") != "high"
    tone = "unsure" if low else "flight"
    heading = (
        row.get("ai_title") or row.get("title") or row.get("project") or "(untitled)"
    )
    where = [
        row.get("project"),
        row.get("branches"),
        f"{row.get('turns') or '?'} turns",
    ]
    session = str(row.get("session") or "")
    return "".join(
        [
            f'<li class="row row--{tone}">',
            _rail("open" if not low else "open ?", tone, days),
            '<div class="body">',
            f'<p class="ask">{safe.text(heading)}</p>',
            '<p class="where">'
            + f' <span class="sep">·</span> '.join(
                safe.text(part) for part in where if part
            )
            + "</p>",
            f'<p class="line"><span class="tag">read it</span><code>ol show '
            f"{safe.text(session[:8])}</code></p>",
            (
                '<p class="caveat">Open only because nothing in it said otherwise — the '
                "classifier did not read a closing line.</p>"
                if low
                else ""
            ),
            "</div>",
            _gauge(days, tone),
            "</li>",
        ]
    )


def _register(
    *, ident: str, name: str, figure: str, tone: str, rule: str, body: str
) -> str:
    """One band: a heading, the count in the largest figure on the page, and its rule."""
    return (
        f'<section class="register register--{tone}" id="{ident}">'
        f'<div class="register-head">'
        f'<p class="figure">{figure}</p>'
        f'<div><h2>{name}</h2><p class="rule">{rule}</p></div>'
        f"</div>{body}</section>"
    )


def _empty(message: str) -> str:
    return f'<p class="empty">{message}</p>'


# --------------------------------------------------------------------------------
# The unknown register: assembled first, because the masthead reports its size.
# --------------------------------------------------------------------------------


def _unknowns(
    safe: _Sanitizer,
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Everything on this page that reads ``?``, each with why it does.

    Ordered by how badly it damages the page above it: an envelope that never listed
    invalidates a whole register, a caveat merely bounds one.
    """
    items: list[dict[str, Any]] = []

    for envelope, name, headline, note in (
        (
            owed,
            "ol owed",
            "The obligation listing itself failed",
            "Every obligation count on this page is ? — not zero.",
        ),
        (
            blocked,
            "ol blocked",
            "Cross-repo discovery itself failed",
            "Every cross-repo count on this page is ? — not zero.",
        ),
    ):
        if not envelope.get("listed", False):
            items.append(
                {
                    "kind": name,
                    "title": headline,
                    "why": safe.text(envelope.get("error") or "no reason was reported"),
                    "note": note,
                    "weight": 0,
                }
            )

    if owed.get("listed") and not owed.get("checked", True):
        items.append(
            {
                "kind": "ol owed",
                "title": "Predicates were not evaluated",
                "why": "Run with verification off, so every row carrying a predicate reads ?.",
                "note": "",
                # Those rows already read `unknown` and are already counted below;
                # weighting this line too would count each of them twice.
                "weight": 0,
            }
        )
    if blocked.get("listed") and not blocked.get("resolved", True):
        items.append(
            {
                "kind": "ol blocked",
                "title": "Blocker edges were not resolved",
                "why": "Run with resolution off, so every row reads ?.",
                "note": "",
                "weight": 0,
            }
        )

    for envelope, name, what in (
        (owed, "ol owed", "result set"),
        (blocked, "ol blocked", "candidate list"),
    ):
        if envelope.get("listed") and envelope.get("truncated"):
            items.append(
                {
                    "kind": name,
                    "title": f"The {what} hit its cap",
                    "why": "There is more than this page shows; the counts are a floor.",
                    "note": "",
                    "weight": 0,
                }
            )

    for row in _rows(owed, UNKNOWN):
        items.append(
            {
                "kind": "obligation",
                "title": safe.text(row.get("title")),
                "why": safe.text(
                    _clip(str(row.get("evidence") or "nothing could be checked"))
                ),
                "note": _ref(safe, row),
                "weight": 1,
            }
        )
    for row in _rows(blocked, UNKNOWN):
        items.append(
            {
                "kind": "cross-repo",
                "title": safe.text(row.get("title")),
                "why": safe.text(
                    _clip(str(row.get("evidence") or "the edges could not be read"))
                ),
                "note": _ref(safe, row),
                "weight": 1,
            }
        )

    if not sessions:
        # `ls` is the one of the three that returns a bare list rather than an envelope,
        # so an empty store cannot be told apart from a store nothing has written to.
        items.append(
            {
                "kind": "ol ls",
                "title": "No digests in the store",
                "why": "Either nothing is open or `ol sync` has never run on this machine. "
                "A list, unlike an envelope, cannot tell the two apart.",
                "note": "",
                "weight": 1,
            }
        )

    low = [row for row in sessions if (row.get("confidence") or "high") != "high"]
    if low:
        named = ", ".join(
            safe.text(row.get("ai_title") or row.get("title") or row.get("session"))
            for row in low[:MAX_NAMED_SESSIONS]
        )
        more = (
            f", and {len(low) - MAX_NAMED_SESSIONS} more"
            if len(low) > MAX_NAMED_SESSIONS
            else ""
        )
        items.append(
            {
                "kind": "ol ls",
                "title": f"{len(low)} of {len(sessions)} open sessions are open by default",
                "why": "Nothing in the closing turn said the work was finished, so the "
                "classifier left them open rather than claiming either way.",
                "note": f"{named}{more}",
                # Not 1. This one item stands for forty rows, and a headline that
                # counted list entries instead of `?` rows would report `1` for them --
                # tidier, smaller, and exactly the failure this register exists to name.
                "weight": len(low),
            }
        )
    return items


def unknown_count(
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
) -> int | None:
    """How many things read ``?``, or ``None`` when even that cannot be counted.

    A register that never listed could be hiding any number of unknown rows, so the
    headline figure for unknowns is itself unknown. Reporting ``2`` there — the two
    failures we happen to know about — is the exact shape of the lie this page is
    against, and it is a lie a reader has no way to spot.

    It counts the rows that read ``?``, not the entries in the list below: one entry
    can stand for forty sessions, and reporting ``1`` for those would be the tidier
    number rather than the true one.

    >>> unknown_count({'listed': True, 'rows': []}, {'listed': True, 'rows': []}, [{}])
    0
    >>> lows = [{'confidence': 'low'}] * 5
    >>> unknown_count({'listed': True, 'rows': []}, {'listed': True, 'rows': []}, lows)
    5
    >>> unknown_count({'listed': False}, {'listed': True, 'rows': []}, [{}]) is None
    True
    """
    if not owed.get("listed", False) or not blocked.get("listed", False):
        return None
    items = _unknowns(_Sanitizer(), dict(owed), dict(blocked), list(sessions))
    return sum(int(item.get("weight", 1)) for item in items)


def unchecked_count(
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
) -> int | None:
    """How many OBLIGATIONS could not be checked against the world. ``None`` if unknowable.

    Deliberately narrower than :func:`unknown_count`, and the two must not be merged in
    the masthead. A `?` on an obligation means *the world could not be reached* — a
    timeout, a missing ``gh``, an untrusted owner. A low-confidence session digest means
    something else entirely: the digest half checks nothing against the world by design,
    so it has nothing it was unable to check. Rolling forty of the second into the first
    reports a crisis of forty when the real number is one, and in the alarming direction.

    >>> unchecked_count({'listed': True, 'rows': [{'state': 'unknown'}]},
    ...                 {'listed': True, 'rows': []})
    1
    >>> unchecked_count({'listed': False}, {'listed': True, 'rows': []}) is None
    True
    """
    if not owed.get("listed", False) or not blocked.get("listed", False):
        return None
    return sum(
        1
        for envelope in (owed, blocked)
        for row in envelope.get("rows", [])
        if row.get("state") == "unknown"
    )


def headline_counts(
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, int | None]:
    """The four figures across the top of the page. ``None`` is ``?``, never a zero.

    Shared by the masthead and by :func:`openloops.tools.dashboard`, so the number a
    caller reads back is the number the page printed.

    >>> headline_counts({'listed': True, 'counts': {'open': 2}, 'rows': []},
    ...                 {'listed': False}, [])['free_to_proceed'] is None
    True
    """
    return {
        "needs_you": _counts(owed, OPEN),
        "free_to_proceed": _counts(blocked, UNBLOCKED),
        "in_flight": len(sessions),
        # Two figures, not one. `unchecked` is the alarming number -- obligations the
        # world would not answer for. `low_confidence` is the calm one: sessions the
        # classifier left open because nothing said otherwise, which is its documented
        # default and not a failure to check anything. Merging them reported 42 on a
        # fleet whose real unchecked count was 1.
        "unchecked": unchecked_count(owed, blocked),
        "low_confidence": _low_confidence_count(sessions),
        "unknown": unknown_count(owed, blocked, sessions),
    }


def _low_confidence_count(sessions: Sequence[Mapping[str, Any]]) -> int:
    """Sessions open only because nothing in them said they were finished."""
    return sum(1 for row in sessions if str(row.get("confidence", "")).lower() == "low")


def _earned(owed: Mapping[str, Any], blocked: Mapping[str, Any], sessions) -> list[str]:
    """What was actually checked. Printed when nothing reads ``?``.

    A clean board with no provenance is the same false claim as a hidden ``?``, told
    more quietly — so an empty unknown register has to show what earned it.
    """
    lines = []
    if owed.get("listed") and owed.get("checked", True):
        counts = owed.get("counts", {})
        lines.append(
            "`ol owed` read "
            + _plural(counts.get("total", 0), "obligation")
            + " and ran "
            + _plural(counts.get("with_predicate", 0), "predicate")
            + "."
        )
    if blocked.get("listed") and blocked.get("resolved", True):
        counts = blocked.get("counts", {})
        lines.append(
            "`ol blocked` resolved every edge on "
            + _plural(counts.get("total", 0), "issue")
            + " from "
            + _plural(counts.get("candidates", 0), "candidate")
            + "."
        )
    if sessions:
        lines.append(
            "`ol ls` read "
            + _plural(len(sessions), "open digest")
            + ", all with a stated reason."
        )
    return lines


# --------------------------------------------------------------------------------
# The document.
# --------------------------------------------------------------------------------


def render_dashboard(
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
    *,
    made_at: Any = None,
    source: str = "",  # "" omits it; a hostname on a published page is a needless leak
    title: str = DFLT_TITLE,
    max_sessions: int = DFLT_MAX_SESSIONS,
    standalone: bool = True,
    aliases: Mapping[str, str] | None = None,
) -> str:
    """The three envelopes as one self-contained HTML page. No network, no script.

    ``owed`` and ``blocked`` are the envelopes :func:`openloops.owed` and
    :func:`openloops.blocked` return; ``sessions`` is the list :func:`openloops.ls`
    returns. All three may be empty mappings, and an envelope whose ``listed`` is
    ``False`` renders as ``?`` throughout rather than as zero.

    ``made_at`` is the moment the snapshot was taken and is printed in the largest type
    on the page. It defaults to now, but a caller that wants a byte-stable page passes
    it — this is the one module in openloops that stamps a generation time, and it does
    so because the whole claim of the page is *when*.

    ``standalone`` wraps the output in a document scaffold for a file you open yourself.
    Pass ``False`` for a host that supplies its own ``<head>`` — a published artifact
    does — and the same page comes back as title, styles and content only.

    ``max_sessions`` bounds the in-flight register; the true total is stated either way.

    >>> page = render_dashboard(
    ...     {'listed': False, 'error': 'gh: not logged in', 'counts': {}},
    ...     {'listed': True, 'counts': {'unblocked': 0, 'total': 0}, 'rows': []},
    ...     [], made_at='2026-01-01T00:00:00Z')
    >>> 'gh: not logged in' in page and 'could not' in page
    True
    """
    safe = _Sanitizer(aliases)
    owed = dict(owed or {})
    blocked = dict(blocked or {})
    sessions = list(sessions or [])
    now = _moment(made_at) if made_at is not None else datetime.now(timezone.utc)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")

    unknowns = _unknowns(safe, owed, blocked, sessions)
    counts = headline_counts(owed, blocked, sessions)

    parts = [
        _masthead(
            safe,
            owed,
            blocked,
            sessions,
            title=title,
            stamp=stamp,
            source=source,
            counts=counts,
        ),
        _needs_register(safe, owed),
        _free_register(safe, blocked),
        _flight_register(safe, sessions, now, max_sessions=max_sessions),
        _unknown_register(safe, unknowns, counts["unknown"], owed, blocked, sessions),
        _footer(safe, stamp),
    ]
    head = (
        f"<title>{safe.text(title)}</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{_CSS}</style>"
    )
    body = f'<main class="sheet">{"".join(parts)}</main>'
    if not standalone:
        return head + body
    return (
        '<!doctype html>\n<html lang="en">\n'
        f'<head>\n<meta charset="utf-8">\n{head}\n</head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _masthead(
    safe: _Sanitizer,
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
    *,
    title: str,
    stamp: str,
    source: str,
    counts: Mapping[str, int | None],
) -> str:
    tally = [
        ("Needs you", _figure(counts["needs_you"]), "needs"),
        ("Free to proceed", _figure(counts["free_to_proceed"]), "free"),
        ("In flight", _figure(counts["in_flight"]), "flight"),
        # The narrow figure, on purpose. See `unchecked_count`: this counts obligations
        # the world would not answer for, and NOT sessions the classifier left open by
        # default -- those are named in the register below, where the distinction can be
        # explained rather than collapsed into one alarming number.
        ("Couldn't check", _figure(counts["unchecked"]), "unsure"),
    ]
    cells = "".join(
        f'<div class="tally-cell tally--{tone}"><p class="tally-figure">{figure}</p>'
        f'<p class="tally-name">{name}</p></div>'
        for name, figure, tone in tally
    )
    scope = ", ".join(safe.text(o) for o in owed.get("owners", ())) or "(none resolved)"
    blocked_scope = (
        ", ".join(
            safe.text(x) for x in (blocked.get("repos") or blocked.get("owners") or ())
        )
        or "(none resolved)"
    )
    bcounts = blocked.get("counts", {})
    ocounts = owed.get("counts", {})
    if not owed.get("listed", False):
        owed_detail = safe.text(owed.get("error") or "no reason was reported")
    elif not owed.get("checked", True):
        owed_detail = (
            "listed but NOT evaluated — every row carrying a predicate reads ?"
        )
    else:
        owed_detail = (
            f"{ocounts.get('with_predicate', 0)} of {ocounts.get('total', 0)} rows carried a "
            "predicate, and every one of them was re-run"
        )
    if not blocked.get("listed", False):
        blocked_detail = safe.text(blocked.get("error") or "no reason was reported")
    elif not blocked.get("resolved", True):
        blocked_detail = "listed but NOT resolved — every row reads ?"
    else:
        blocked_detail = (
            _plural(bcounts.get("candidates", 0), "candidate")
            + f", {bcounts.get('without_edges', 0)} of which carried no dependency edge at all"
        )
    instruments = [
        (
            "ol owed",
            "read" if owed.get("listed") else "could not read",
            bool(owed.get("listed")),
            owed_detail,
            f"owners: {scope}",
        ),
        (
            "ol blocked",
            "read" if blocked.get("listed") else "could not read",
            bool(blocked.get("listed")),
            blocked_detail,
            f"scope: {blocked_scope}",
        ),
        (
            "ol ls",
            "read",
            True,
            f"{_plural(len(sessions), 'open digest')}, from a local store rather than from GitHub",
            f"source: {safe.text(source) or 'this machine'}",
        ),
    ]
    rows = "".join(
        f'<li class="instrument{"" if ok else " instrument--bad"}">'
        f"<code>{name}</code><b>{state}</b>"
        f"<span>{detail}</span><em>{note}</em></li>"
        for name, state, ok, detail, note in instruments
    )
    return (
        '<header class="masthead">'
        '<p class="eyebrow">openloops <span class="sep">·</span> snapshot, not a status page</p>'
        f"<h1>{safe.text(title)}</h1>"
        f'<p class="stamp">as of <time>{safe.text(stamp)}</time></p>'
        '<p class="claim">Everything below is what three commands returned at that moment '
        "and nothing since. This page cannot check anything: it runs no commands and "
        "reaches nowhere. Treat every row as a lead to re-run, never as the state of the "
        "world right now.</p>"
        f'<div class="tally">{cells}</div>'
        f'<ul class="instruments">{rows}</ul>'
        "</header>"
    )


def _needs_register(safe: _Sanitizer, owed: Mapping[str, Any]) -> str:
    if not owed.get("listed", False):
        body = _cannot(safe, "ol owed", owed.get("error"), "nothing is owed")
        figure = "?"
    else:
        open_rows = _rows(owed, OPEN)
        done_rows = _rows(owed, DISCHARGED)
        figure = str(len(open_rows))
        body = (
            '<ol class="ledger">'
            + "".join(
                _obligation_row(safe, r, tone="needs", chip="open") for r in open_rows
            )
            + "</ol>"
            if open_rows
            else _empty(
                "No open obligation is waiting on you in the repositories that were read."
            )
        )
        if done_rows:
            done = "".join(
                _obligation_row(safe, row, tone="done", chip="done")
                for row in done_rows
            )
            body += (
                '<p class="subhead">Discharged — the predicate passes, so there is nothing '
                "to do but close the issue. openloops will not close it for you.</p>"
                f'<ol class="ledger ledger--quiet">{done}</ol>'
            )
    return _register(
        ident="needs",
        name="Needs you now",
        figure=figure,
        tone="needs",
        rule="Open <code>manual-task</code> issues your agents filed when they got blocked "
        "on you. Each one was re-checked by running the predicate printed under it — "
        "disagree with the verdict by reading the command, not by trusting the chip.",
        body=body,
    )


def _free_register(safe: _Sanitizer, blocked: Mapping[str, Any]) -> str:
    if not blocked.get("listed", False):
        body = _cannot(safe, "ol blocked", blocked.get("error"), "nothing is waiting")
        figure = "?"
    else:
        free_rows = _rows(blocked, UNBLOCKED)
        waiting = _rows(blocked, BLOCKED)
        figure = str(len(free_rows))
        body = (
            f'<ol class="ledger">{"".join(_unblocked_row(safe, r) for r in free_rows)}</ol>'
            if free_rows
            else _empty("Nothing has become free since it was last looked at.")
        )
        if waiting:
            rows = "".join(_waiting_row(safe, row) for row in waiting)
            body += (
                f'<p class="subhead">Still waiting — {_plural(len(waiting), "issue")}, each naming the '
                "foreign repository it is blocked on.</p>"
                f'<ul class="thins">{rows}</ul>'
            )
    return _register(
        ident="free",
        name="Free to proceed",
        figure=figure,
        tone="free",
        rule="Issues whose every <code>blocked_by</code> edge has closed. The days figure is "
        "how long the work has been free while nothing anywhere said so — that number is "
        "the reason this register exists.",
        body=body,
    )


def _flight_register(
    safe: _Sanitizer,
    sessions: Sequence[Mapping[str, Any]],
    now: datetime | None,
    *,
    max_sessions: int,
) -> str:
    shown = list(sessions)[: max(0, max_sessions)]
    tally = _project_tally(safe, sessions)
    if not sessions:
        body = _empty(
            "The digest store is empty. That is not the same as nothing being open — see "
            "the unknown register."
        )
    else:
        rows = "".join(_session_row(safe, row, now) for row in shown)
        body = tally + f'<ol class="ledger">{rows}</ol>'
        if len(shown) < len(sessions):
            body += _empty(
                f"Showing the {len(shown)} most recent of {len(sessions)}. "
                "Run <code>ol ls --limit 0</code> for all of them."
            )
    return _register(
        ident="flight",
        name="In flight",
        figure=str(len(sessions)),
        tone="flight",
        rule="What your sessions left open, newest last turn first. A digest says what a "
        "session <em>said</em>, dated — never what is true now, which is why none of these "
        "rows has been verified against anything.",
        body=body,
    )


def _project_tally(safe: _Sanitizer, sessions: Sequence[Mapping[str, Any]]) -> str:
    """Where the open sessions actually are. A hundred rows do not answer that; this does."""
    counts: dict[str, int] = {}
    for row in sessions:
        counts[str(row.get("project") or "(no project)")] = (
            counts.get(str(row.get("project") or "(no project)"), 0) + 1
        )
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if not ranked:
        return ""
    cells = "".join(
        f"<li><b>{count}</b><span>{safe.text(project)}</span></li>"
        for project, count in ranked
    )
    return f'<ul class="tallystrip">{cells}</ul>'


def _unknown_register(
    safe: _Sanitizer,
    unknowns: Sequence[Mapping[str, Any]],
    unknown_count: int | None,
    owed: Mapping[str, Any],
    blocked: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
) -> str:
    if unknowns:
        items = "".join(
            f'<li class="unsure-item"><p class="kind"><code>{item["kind"]}</code></p>'
            f'<div><p class="ask">{item["title"]}</p>'
            f'<p class="why">{item["why"]}</p>'
            + (f'<p class="note">{item["note"]}</p>' if item.get("note") else "")
            + "</div></li>"
            for item in unknowns
        )
        body = f'<ul class="unsures">{items}</ul>'
    else:
        earned = _earned(owed, blocked, sessions)
        proof = "".join(f"<li>{safe.text(line)}</li>" for line in earned)
        body = (
            '<p class="empty empty--earned">Nothing on this page reads <b>?</b>. '
            "That is a claim, so here is what earned it:</p>"
            f'<ul class="proof">{proof or "<li>Nothing was checked at all.</li>"}</ul>'
        )
    return _register(
        ident="unknown",
        name="Unknown",
        figure=_figure(unknown_count),
        tone="unsure",
        rule="Everything that could not be established, and why. A <b>?</b> is never rounded "
        "into a yes or a no, and it is never left off this page to make the board look "
        "tidier — a surface that reports a clean answer because it failed to check is "
        "worse than no surface.",
        body=body,
    )


def _cannot(safe: _Sanitizer, command: str, error: Any, mistaken_for: str) -> str:
    """What a register prints when its envelope never listed. Never a zero."""
    return (
        f'<div class="cannot"><p class="cannot-mark">?</p><div>'
        f'<p class="ask"><code>{safe.text(command)}</code> could not read the world, so '
        f"this register is unknown — not empty.</p>"
        f'<p class="why">{safe.text(error or "no reason was reported")}</p>'
        f'<p class="note">Do not read this as “{safe.text(mistaken_for)}”. '
        "The counts above are ? for the same reason.</p></div></div>"
    )


def _footer(safe: _Sanitizer, stamp: str) -> str:
    withheld = ""
    if safe.withheld:
        kinds = ", ".join(sorted(set(safe.withheld)))
        withheld = (
            f'<p class="withheld">{len(safe.withheld)} field(s) were withheld from this page '
            f"because they matched a credential pattern ({safe.text(kinds)}). The matched "
            "text is not printed anywhere, including here.</p>"
        )
    return (
        '<footer class="colophon">'
        f"<p>Rendered by <code>ol dashboard</code> at {safe.text(stamp)} from "
        "<code>ol owed</code>, <code>ol blocked</code> and <code>ol ls</code>. "
        "Re-run it to get a newer one; there is no other way for this page to change.</p>"
        "<p>openloops never writes to GitHub. Nothing here closed, reopened, relabelled or "
        "commented on anything — it read, and it reported.</p>"
        f"{withheld}"
        "</footer>"
    )


# --------------------------------------------------------------------------------
# The stylesheet. Inlined because a published page may load nothing from anywhere.
# --------------------------------------------------------------------------------

#: The dark palette, written once and injected into both blocks that can select it —
#: the `prefers-color-scheme` one for the un-stamped default and the `data-theme` one
#: for an explicit toggle. Two copies of a palette drift; one copy cannot.
_DARK_TOKENS = """
  --ground:#0e1211; --surface:#151b19; --sunk:#111615;
  --ink:#e4e8e3; --ink-soft:#94a29d; --rule:#29312e; --rule-soft:#1e2523;
  --accent:#74c6bc;
  --needs:#e0a44a; --needs-wash:#2c2317;
  --free:#74c282; --free-wash:#182619;
  --waits:#8b9994; --waits-wash:#1c2321;
  --unsure:#f17fa5; --unsure-wash:#2c161f;
  --done:#7f8f8a; --done-wash:#1a201e;
"""

_CSS = (
    """
:root{
  --ground:#eff0ec; --surface:#f8f9f5; --sunk:#e7e9e3;
  --ink:#151c1a; --ink-soft:#56635f; --rule:#d2d7d0; --rule-soft:#e3e6e0;
  --accent:#17514f;
  --needs:#94510a; --needs-wash:#f2e6d4;
  --free:#1e6b3c; --free-wash:#dfeade;
  --waits:#6c7975; --waits-wash:#e6e9e4;
  --unsure:#96234f; --unsure-wash:#f2dee4;
  --done:#69766f; --done-wash:#e8ebe6;
  --serif:ui-serif,Georgia,"Iowan Old Style","Palatino Linotype","Book Antiqua",serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --step:clamp(0.5rem,1.2vw,0.9rem);
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){"""
    + _DARK_TOKENS
    + """} }
:root[data-theme="dark"]{"""
    + _DARK_TOKENS
    + """}

*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--serif); font-size:17px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.sheet{max-width:64rem; margin:0 auto; padding:clamp(1.25rem,4vw,3.5rem) clamp(1rem,4vw,2.5rem) 4rem}
h1,h2{text-wrap:balance; margin:0; font-weight:600; letter-spacing:-0.012em}
p{margin:0}
a{color:var(--accent); text-underline-offset:0.18em; text-decoration-thickness:from-font}
a:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:1px}
code{font-family:var(--mono); font-size:0.82em}
b,strong{font-weight:600}
.sep{color:var(--rule); padding:0 0.15em}

/* ---- masthead: the timestamp is the thesis, so it gets the type ---- */
.masthead{display:grid; gap:1.1rem; padding-bottom:1.6rem; border-bottom:2px solid var(--ink)}
.eyebrow{
  font-family:var(--mono); font-size:0.7rem; letter-spacing:0.16em;
  text-transform:uppercase; color:var(--ink-soft);
}
.masthead h1{font-size:clamp(2rem,5.2vw,3.1rem); line-height:1.05}
.stamp{
  font-family:var(--mono); font-size:clamp(1.05rem,2.6vw,1.5rem);
  color:var(--accent); font-variant-numeric:tabular-nums; letter-spacing:-0.01em;
}
.stamp time{border-bottom:2px solid var(--accent); padding-bottom:0.08em}
.claim{max-width:38rem; color:var(--ink-soft); font-size:0.98rem}

.tally{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
  gap:1px; background:var(--rule); border:1px solid var(--rule); margin-top:0.4rem;
}
.tally-cell{background:var(--surface); padding:0.9rem 1rem 0.8rem}
.tally-figure{
  font-family:var(--mono); font-size:2.4rem; line-height:1;
  font-variant-numeric:tabular-nums; letter-spacing:-0.03em;
}
.tally-name{
  font-family:var(--mono); font-size:0.68rem; letter-spacing:0.13em;
  text-transform:uppercase; color:var(--ink-soft); margin-top:0.45rem;
}
.tally--needs .tally-figure{color:var(--needs)}
.tally--free .tally-figure{color:var(--free)}
.tally--flight .tally-figure{color:var(--ink)}
.tally--unsure .tally-figure{color:var(--unsure)}

.instruments{list-style:none; margin:0; padding:0; display:grid; gap:1px; background:var(--rule)}
.instrument{
  background:var(--surface); display:grid; gap:0.15rem 0.9rem; padding:0.55rem 1rem;
  grid-template-columns:7.5rem 5.5rem 1fr; align-items:baseline;
  font-size:0.83rem; color:var(--ink-soft);
}
.instrument code{color:var(--ink); font-size:0.78rem}
.instrument b{
  font-family:var(--mono); font-size:0.66rem; letter-spacing:0.12em;
  text-transform:uppercase; color:var(--free);
}
.instrument em{grid-column:3; font-style:normal; font-family:var(--mono); font-size:0.72rem; color:var(--ink-soft); opacity:0.8}
.instrument--bad b{color:var(--unsure)}
.instrument--bad{background:var(--unsure-wash)}

/* ---- registers ---- */
.register{margin-top:clamp(2.2rem,5vw,3.4rem)}
.register-head{
  display:grid; grid-template-columns:auto 1fr; gap:0 1.25rem; align-items:start;
  padding-bottom:0.85rem; border-bottom:1px solid var(--ink);
}
.figure{
  font-family:var(--mono); font-size:clamp(2.6rem,7vw,3.6rem); line-height:0.85;
  font-variant-numeric:tabular-nums; letter-spacing:-0.045em; min-width:2ch;
}
.register--needs .figure{color:var(--needs)}
.register--free .figure{color:var(--free)}
.register--flight .figure{color:var(--ink)}
.register--unsure .figure{color:var(--unsure)}
.register h2{font-size:clamp(1.35rem,3vw,1.75rem)}
.rule{color:var(--ink-soft); font-size:0.92rem; max-width:44rem; margin-top:0.3rem}
.subhead{
  font-family:var(--mono); font-size:0.72rem; letter-spacing:0.1em; text-transform:uppercase;
  color:var(--ink-soft); margin-top:2rem; padding-bottom:0.5rem; border-bottom:1px solid var(--rule);
}

/* ---- ledger rows: hairlines, not cards ---- */
.ledger{list-style:none; margin:0; padding:0}
.row{
  display:grid; grid-template-columns:5.75rem 1fr; gap:0 1.25rem;
  padding:1.15rem 0 0.85rem; border-bottom:1px solid var(--rule-soft); position:relative;
}
.ledger--quiet .row{opacity:0.72}
.rail{display:flex; flex-direction:column; gap:0.4rem; align-items:flex-start}
.chip{
  font-family:var(--mono); font-size:0.62rem; letter-spacing:0.1em; text-transform:uppercase;
  padding:0.2rem 0.42rem; border:1px solid currentColor; white-space:nowrap;
}
.chip--needs{color:var(--needs); background:var(--needs-wash)}
.chip--free{color:var(--free); background:var(--free-wash)}
.chip--flight{color:var(--waits); background:var(--waits-wash)}
.chip--unsure{color:var(--unsure); background:var(--unsure-wash)}
.chip--done{color:var(--done); background:var(--done-wash)}
.age{font-family:var(--mono); font-variant-numeric:tabular-nums; display:flex; align-items:baseline; gap:0.08em}
.age b{font-size:1.7rem; line-height:1; letter-spacing:-0.03em; font-weight:500}
.age i{font-style:normal; font-size:0.78rem; color:var(--ink-soft)}
.body{display:grid; gap:0.35rem; min-width:0}
.ask{font-size:1.04rem; line-height:1.35; text-wrap:pretty}
.where{font-family:var(--mono); font-size:0.74rem; color:var(--ink-soft)}
.ref{font-family:var(--mono); color:var(--accent)}
.verdict{color:var(--free); font-size:0.95rem; font-style:italic}
.caveat{color:var(--unsure); font-size:0.88rem; font-style:italic}
.line{
  display:grid; grid-template-columns:5.2rem 1fr; gap:0.6rem; align-items:baseline;
  margin-top:0.15rem; min-width:0;
}
.line .tag{
  font-family:var(--mono); font-size:0.62rem; letter-spacing:0.11em; text-transform:uppercase;
  color:var(--ink-soft); padding-top:0.15em;
}
.line code{
  display:block; background:var(--sunk); padding:0.42rem 0.55rem;
  white-space:pre-wrap; overflow-wrap:anywhere; color:var(--ink); line-height:1.45;
  border-left:2px solid var(--rule);
}
.gauge{grid-column:1/-1; height:3px; background:var(--rule-soft); margin-top:0.9rem}
.gauge span{display:block; height:100%}
.gauge--needs span{background:var(--needs)}
.gauge--free span{background:var(--free)}
.gauge--flight span{background:var(--waits)}
.gauge--unsure span{background:var(--unsure)}
.gauge--done span{background:var(--done)}

/* ---- the dense "still waiting" list ---- */
.thins{list-style:none; margin:0; padding:0}
.thin{
  display:grid; grid-template-columns:3.2rem 1fr; gap:0.2rem 0.9rem; align-items:baseline;
  padding:0.6rem 0; border-bottom:1px solid var(--rule-soft); font-size:0.92rem;
}
.thin-age{font-family:var(--mono); font-variant-numeric:tabular-nums; color:var(--ink-soft); font-size:0.8rem}
.thin-ask{min-width:0; overflow-wrap:anywhere}
.thin-on{grid-column:2; color:var(--waits); font-size:0.72rem; overflow-wrap:anywhere}

/* Borders rather than a 1px gap over a coloured ground: a wrapping flex row leaves
   the ground showing as a stray block wherever the last cell stops short. */
.tallystrip{
  list-style:none; margin:1.1rem 0 0.4rem; padding:0; display:flex; flex-wrap:wrap;
  background:var(--surface); border:1px solid var(--rule);
}
.tallystrip li{
  padding:0.5rem 0.75rem; display:flex; gap:0.4rem; align-items:baseline;
  border-right:1px solid var(--rule);
}
.tallystrip li:last-child{border-right:0}
.tallystrip b{font-family:var(--mono); font-variant-numeric:tabular-nums; font-size:1rem}
.tallystrip span{font-family:var(--mono); font-size:0.72rem; color:var(--ink-soft)}

/* ---- unknown ---- */
.unsures{list-style:none; margin:0; padding:0}
.unsure-item{
  display:grid; grid-template-columns:7.5rem 1fr; gap:0.3rem 1.25rem;
  padding:1rem 0; border-bottom:1px solid var(--rule-soft);
}
.unsure-item .kind code{
  color:var(--unsure); font-size:0.68rem; letter-spacing:0.09em; text-transform:uppercase;
}
.why{color:var(--ink-soft); font-size:0.92rem}
.note{font-family:var(--mono); font-size:0.74rem; color:var(--ink-soft); opacity:0.85; overflow-wrap:anywhere}
.proof{margin:0.6rem 0 0; padding-left:1.1rem; color:var(--ink-soft); font-size:0.93rem}
.proof li{margin-top:0.2rem}
.empty{color:var(--ink-soft); font-size:0.95rem; padding:1.1rem 0; font-style:italic}
.empty--earned{font-style:normal; color:var(--ink)}

.cannot{
  display:grid; grid-template-columns:3.5rem 1fr; gap:1rem; align-items:start;
  background:var(--unsure-wash); border-left:3px solid var(--unsure); padding:1.1rem 1.2rem; margin-top:1.2rem;
}
.cannot-mark{font-family:var(--mono); font-size:2.6rem; line-height:0.8; color:var(--unsure)}
.cannot .ask{font-size:1rem}

.colophon{
  margin-top:3.5rem; padding-top:1.2rem; border-top:2px solid var(--ink);
  display:grid; gap:0.55rem; color:var(--ink-soft); font-size:0.88rem;
}
/* The rule spans the sheet; only the prose is held to a readable measure. */
.colophon p{max-width:44rem}
.withheld{color:var(--unsure)}

@media (max-width:34rem){
  body{font-size:16px}
  .row,.unsure-item{grid-template-columns:1fr}
  .rail{flex-direction:row; align-items:baseline; gap:0.7rem}
  .age b{font-size:1.25rem}
  .line{grid-template-columns:1fr; gap:0.2rem}
  .thin{grid-template-columns:1fr}
  .thin-on{grid-column:1}
  .instrument{grid-template-columns:1fr auto}
  .instrument span,.instrument em{grid-column:1/-1}
  .cannot{grid-template-columns:1fr}
}
@media (prefers-reduced-motion:reduce){ *{transition:none !important; animation:none !important} }
"""
)
