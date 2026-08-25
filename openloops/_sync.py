"""The incremental pass: read what changed, write the digests, report what happened.

One function, :func:`sync`, and the two seams the release is built around are its two
keyword arguments. ``transcript_source=`` decides where sessions are read from and
``digests_store=`` decides where digests are written; both default to something that
works on a fresh machine with no configuration, no credentials and no network.

Change detection is mtime-gated, per ADR-010. A transcript whose revision token matches
the cached one is not re-read. That misses a rewrite that preserves mtime and fires on
a touch that changes nothing, and both are accepted: the alternative is re-deriving
several thousand digests every tick to protect against a case that does not arise.

Two properties this module has to preserve, because tests assert them:

- **A digest is derived, never authored.** Deleting the store and the cache and syncing
  again reproduces every digest byte-for-byte, for every session whose transcript still
  exists. Digests whose transcripts have since been garbage-collected are *retained*
  rather than regenerated — that is the point of the tool, and :func:`sync` never
  deletes one.
- **Nothing is written unscrubbed.** A session whose digest matches a credential
  pattern is skipped, reported, and left out of the cache so the next run tries again.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from openloops.base import STATES, Session
from openloops._classify import classify
from openloops.digest import make_digest
from openloops.egress import CredentialFound
from openloops.store import (
    default_source,
    digest_key,
    digests_store as default_digests_store,
    load_sync_state,
    other_state,
    parse_digest_key,
    save_sync_state,
)
from openloops.transcripts import ClaudeCodeTranscripts, Revisioned

__all__ = ["DIGEST_SCHEMA", "sync", "sync_report_lines"]

#: Bumped whenever the rendered digest could differ for an unchanged transcript — a new
#: front-matter field, a changed section, a widened cue table. It is folded into the
#: cache value so the next tick re-derives instead of leaving every existing digest
#: frozen at bytes an older version produced.
DIGEST_SCHEMA = "1"


def sync(
    *,
    transcript_source: Mapping[str, Session] | None = None,
    digests_store: MutableMapping[str, str] | None = None,
    source: str | None = None,
    since_days: float | None = None,
    state_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bring the digest store up to date with the sessions, and say what changed.

    ``force`` ignores the cache and re-derives everything; the result must be identical,
    which is what makes it safe to suggest when someone suspects a stale digest.

    >>> from openloops.base import STATES, Session
    >>> sessions = {'s1': Session(key='s1',
    ...                               last_assistant_text='Shipped it. Nothing is pending.')}
    >>> store = {}
    >>> r = sync(transcript_source=sessions, digests_store=store, source='demo',
    ...          state_dir='/tmp/openloops-doctest-state', force=True)
    >>> r['written'], sorted(store)
    (1, ['demo/archive/s1.md'])
    >>> sync(transcript_source=sessions, digests_store=store, source='demo',
    ...      state_dir='/tmp/openloops-doctest-state', force=True)['written']
    0
    """
    sessions = Revisioned(
        ClaudeCodeTranscripts(since_days=since_days)
        if transcript_source is None
        else transcript_source
    )
    store = default_digests_store() if digests_store is None else digests_store
    source = default_source() if source is None else source

    cache = {} if force else load_sync_state(state_dir)
    updated = dict(cache)
    scanned = written = unchanged = moved = 0
    errors: list[dict[str, str]] = []

    for key in sessions:
        scanned += 1
        try:
            revision = _stamp(sessions.revision(key))
        except (KeyError, OSError) as exc:
            # The transcript went away between listing and reading. One session's
            # problem must not throw away the whole run — including the cache, which is
            # only written at the end.
            errors.append({"session": key, "problem": f"unreadable: {exc}"})
            continue
        if not force and cache.get(key) == revision and _has_digest(store, source, key):
            unchanged += 1
            continue

        try:
            session = sessions[key]
        except (KeyError, OSError) as exc:
            errors.append({"session": key, "problem": f"unreadable: {exc}"})
            continue
        verdict = classify(session)
        try:
            digest = make_digest(session, verdict, source=source)
        except CredentialFound as exc:
            # The previous digest of this session must not stand: the transcript still
            # exists, so the retention argument does not apply, and leaving it would let
            # `ol ls` serve a stale snapshot with no marker — the exact failure this
            # package exists to prevent, produced by its own error path.
            errors.append({"session": key, "problem": str(exc)})
            for state in STATES:
                store.pop(digest_key(source, state, key), None)
            updated.pop(key, None)
            continue

        if _is_empty(session) and _has_digest(store, source, key):
            # A transcript that read as nothing — truncated, mid-rewrite, or unreadable —
            # yields a content-free digest, and writing it over a good one destroys the
            # only surviving record of that session. For a retention device that is the
            # worst available failure, so the existing digest stands and the run says so.
            errors.append(
                {"session": key, "problem": "read as empty; kept the existing digest"}
            )
            updated.pop(key, None)
            continue

        stale = digest_key(source, other_state(verdict.state), key)
        if stale in store:
            del store[stale]
            moved += 1
        if store.get(digest.key) != digest.text:
            store[digest.key] = digest.text
            written += 1
        updated[key] = revision

    save_sync_state(updated, state_dir)
    return {
        "source": source,
        "scanned": scanned,
        "written": written,
        "unchanged": unchanged,
        "moved": moved,
        "errors": errors,
        "digests": sum(1 for _ in store),
    }


