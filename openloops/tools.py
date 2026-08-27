"""The package's single list of operations: plain functions, JSON-ready dicts.

Every surface openloops has or might grow — the ``ol`` command today, an MCP server or
an HTTP endpoint later — dispatches from this module and nothing else. The functions
here know nothing about argument parsers, transports or agent hosts; they take flat
serialisable arguments and return flat serialisable results, and printing is somebody
else's job.

Keeping one list is what stops two surfaces from drifting apart. A parity test between
two surfaces is a sign that there are two implementations, and there is one here.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openloops.base import OPEN, STATES, Session
from openloops.dashboard import (
    DFLT_MAX_SESSIONS,
    DFLT_TITLE,
    headline_counts,
    render_dashboard,
)
from openloops.blockers import (
    DFLT_CANDIDATE_LIMIT,
    DFLT_QUERY,
    blocked as _blocked,
)
from openloops.obligations import (
    DFLT_LABEL,
    DFLT_LIMIT,
    DFLT_LIST_TIMEOUT,
    DFLT_PREDICATE_TIMEOUT,
    owed as _owed,
)
from openloops.store import (
    data_dir,
    default_source,
    digests_store as default_digests_store,
    load_sync_state,
    parse_digest_key,
    state_dir,
    sync_state_path,
)
from openloops._sync import retained, sync as _sync
from openloops.transcripts import ClaudeCodeTranscripts

__all__ = [
    "ROW_FIELDS",
    "sync",
    "ls",
    "show",
    "status",
    "owed",
    "blocked",
    "dashboard",
]

#: The keys every :func:`ls` row carries, whatever the digest happens to record.
ROW_FIELDS = (
    "session",
    "source",
    "state",
    "title",
    "ai_title",
    "project",
    "branches",
    "started",
    "ended",
    "last_turn",
    "turns",
    "model",
    "confidence",
    "verified",
)


def _resolve_store(digests_store=None) -> MutableMapping[str, str]:
    return default_digests_store() if digests_store is None else digests_store


def _front_matter(text: str) -> dict[str, str]:
    """The digest's ``key: value`` header, as a dict. Absent header reads as empty.

    >>> _front_matter('---\\nstate: open\\ntitle: a b\\n---\\n# x')
    {'state': 'open', 'title': 'a b'}
    >>> _front_matter('no header here')
    {}
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if _:
            out[key.strip()] = value.strip()
    return out


