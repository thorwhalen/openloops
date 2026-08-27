"""The other kind of open loop: the one that points at a repository, not at a person.

An agent working in repo X finds that the real fix belongs in repo Y. It files in Y,
writes a workaround in X, and moves on. Y gets fixed. **X is never told.** Nobody was
blocking, nothing waited on a human, so the loop is invisible to :func:`openloops.owed`
— and the workaround in X quietly becomes architecture, noticeable months later only
when somebody asks why the code looks like that.

GitHub already models the edge, and it is already cross-repo: the
``dependencies/blocked_by`` collection on an issue answers with each blocker's own
repository, number and state. The representation costs nothing and exists today.
**What is missing is the harvest** — nothing notices when a blocker is resolved,
because the edge is queryable, not eventful. Closing an issue in Y emits no event that
anything in X is listening to, exactly as setting a secret emits none that
:mod:`openloops.obligations` could hear. This module is that harvest and nothing else.

:func:`blocked` lists the open issues across a fleet that carry a ``blocked_by`` edge,
resolves every edge, and reports **three** states — never two:

===============  ==============================================================
``unblocked``    every blocker is closed. *This is the row that matters*: the work
                 can proceed and nobody has been told. It sorts first, and it
                 carries ``unblocked_days`` — how long it has been free.
``blocked``      at least one blocker is still open. The row names which, with the
                 foreign repository, because "who am I waiting on" is the second
                 question a reader has.
``unknown``      the edges could not be resolved. Displayed as ``?``.
===============  ==============================================================

``?`` is not a rounding error, it is the whole point. A run that could not reach the
dependency graph must not report a clean board, so nothing here is allowed to collapse
``unknown`` into ``unblocked`` or into ``blocked``.

**Nothing here mutates anything.** An ``unblocked`` row is a finding, not an
instruction: the workaround in X may still be the right code, and only a human knows.
You are shown the edge, the blocker's state and the date it closed, and you decide.

Discovery is a candidate list, not an answer
--------------------------------------------

Finding the blocked issues in the first place has two implementations here, and which
runs is decided by whether ``repos=`` is given.

**Across a fleet** (``owners=``, the default): one ``gh search issues`` call carrying
GitHub's own ``is:blocked`` qualifier. One request answers for every repository, which
is what makes this cheap enough to run at the start of a session. But the qualifier is
a *search index*, and a search index is not the dependency graph. Measured on one real
fleet on 2026-08-27, scoped to three owners: ``is:blocked`` returned 15 open issues, of
which **10 carried a ``blocked_by`` edge and 5 carried no dependency edge of any kind**
— not a stale edge, and four of the five carry no sub-issue relation either (the fifth, checked, has two sub-issues, which is a correlation rather than an explanation, since its parent has no dependency edges), simply none. Recall
was perfect on that fleet: all 10 were found, checked against a full per-repository
enumeration of 821 open issues across 148 repositories. Precision was 10/15.

So a candidate is a *candidate*. Every one is re-resolved against
``dependencies/blocked_by``, which is the graph rather than an index of it, and one
with no edge is dropped and counted as ``without_edges`` — visible in the envelope and
printed by the CLI, because a discovery step that quietly disagrees with reality is the
same class of defect as a count that cannot say ``?``. The recall figure is one
measurement on one fleet on one day and nothing here treats it as a guarantee, which
is what the second implementation is for.

**Per repository** (``repos=``): one paginated REST listing per repository, filtered on
the ``issue_dependencies_summary`` GitHub already returns on every row of it — its
``blocked_by`` count is the blockers still open and ``total_blocked_by`` is all of
them. This reads the dependency counts themselves rather than an index of them, so it
cannot over-report and cannot miss; it is the per-repo enumeration ADR-005
``github-authoritative`` requires of anything that must not lose a row, since the
search API is hard-capped at 1000 results. It costs one request per hundred open
issues in each repository you name, so it is the audit, not the daily command.

The N+1, and what bounds it
---------------------------

Resolving edges is **one API call per candidate** — there is no batch form. ``limit=``
is that bound and it defaults to :data:`DFLT_CANDIDATE_LIMIT`; one more than it is
requested, so a candidate list that saturates its own cap comes back ``truncated:
True`` and every surface says so. When the bound is hit the count is a **floor**, never
a total: rows past the cap are not resolved, not guessed at, and not counted. At the
default that is at most 51 requests against a 5000/hour core limit, which per ADR-005
is read from each response's own ``X-Ratelimit-*`` headers rather than from the
rate-limit endpoint — a claim this module keeps by never asking for the number at all.

**Kill criterion** (this ships on an argument, so it names in advance what would retire
it): if, ninety days after this ships, ``counts['unblocked']`` has never once been
non-zero on a real run, delete it. Its entire reason to exist over ``gh search issues
-- 'is:blocked'`` is finding the row that became free while nobody watched; with no
such row it is a slower alias that draws a table. Removal is one command — delete this
module and ``tests/test_blockers.py``, and drop ``blocked`` from
``openloops.tools._dispatch_funcs``, from ``openloops.__main__._commands`` and from
``openloops.__init__``. Nothing imports it, nothing persists, and no other module
changes.

**What this is not.** It is a *reader*, like everything else here. No store, no schema,
no history, no event log, no local copy of the dependency graph: the edge on GitHub
**is** the record. Deleting this module loses no data.

    >>> from datetime import datetime, timezone
    >>> candidates = [
    ...     {'number': 12, 'title': 'Drop the workaround once the engine lands',
    ...      'url': 'https://github.com/acme/widget/issues/12',
    ...      'createdAt': '2026-07-01T00:00:00Z',
    ...      'repository': {'nameWithOwner': 'acme/widget'}},
    ...     {'number': 13, 'title': 'Waiting on the parser rewrite',
    ...      'url': 'https://github.com/acme/widget/issues/13',
    ...      'createdAt': '2026-08-01T00:00:00Z',
    ...      'repository': {'nameWithOwner': 'acme/widget'}},
    ... ]
    >>> edges = {
    ...     'acme/widget#12': [{'number': 15, 'state': 'closed',
    ...                         'closed_at': '2026-08-20T00:00:00Z',
    ...                         'repository': {'full_name': 'acme/engine'}}],
    ...     'acme/widget#13': [{'number': 7, 'state': 'open',
    ...                         'repository': {'full_name': 'acme/parser'}}],
    ... }
    >>> report = blocked(                    # a dict and a dict: no gh, no network
    ...     issues_source=candidates,
    ...     blockers_source=edges,
    ...     now=datetime(2026, 8, 27, tzinfo=timezone.utc),
    ... )
    >>> report['counts']['unblocked'], report['counts']['blocked']
    (1, 1)
    >>> for row in report['rows']:
    ...     print(row['state'], f"{row['repo']}#{row['number']}",
    ...           ' '.join(b['ref'] for b in row['blockers']))
    unblocked acme/widget#12 acme/engine#15 [closed]
    blocked acme/widget#13 acme/parser#7 [open]

The unblocked row says how long it has been free — the number nobody currently has:

    >>> report['rows'][0]['unblocked_days']
    7

A candidate the dependency graph does not agree with is dropped, and the disagreement
is counted rather than hidden:

    >>> quiet = blocked(issues_source=candidates, blockers_source={},
    ...                 now=datetime(2026, 8, 27, tzinfo=timezone.utc))
    >>> quiet['counts']['without_edges'], quiet['counts']['total']
    (2, 0)

A run that could not resolve is never a clean board:

    >>> def unreachable(repo, number):
    ...     raise GhUnavailable('gh: not logged in')
    >>> dark = blocked(issues_source=candidates, blockers_source=unreachable,
    ...                now=datetime(2026, 8, 27, tzinfo=timezone.utc))
    >>> dark['counts']['unknown'], dark['counts']['unblocked']
    (2, 0)
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any

# One `gh` shell-out, one owner-resolution rule and one age calculation exist in this
# package, and they live in `obligations` because that is where they were first needed.
# A second `_gh` would be a defect (ADR-007 mandates exactly one), and a second owner
# rule would let two commands answer about different fleets without saying so. If a
# third module ever wants them they move to a shared home; two do not justify the move.
from openloops.obligations import (
    DFLT_LIST_TIMEOUT,
    OWNERS_ENV_VAR,
    UNKNOWN,
    GhUnavailable,
    _age_days,
    _evidence,
    _gh,
    _repo_of,
    configured_owners,
)

__all__ = [
    "BLOCKED",
    "BLOCKED_FIELDS",
    "BLOCKER_STATES",
    "UNBLOCKED",
    "UNKNOWN",
    "BlockedIssue",
    "Blocker",
    "GhUnavailable",
    "blocked",
    "gh_blocked_by",
    "gh_blocked_candidates",
]

#: Loop state: every blocker is closed. The work can proceed and nobody has been told.
UNBLOCKED = "unblocked"
#: Loop state: at least one blocker is still open, and the row names which.
BLOCKED = "blocked"
#: The three states, in the order a reader cares about them. ``unknown`` is
#: :data:`openloops.obligations.UNKNOWN`: not-checked means the same thing either way.
BLOCKER_STATES = (UNBLOCKED, BLOCKED, UNKNOWN)

#: GitHub's own search qualifier for "this issue has a blocking dependency". It is an
#: index over the graph rather than the graph; see this module's docstring for what
#: that cost when it was measured.
DFLT_QUERY = "is:blocked"

#: How many candidates to resolve. Resolution is one API call per candidate and there
#: is no batch form, so this *is* the N+1 bound. Past it the result is ``truncated``
#: and the counts are a floor.
DFLT_CANDIDATE_LIMIT = 50

#: Page size for both listing calls. ``gh api --paginate`` walks the rest.
_PER_PAGE = 100

#: The two states GitHub gives an issue. Anything else is ``unknown``, never guessed.
_OPEN, _CLOSED = "open", "closed"

#: The candidate fields the fleet-wide search asks for. No ``body``: unlike an
#: obligation, a blocked issue carries its answer in the graph rather than in its text.
_SEARCH_FIELDS = ("createdAt", "number", "repository", "title", "url")


#: Internal candidate key: GitHub's own blocker count, from the audit path only.
_EXPECTED_BLOCKERS = "_expected_blockers"


# --------------------------------------------------------------------------------
# The row shapes.
# --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Blocker:
    """One edge: the issue, in whatever repository it lives, that blocks another.

    ``repo`` is the *blocker's* repository, and carrying it is the whole point — an
    edge that did not name it would answer only the easy half of the question.

    >>> Blocker('acme/engine', 15, 'closed').ref
    'acme/engine#15 [closed]'
    >>> Blocker('acme/engine', 15).ref
    'acme/engine#15 [?]'
    >>> Blocker('', 15, 'closed').ref
    '?#15 [closed]'
    """

    repo: str
    number: int
    state: str = ""
    url: str = ""
    closed_at: str = ""

    @property
    def ref(self) -> str:
        """``owner/name#number [state]`` — how a blocker is written down.

        A ``?`` in either half is a fact about what could be read, never a shrug: an
        edge whose repository the payload did not name says so rather than borrowing
        the blocked issue's own repository and inventing a same-repo dependency.
        """
        return f"{self.repo or '?'}#{self.number} [{self.state or '?'}]"

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, with :attr:`ref` materialised for surfaces that print it."""
        return {**asdict(self), "ref": self.ref}


