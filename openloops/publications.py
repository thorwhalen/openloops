"""What your agents handed you lately: recently published annals documents, per session.

openloops answers "what do I owe?"; this answers its sibling, "what did my agents hand
me?", from the documents sessions published with ``annals publish --session <name>``.
It is read-only and does not depend on annals being installed: the list of documents
comes through one seam, ``source=``, which is either the documents themselves (the
``docs`` of ``annals ls``) or a zero-argument callable returning them. The default seam
runs ``annals ls`` and says so, as an unlisted report, when annals is absent -- an
empty list would read as "nothing was published".

>>> docs = [{'id': 'a1', 'title': 'Report', 'created': '2026-01-02T00:00:00Z',
...          'source': {'session': 'sweep'}}]
>>> report = published(source=docs)
>>> report['listed'], report['rows'][0]['session'], report['rows'][0]['url']
(True, 'sweep', 'https://apps.thorwhalen.com/annals/d/a1')
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from typing import Any

__all__ = ["published", "DFLT_DOCUMENT_BASE", "DFLT_LIMIT", "DFLT_TIMEOUT"]

#: Where a published document's page lives (the prefix of ``DFLT_DOCUMENT_URL`` in
#: :mod:`openloops.obligations`).
DFLT_DOCUMENT_BASE = "https://apps.thorwhalen.com/annals/d/"
#: How many recent documents to read.
DFLT_LIMIT = 50
#: Seconds to wait for ``annals ls``.
DFLT_TIMEOUT = 20.0
#: The session shown for a document published without ``--session``.
UNATTRIBUTED = "(none)"


class AnnalsUnavailable(RuntimeError):
    """``annals ls`` could not be read; the message says why."""


def _annals_ls(limit: int, timeout: float) -> list[dict]:
    """The ``docs`` of ``annals ls``, newest first. The only shell-out in this module."""
    executable = shutil.which("annals")
    if executable is None:
        raise AnnalsUnavailable("the `annals` CLI is not on PATH")
    try:
        done = subprocess.run(
            [executable, "ls", "-l", str(limit)],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise AnnalsUnavailable(f"`annals ls` timed out after {timeout:g}s") from None
    except OSError as exc:
        raise AnnalsUnavailable(f"could not run `annals`: {exc}") from None
    if done.returncode != 0:
        lines = [x.strip() for x in (done.stderr or "").splitlines() if x.strip()]
        raise AnnalsUnavailable(
            lines[0] if lines else f"`annals ls` exited {done.returncode}"
        )
    try:
        docs = json.loads(done.stdout)["docs"]
    except (ValueError, KeyError, TypeError):
        raise AnnalsUnavailable("`annals ls` printed something unexpected") from None
    return list(docs)


def _row(doc: Mapping[str, Any], base: str) -> dict[str, Any]:
    source = doc.get("source") or {}
    return {
        "id": doc.get("id", ""),
        "title": doc.get("title", ""),
        "session": source.get("session") or UNATTRIBUTED,
        "when": doc.get("updated") or doc.get("created") or "",
        "kind": doc.get("kind", ""),
        "url": f"{base}{doc.get('id', '')}",
    }


def published(
    *,
    limit: int = DFLT_LIMIT,
    session: str | None = None,
    source: Iterable[Mapping[str, Any]]
    | Callable[[], Iterable[Mapping[str, Any]]]
    | None = None,
    base_url: str = DFLT_DOCUMENT_BASE,
    timeout: float = DFLT_TIMEOUT,
) -> dict[str, Any]:
    """Recently published documents, newest first, each with its session and link.

    ``session`` keeps one session's documents. The result is an envelope:
    ``listed=False`` with an ``error`` means the documents could not be read, which
    must not be mistaken for "none were published".
    """
    try:
        if source is None:
            docs = _annals_ls(limit, timeout)
        else:
            docs = list(source() if callable(source) else source)
    except AnnalsUnavailable as exc:
        return {"listed": False, "error": str(exc), "rows": [], "by_session": {}}
    rows = [_row(d, base_url) for d in docs]
    if session:
        rows = [r for r in rows if r["session"] == session]
    rows.sort(key=lambda r: r["when"], reverse=True)
    rows = rows[: max(limit, 0)] if limit else rows
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["session"]] = counts.get(r["session"], 0) + 1
    return {"listed": True, "error": "", "rows": rows, "by_session": counts}