def sync(
    *,
    source: str | None = None,
    since_days: float | None = None,
    force: bool = False,
    transcript_source: Mapping[str, Session] | None = None,
    digests_store: MutableMapping[str, str] | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Read what changed in the sessions and write the digests. Returns a summary.

    ``since_days`` bounds the scan to recently-modified transcripts; ``force``
    re-derives everything, which must produce an identical store.

    ``state_dir`` scopes the change-detection cache. It matters because the seams do
    not isolate on their own: swapping ``transcript_source`` for a fixture and leaving
    the cache alone writes the fixture's revisions into the caller's real one.
    """
    return _sync(
        transcript_source=transcript_source,
        digests_store=digests_store,
        source=source,
        since_days=since_days,
        state_dir=state_dir,
        force=force,
    )


def ls(
    *,
    state: str = OPEN,
    source: str | None = None,
    project: str | None = None,
    confidence: str | None = None,
    limit: int = 20,
    digests_store: MutableMapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The digests in the store, newest last-turn first.

    ``state`` is ``open``, ``archive`` or ``all``. ``source``, ``project`` and
    ``confidence`` narrow by the digest's own header fields. Each row is that front
    matter plus its key.

    ``confidence='high'`` is the one worth knowing about: most sessions land in ``open``,
    and a good few of those are open only because nothing said otherwise. Filtering to
    ``high`` leaves the ones where the session itself said something.

    >>> rows = ls(digests_store={'m/open/s1.md':
    ...     '---\\nsession: s1\\nstate: open\\nlast_turn: T9\\n---\\n'})
    >>> rows[0]['session'], rows[0]['key']
    ('s1', 'm/open/s1.md')
    """
    if state not in (*STATES, "all"):
        raise ValueError(f"state must be one of {(*STATES, 'all')}, got {state!r}")
    store = _resolve_store(digests_store)
    rows: list[dict[str, Any]] = []
    for key in store:
        try:
            key_source, key_state, session_key = parse_digest_key(key)
        except ValueError:
            continue
        if state != "all" and key_state != state:
            continue
        if source is not None and key_source != source:
            continue
        row = _front_matter(store[key])
        if project is not None and row.get("project") != project:
            continue
        if confidence is not None and row.get("confidence", "high") != confidence:
            continue
        row.setdefault("session", session_key)
        row.setdefault("state", key_state)
        row.setdefault("source", key_source)
        # Every documented field is present on every row, empty when the digest omits
        # it. A row shape that varies by session makes `row["title"]` a coin flip, and
        # it is the first thing anyone writes; it would also make a JSON surface's
        # schema a lie.
        for field in ROW_FIELDS:
            row.setdefault(field, "")
        row["key"] = key
        rows.append(row)
    rows.sort(key=lambda r: (r.get("last_turn") or "", r["key"]), reverse=True)
    return rows[:limit] if limit and limit > 0 else rows


def show(
    session: str,
    *,
    source: str | None = None,
    digests_store: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """One digest in full, found by session id or by a unique prefix of one.

    An exact id always wins over a prefix, so a session whose id happens to be a prefix
    of another stays reachable. ``source`` narrows a store that several machines write
    into, where the same session can legitimately appear more than once.

    >>> store = {'m/open/abcdef.md': '---\\nsession: abcdef\\n---\\nbody'}
    >>> show('abc', digests_store=store)['key']
    'm/open/abcdef.md'
    """
    if not session:
        raise KeyError("no session given")
    store = _resolve_store(digests_store)
    exact, prefixed = [], []
    for key in store:
        try:
            key_source, _state, session_key = parse_digest_key(key)
        except ValueError:
            continue
        if source is not None and key_source != source:
            continue
        if session_key == session:
            exact.append(key)
        elif session_key.startswith(session):
            prefixed.append(key)
    matches = exact or prefixed
    if not matches:
        raise KeyError(f"no digest for session {session!r}")
    if len(matches) > 1:
        listed = "\n  ".join(sorted(matches))
        raise KeyError(
            f"{session!r} matches {len(matches)} digests; narrow it with --source:"
            f"\n  {listed}"
        )
    key = matches[0]
    text = store[key]
    return {"key": key, "text": text, **_front_matter(text)}


def status(
    *,
    source: str | None = None,
    since_days: float | None = None,
    digests_store: MutableMapping[str, str] | None = None,
    transcript_source: Mapping[str, Session] | None = None,
) -> dict[str, Any]:
    """Where everything is, how much of it there is, and how stale the cache is.

    Reports the cache's age because a read served from a cache that nothing has
    refreshed is the failure openloops is built to avoid — a periodic job that died
    leaves a confident, months-old answer behind, and the only defence is saying how
    old the answer is.
    """
    store = _resolve_store(digests_store)
    sessions = (
        ClaudeCodeTranscripts(since_days=since_days)
        if transcript_source is None
        else transcript_source
    )
    # Scope to one source. A store several machines write into holds their digests too,
    # and counting those against *this* machine's transcripts would report every one of
    # them as having lost its transcript — a present-tense claim, and a false one.
    source = default_source() if source is None else source
    counts = {state: 0 for state in STATES}
    for key in store:
        try:
            key_source, key_state, _session = parse_digest_key(key)
        except ValueError:
            continue
        if source is not None and key_source != source:
            continue
        if key_state in counts:
            counts[key_state] += 1

    cache_path = sync_state_path()
    cache_mtime = cache_path.stat().st_mtime if cache_path.exists() else None
    return {
        "source": source,
        "data_dir": str(data_dir()),
        "state_dir": str(state_dir()),
        "digests": dict(counts),
        "cached_sessions": len(load_sync_state()),
        "cache_file": str(cache_path),
        "cache_mtime": cache_mtime,
        "sessions_on_disk": len(sessions),
        "retained": len(retained(store, sessions, source=source)),
    }


def owed(
    *,
    verify: bool = True,
    owners: list[str] | None = None,
    trusted_owners: list[str] | None = None,
    label: str = DFLT_LABEL,
    limit: int = DFLT_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
    predicate_timeout: float = DFLT_PREDICATE_TIMEOUT,
    issues_source: Any = None,
    run_predicate: Any = None,
) -> dict[str, Any]:
    """What you still owe your agents, with each obligation re-checked against the world.

    Lists the open `manual-task` issues across ``owners`` and evaluates the
    ``**Verify:**`` predicate each one carries, reporting three states: ``open``,
    ``discharged`` (the predicate returned 0 — done, but the issue is still open) and
    ``unknown`` (nothing could be checked). Nothing is ever closed, relabelled or
    written; see :mod:`openloops.obligations` for the trust boundary that evaluating a
    predicate crosses, and ``verify=False`` for the way to read without executing.

    The result is an envelope rather than a list, because ``listed=False`` — the query
    itself failed — must not be readable as "nothing owed".

    >>> report = owed(issues_source=[], run_predicate=lambda command: 0)
    >>> report['listed'], report['counts']['total']
    (True, 0)
    """
    return _owed(
        verify=verify,
        owners=owners,
        trusted_owners=trusted_owners,
        label=label,
        limit=limit,
        timeout=timeout,
        predicate_timeout=predicate_timeout,
        issues_source=issues_source,
        run_predicate=run_predicate,
    )


def blocked(
    *,
    resolve: bool = True,
    owners: list[str] | None = None,
    repos: list[str] | None = None,
    query: str = DFLT_QUERY,
    limit: int = DFLT_CANDIDATE_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
    issues_source: Any = None,
    blockers_source: Any = None,
) -> dict[str, Any]:
    """What your repositories are waiting on — and what is no longer waiting.

    The sibling of :func:`owed`: an obligation points at a person, a blocker edge
    points at another repository, and both are commitments nothing is watching. Lists
    the open issues carrying a ``blocked_by`` dependency across ``owners`` (or exactly
    the ``repos`` you name), resolves every edge, and reports three states:
    ``unblocked`` (every blocker closed — the work is free and nobody has been told),
    ``blocked`` (naming the foreign repository it waits on) and ``unknown`` (nothing
    could be resolved). Nothing is ever closed, relabelled or written; see
    :mod:`openloops.blockers` for what discovery costs and what it is measured to miss.

    The result is an envelope rather than a list, because ``listed=False`` — discovery
    itself failed — must not be readable as "nothing is waiting".

    >>> report = blocked(issues_source=[], blockers_source={})
    >>> report['listed'], report['counts']['total']
    (True, 0)
    """
    return _blocked(
        resolve=resolve,
        owners=owners,
        repos=repos or (),
        query=query,
        limit=limit,
        timeout=timeout,
        issues_source=issues_source,
        blockers_source=blockers_source,
    )


def dashboard(
    *,
    verify: bool = True,
    resolve: bool = True,
    owners: list[str] | None = None,
    repos: list[str] | None = None,
    limit: int = DFLT_LIMIT,
    candidate_limit: int = DFLT_CANDIDATE_LIMIT,
    max_sessions: int = DFLT_MAX_SESSIONS,
    title: str = DFLT_TITLE,
    standalone: bool = True,
    path: str | None = None,
    made_at: str | None = None,
    owed_report: Mapping[str, Any] | None = None,
    blocked_report: Mapping[str, Any] | None = None,
    sessions: list[dict[str, Any]] | None = None,
    digests_store: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """All three answers as one self-contained HTML page, for looking at rather than reading.

    Runs :func:`owed`, :func:`blocked` and :func:`ls`, then renders
    :func:`openloops.dashboard.render_dashboard` over what they returned. The page is a
    **snapshot**: it stamps the moment it was made and states, in its largest type, that
    it has checked nothing since — because a published page cannot. Nothing is written
    to GitHub, here or anywhere in openloops.

    ``path`` also writes the page there, scrubbed, and reports where it went.
    ``standalone=False`` returns the same page without the document scaffold, for a host
    that supplies its own ``<head>``.

    Each of the three reads is a seam: pass ``owed_report=``, ``blocked_report=`` or
    ``sessions=`` and that one is not performed. With all three passed this reaches no
    network and needs no ``gh``, which is how the tests run.

    ``counts`` comes back alongside the page and carries ``null`` — not ``0`` — for any
    figure that could not be established, so a caller reading the JSON is held to the
    same three-state rule as a reader looking at the page.

    >>> result = dashboard(owed_report={'listed': True, 'counts': {'open': 0}, 'rows': []},
    ...                    blocked_report={'listed': False, 'error': 'no gh'},
    ...                    sessions=[], made_at='2026-01-01T00:00:00Z')
    >>> result['counts']['free_to_proceed'] is None, result['counts']['unknown'] is None
    (True, True)
    """
    owed_report = (
        _owed(
            verify=verify,
            owners=owners,
            label=DFLT_LABEL,
            limit=limit,
            timeout=DFLT_LIST_TIMEOUT,
            predicate_timeout=DFLT_PREDICATE_TIMEOUT,
        )
        if owed_report is None
        else dict(owed_report)
    )
    blocked_report = (
        _blocked(
            resolve=resolve,
            owners=owners,
            repos=repos or (),
            query=DFLT_QUERY,
            limit=candidate_limit,
            timeout=DFLT_LIST_TIMEOUT,
        )
        if blocked_report is None
        else dict(blocked_report)
    )
    if sessions is None:
        # `limit=0` is "all of them". The renderer needs the true total to be able to
        # say "40 of 154"; a pre-clipped list would let the page state a smaller number
        # than is really open, which is the same family of error as reporting a `?` as 0.
        sessions = ls(state=OPEN, limit=0, digests_store=digests_store)
    made_at = made_at or datetime.now(timezone.utc).isoformat()
    html = render_dashboard(
        owed_report,
        blocked_report,
        sessions,
        made_at=made_at,
        source=default_source(),
        title=title,
        max_sessions=max_sessions,
        standalone=standalone,
    )
    written = ""
    if path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        written = str(target)
    return {
        "html": html,
        "path": written,
        "bytes": len(html.encode("utf-8")),
        "made_at": made_at,
        "counts": headline_counts(owed_report, blocked_report, sessions),
    }


#: Single source of truth for what every surface exposes. The CLI dispatches this list;
#: an MCP or HTTP adapter would reference the same names as strings.
_dispatch_funcs = [sync, ls, show, status, owed, blocked, dashboard]


if __name__ == "__main__":
    import argh

    argh.dispatch_commands(_dispatch_funcs)