@dataclass(frozen=True)
class BlockedIssue:
    """One open issue that carries blocker edges, with the verdict those edges imply.

    ``blockers`` is carried in full next to ``state`` so a reader can disagree with the
    verdict rather than absorb it — the same rule :class:`openloops.obligations.
    Obligation` follows for its predicate.

    >>> BlockedIssue('acme/widget', 12, 't', 'u', '2026-01-01T00:00:00Z', 3).state
    'unknown'
    """

    repo: str
    number: int
    title: str
    url: str
    created: str
    age_days: int
    state: str = UNKNOWN
    blockers: tuple[Blocker, ...] = ()
    #: At least one blocker lives in another repository — the shape this module is for.
    cross_repo: bool = False
    #: Days since the last blocker closed, for an ``unblocked`` row: how long the work
    #: has been free while nobody was told. ``0`` for every other state.
    unblocked_days: int = 0
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, blockers included."""
        return {
            **asdict(self),
            "blockers": [blocker.as_dict() for blocker in self.blockers],
        }


#: Every key on every row, whatever the issue's edges happened to say. A row shape that
#: varies by issue makes ``row["blockers"]`` a coin flip and a JSON schema a lie.
BLOCKED_FIELDS = tuple(f.name for f in fields(BlockedIssue))


# --------------------------------------------------------------------------------
# Reading the world. Both calls go through the package's single `gh` shell-out.
# --------------------------------------------------------------------------------


def _json_list(payload: str, *, what: str) -> list[dict[str, Any]]:
    """Parse a ``gh`` JSON array. Anything else is :class:`GhUnavailable`.

    Never an empty list on a parse failure: "I could not read the answer" and "the
    answer is nothing" are the two things this package refuses to conflate.
    """
    try:
        rows = json.loads(payload or "[]")
    except ValueError as exc:
        raise GhUnavailable(f"`{what}` returned no usable JSON: {exc}") from None
    if not isinstance(rows, list):
        raise GhUnavailable(f"`{what}` returned something other than a list")
    return [row for row in rows if isinstance(row, Mapping)]


def _search_candidates(
    owners: Sequence[str], *, query: str, limit: int, timeout: float
) -> list[dict[str, Any]]:
    """One fleet-wide ``gh search issues`` call. Cheap, and only ever a candidate list.

    A *filtered* search, not an enumeration, which is the only form ADR-005 allows:
    the qualifier is applied server-side and the result is capped.
    """
    args = ["search", "issues"]
    for owner in owners:
        args += ["--owner", owner]
    args += [
        "--state",
        _OPEN,
        "--limit",
        str(limit),
        "--json",
        ",".join(_SEARCH_FIELDS),
        "--",
        query,
    ]
    return _json_list(_gh(args, timeout=timeout), what="gh search issues")


def _repo_candidates(
    repos: Sequence[str], *, limit: int, timeout: float
) -> list[dict[str, Any]]:
    """Per-repository enumeration, filtered on the dependency counts GitHub returns.

    The listing endpoint already carries ``issue_dependencies_summary`` on every row,
    so one paginated request per repository names every issue with a blocker without
    touching the search index at all. Pull requests are skipped: they are in the same
    collection and they are not what this counts.
    """
    found: list[dict[str, Any]] = []
    for repo in repos:
        path = f"repos/{repo}/issues?state={_OPEN}&per_page={_PER_PAGE}"
        rows = _json_list(
            _gh(["api", path, "--paginate"], timeout=timeout), what=f"gh api {path}"
        )
        for row in rows:
            if row.get("pull_request"):
                continue
            summary = row.get("issue_dependencies_summary") or {}
            if not isinstance(summary, Mapping) or not summary.get("total_blocked_by"):
                continue
            found.append(
                {
                    # GitHub's own count of this issue's blockers, kept so that an edge
                    # listing which disagrees with it can be reported as `?` rather than
                    # dropped. On this path the row was SELECTED because the count was
                    # non-zero, so an empty listing is a contradiction, not an absence.
                    _EXPECTED_BLOCKERS: summary.get("total_blocked_by"),
                    "number": row.get("number"),
                    "title": row.get("title"),
                    "url": row.get("html_url"),
                    "createdAt": row.get("created_at"),
                    "repository": {"nameWithOwner": repo},
                }
            )
            if len(found) >= limit:
                # Stopping here rather than reading on is what makes the cap visible:
                # the caller asked for one more than it reports, so a full list is
                # reported as truncated instead of being silently trimmed.
                return found
    return found


def gh_blocked_candidates(
    *,
    owners: Sequence[str] = (),
    repos: Sequence[str] = (),
    query: str = DFLT_QUERY,
    limit: int = DFLT_CANDIDATE_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
) -> list[dict[str, Any]]:
    """The default ``issues_source``: open issues that *may* carry a blocker edge.

    ``repos=`` chooses the exact per-repository enumeration; otherwise ``owners=``
    drives one fleet-wide search. Both return rows shaped the way ``gh search issues``
    shapes them — ``createdAt``, ``number``, ``repository``, ``title``, ``url`` — so
    everything downstream reads one shape. Which one to use, and what each costs and
    misses, is the "Discovery is a candidate list" section of this module's docstring.

    A large repository can take longer than ``timeout`` to paginate; that is a
    :class:`GhUnavailable`, which reads ``?``, not an empty answer.
    """
    if repos:
        return _repo_candidates(repos, limit=limit, timeout=timeout)
    if not owners:
        raise GhUnavailable(
            f"no owners to search: set {OWNERS_ENV_VAR}, or name repositories directly"
        )
    return _search_candidates(owners, query=query, limit=limit, timeout=timeout)


def gh_blocked_by(
    repo: str, number: int, *, timeout: float = DFLT_LIST_TIMEOUT
) -> list[dict[str, Any]]:
    """The default ``blockers_source``: the blocker edges out of one issue.

    One request per issue — the N+1 :func:`blocked` bounds with ``limit=``. Returns the
    rows GitHub sends, unparsed and unjudged; :func:`_verdict` is what reads a state
    out of them. An issue with no edges answers ``[]``, which is an answer.
    """
    path = (
        f"repos/{repo}/issues/{number}/dependencies/blocked_by?per_page={_PER_PAGE}"
    )
    return _json_list(
        _gh(["api", path, "--paginate"], timeout=timeout), what=f"gh api {path}"
    )


# --------------------------------------------------------------------------------
# Reading a verdict out of the edges.
# --------------------------------------------------------------------------------


def _repo_of_blocker(edge: Mapping[str, Any]) -> str:
    """The blocker's ``owner/name``, from the payload or failing that from its URL.

    >>> _repo_of_blocker({'repository': {'full_name': 'acme/engine'}})
    'acme/engine'
    >>> _repo_of_blocker({'html_url': 'https://github.com/acme/engine/issues/15'})
    'acme/engine'
    >>> _repo_of_blocker({})
    ''
    """
    repository = edge.get("repository")
    if isinstance(repository, Mapping):
        named = repository.get("full_name") or repository.get("nameWithOwner")
        if named:
            return str(named)
    elif isinstance(repository, str) and repository:
        return repository
    url = str(edge.get("html_url") or edge.get("url") or "")
    parts = [part for part in url.split("/") if part]
    # .../github.com/OWNER/NAME/issues/N — the two segments before the collection name.
    for collection in ("issues", "pull"):
        if collection in parts:
            at = parts.index(collection)
            if at >= 2:
                return f"{parts[at - 2]}/{parts[at - 1]}"
    return ""


def _blockers_from(edges: Iterable[Mapping[str, Any]]) -> tuple[Blocker, ...]:
    """Turn raw dependency rows into :class:`Blocker` values, judging nothing yet.

    >>> _blockers_from([{'number': 15, 'state': 'closed',
    ...                  'repository': {'full_name': 'acme/engine'}}])[0].ref
    'acme/engine#15 [closed]'
    """
    blockers = []
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        state = str(edge.get("state") or "").strip().lower()
        blockers.append(
            Blocker(
                repo=_repo_of_blocker(edge),
                number=int(edge.get("number") or 0),
                state=state if state in (_OPEN, _CLOSED) else "",
                url=str(edge.get("html_url") or ""),
                closed_at=str(edge.get("closed_at") or ""),
            )
        )
    return tuple(blockers)


def _refs(blockers: Iterable[Blocker]) -> str:
    return " ".join(blocker.ref for blocker in blockers)


def _verdict(blockers: Sequence[Blocker]) -> tuple[str, str]:
    """``(state, evidence)`` for one issue's edges. The three-state rule lives here.

    Read it as a sequence of refusals: an unreadable blocker state is never rounded to
    either answer; one blocker still open is enough to keep the row blocked; only *all*
    of them closed makes a row free.

    >>> _verdict([Blocker('acme/engine', 15, 'closed')])
    ('unblocked', 'every blocker is closed: acme/engine#15 [closed]')
    >>> _verdict([Blocker('a/b', 1, 'open'), Blocker('a/c', 2, 'closed')])[0]
    'blocked'
    >>> _verdict([Blocker('a/b', 1, 'wat')])[0]
    'unknown'
    >>> _verdict([])[0]
    'unknown'
    """
    if not blockers:
        return UNKNOWN, "no blocker edges were returned"
    unreadable = [b for b in blockers if b.state not in (_OPEN, _CLOSED)]
    if unreadable:
        return UNKNOWN, _evidence(
            "a blocker's state could not be read:", _refs(unreadable)
        )
    still_open = [b for b in blockers if b.state == _OPEN]
    if still_open:
        return BLOCKED, _evidence(
            f"{len(still_open)} of {len(blockers)} blockers still open:",
            _refs(still_open),
        )
    return UNBLOCKED, _evidence("every blocker is closed:", _refs(blockers))


def _unblocked_days(blockers: Sequence[Blocker], now: datetime) -> int:
    """How long since the *last* blocker closed. ``0`` when none of them says.

    ISO-8601 stamps in UTC sort lexicographically, so the maximum is the most recent.

    >>> from datetime import datetime, timezone
    >>> _unblocked_days(
    ...     [Blocker('a/b', 1, 'closed', closed_at='2026-08-20T00:00:00Z'),
    ...      Blocker('a/c', 2, 'closed', closed_at='2026-08-10T00:00:00Z')],
    ...     datetime(2026, 8, 27, tzinfo=timezone.utc))
    7
    """
    stamps = [b.closed_at for b in blockers if b.closed_at]
    return _age_days(max(stamps), now) if stamps else 0


#: What each state is worth in the ordering: what is free to do first, what was never
#: checked next, what is still waiting last. Within a state, cross-repo rows come
#: first — a same-repo blocker is at least visible to the repo that owns it.
_STATE_RANK = {UNBLOCKED: 0, UNKNOWN: 1, BLOCKED: 2}


def _sort_key(row: BlockedIssue) -> tuple:
    return (
        _STATE_RANK.get(row.state, 9),
        0 if row.cross_repo else 1,
        -row.age_days,
        row.repo,
        row.number,
    )


# --------------------------------------------------------------------------------
# The operation.
# --------------------------------------------------------------------------------


def _candidates(issues_source: Any, **query: Any) -> list[dict[str, Any]]:
    """Call the source if it is callable; otherwise take it as the rows themselves."""
    if issues_source is None:
        return gh_blocked_candidates(**query)
    if callable(issues_source):
        return list(issues_source(**query))
    return [dict(row) for row in issues_source]


def _edges_of(
    blockers_source: Any, repo: str, number: int, *, timeout: float
) -> list[Mapping[str, Any]]:
    """One issue's edges, from whichever kind of source was injected.

    A mapping keyed ``'owner/name#number'`` is accepted because a test fixture is
    naturally written that way, and a missing key there means "no edges" — which the
    caller reads as a candidate the graph does not agree with, not as an error.
    """
    if blockers_source is None:
        return gh_blocked_by(repo, number, timeout=timeout)
    if isinstance(blockers_source, Mapping):
        return list(blockers_source.get(f"{repo}#{number}", ()))
    return list(blockers_source(repo, number))


def blocked(
    *,
    resolve: bool = True,
    owners: Iterable[str] | None = None,
    repos: Iterable[str] = (),
    query: str = DFLT_QUERY,
    limit: int = DFLT_CANDIDATE_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
    now: datetime | None = None,
    issues_source: Any = None,
    blockers_source: Any = None,
) -> dict[str, Any]:
    """Open issues that carry a blocker edge, with every edge resolved.

    The row that matters sorts first: ``unblocked`` — every blocker closed, the work
    free to proceed, and nothing anywhere has said so. ``blocked`` rows name what they
    are waiting on, foreign repository included. ``unknown`` means the edges could not
    be read, and it is never rounded into either of the others.

    ``owners=`` scopes the fleet-wide search (default: :func:`openloops.obligations.
    configured_owners`, the same fleet ``ol owed`` answers about, so two commands never
    quietly disagree about which repositories exist). ``repos=`` instead enumerates the
    repositories you name exactly, which is the audit path.

    ``resolve=False`` lists candidates without spending one API call each; every row
    then reads ``unknown``, because that is what is true about it.

    Two seams, each one keyword argument, each defaulting to a real implementation:
    ``issues_source=`` (defaults to :func:`gh_blocked_candidates`; a list of dicts
    substitutes) and ``blockers_source=`` (defaults to :func:`gh_blocked_by`; a mapping
    from ``'owner/name#number'`` to edges, or any callable of ``(repo, number)``,
    substitutes). With both injected this reaches no network and needs no ``gh``.

    Returns one envelope, never a bare list, because a reader has to be able to tell
    "nothing is waiting" from "I could not find out":

    ``listed``
        ``False`` when *discovery itself* failed. Every surface must render that as
        ``?``. The counts are zeros and they mean nothing.
    ``resolved``
        whether edges were resolved at all.
    ``truncated``
        the candidate list saturated ``limit``, so the counts are a floor.
    ``counts``
        ``unblocked`` / ``blocked`` / ``unknown``, plus ``cross_repo``, ``candidates``
        (how many discovery offered), ``without_edges`` (how many of those the
        dependency graph disagreed about) and ``total`` (how many rows).
    ``rows``
        one dict per issue, with every key in :data:`BLOCKED_FIELDS`.

    >>> report = blocked(issues_source=[], blockers_source={})
    >>> report['listed'], report['counts']['total'], report['rows']
    (True, 0, [])

    Discovery that could not run is not "nothing is waiting":

    >>> def broken(**query):
    ...     raise GhUnavailable('gh: not logged in')
    >>> report = blocked(issues_source=broken)
    >>> report['listed'], report['error'], report['counts']['total']
    (False, 'gh: not logged in', 0)
    """
    now = datetime.now(timezone.utc) if now is None else now
    named_repos = tuple(repos)
    counts = {
        UNBLOCKED: 0,
        BLOCKED: 0,
        UNKNOWN: 0,
        "cross_repo": 0,
        "candidates": 0,
        "without_edges": 0,
        "total": 0,
    }

    def envelope(**overrides: Any) -> dict[str, Any]:
        base = {
            "listed": True,
            "resolved": resolve,
            "error": "",
            "truncated": False,
            "query": query,
            "owners": [],
            "repos": list(named_repos),
            "counts": dict(counts),
            "rows": [],
        }
        return {**base, **overrides}

    try:
        # Resolving owners can itself need `gh`. It is skipped when repositories were
        # named or when the caller supplied the rows, so an injected source stays
        # offline and an audit of three repositories does not ask about a whole fleet.
        if owners is not None:
            resolved_owners = tuple(owners)
        elif named_repos or issues_source is not None:
            resolved_owners = ()
        else:
            resolved_owners = configured_owners(timeout=timeout)
        raw = _candidates(
            issues_source,
            owners=resolved_owners,
            repos=named_repos,
            query=query,
            limit=limit + 1,  # one more than we report: saturation must be visible
            timeout=timeout,
        )
    except GhUnavailable as exc:
        return envelope(listed=False, error=str(exc), owners=list(owners or ()))

    truncated = len(raw) > limit
    considered = raw[:limit]
    rows: list[BlockedIssue] = []
    without_edges = 0

    for issue in considered:
        repo = _repo_of(issue)
        number = int(issue.get("number") or 0)
        created = str(issue.get("createdAt") or "")
        common = {
            "repo": repo,
            "number": number,
            "title": str(issue.get("title") or ""),
            "url": str(issue.get("url") or ""),
            "created": created,
            "age_days": _age_days(created, now),
        }
        if not resolve:
            rows.append(
                BlockedIssue(
                    **common, state=UNKNOWN, evidence="not resolved (resolve=False)"
                )
            )
            continue
        try:
            edges = _edges_of(blockers_source, repo, number, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - a source that blew up is not an answer
            rows.append(
                BlockedIssue(
                    **common,
                    state=UNKNOWN,
                    evidence=_evidence("the blocker edges could not be read:", str(exc)),
                )
            )
            continue
        blockers = _blockers_from(edges)
        if not blockers:
            expected = issue.get(_EXPECTED_BLOCKERS)
            if expected:
                # GitHub said this issue has blockers and then listed none. That is a
                # contradiction, not an absence -- most likely a blocker in a repository
                # this token cannot read. Dropping it would print a clean board over an
                # issue known to be waiting, which is the one failure this module exists
                # to prevent. It is `?`.
                rows.append(
                    BlockedIssue(
                        **common,
                        state=UNKNOWN,
                        evidence=_evidence(
                            f"GitHub reports {expected} blocker(s) but listed none;",
                            "a blocker in a repository this token cannot read would",
                            "look exactly like this",
                        ),
                    )
                )
                continue
            # Search offered a row the dependency graph does not agree with, and nothing
            # claims otherwise. Not a third state and not this module's subject -- but
            # counted, and every surface prints the count.
            without_edges += 1
            continue
        state, evidence = _verdict(blockers)
        rows.append(
            BlockedIssue(
                **common,
                state=state,
                blockers=blockers,
                cross_repo=any(b.repo and b.repo != repo for b in blockers),
                unblocked_days=(
                    _unblocked_days(blockers, now) if state == UNBLOCKED else 0
                ),
                evidence=evidence,
            )
        )

    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1
        counts["cross_repo"] += 1 if row.cross_repo else 0
    counts["candidates"] = len(considered)
    counts["without_edges"] = without_edges
    counts["total"] = len(rows)

    return envelope(
        owners=list(resolved_owners),
        truncated=truncated,
        counts=dict(counts),
        rows=[row.as_dict() for row in sorted(rows, key=_sort_key)],
    )