def _is_empty(session: Session) -> bool:
    """Whether a session carried nothing worth keeping.

    Not the same as "a short session": a real one has at least a turn, a closing text,
    or a recap. Zero of all three means the read produced nothing, whatever the reason.

    >>> from openloops.base import Session
    >>> _is_empty(Session(key='s')), _is_empty(Session(key='s', turn_count=1))
    (True, False)
    """
    return not (
        session.turn_count
        or session.last_assistant_text
        or session.recap
        or session.compaction
    )


def _stamp(revision: object) -> str:
    """A cache value: the transcript's revision *and* the schema that rendered it."""
    return f"{revision}:{DIGEST_SCHEMA}"


def _has_digest(store: Mapping[str, str], source: str, key: str) -> bool:
    """Whether either loop state already holds a digest for this session."""
    return any(digest_key(source, state, key) in store for state in ("open", "archive"))


def retained(
    store: Mapping[str, str],
    sessions: Mapping[str, Session],
    *,
    source: str | None = None,
) -> list[str]:
    """Digest keys whose session no longer has a transcript — the retention surplus.

    These are what makes openloops a retention device rather than a view: Claude Code
    garbage-collects transcripts, and a digest outlives the thing it was derived from.
    :func:`sync` never removes them, and they are the one part of the store that a
    from-scratch rebuild does not reproduce.

    >>> retained({'m/open/a.md': '', 'm/open/b.md': ''}, {'a': None})
    ['m/open/b.md']
    """
    out = []
    for key in sorted(store):
        try:
            digest_source, _state, session_key = parse_digest_key(key)
        except ValueError:
            continue
        if source is not None and digest_source != source:
            continue
        if session_key not in sessions:
            out.append(key)
    return out


def sync_report_lines(result: Mapping[str, Any]) -> list[str]:
    """Human-readable lines for a :func:`sync` result, errors last and unmissable.

    >>> sync_report_lines({'source': 'mac', 'scanned': 3, 'written': 1, 'unchanged': 2,
    ...                    'moved': 0, 'digests': 9, 'errors': []})
    ['mac: 3 sessions scanned, 1 digest written, 2 unchanged, 0 moved; 9 digests in store.']
    """
    written = result.get("written", 0)
    lines = [
        f"{result.get('source')}: {result.get('scanned', 0)} sessions scanned, "
        f"{written} digest{'' if written == 1 else 's'} written, "
        f"{result.get('unchanged', 0)} unchanged, {result.get('moved', 0)} moved; "
        f"{result.get('digests', 0)} digests in store."
    ]
    errors = result.get("errors") or []
    if errors:
        lines.append(
            f"{len(errors)} session(s) SKIPPED because their digest matched a "
            "credential pattern. Nothing was written for them, and nothing was "
            "redacted — inspect the transcript before syncing again:"
        )
        lines += [f"  - {e['session']}: {e['problem']}" for e in errors]
    return lines
