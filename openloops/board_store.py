"""The board store's rules, for a self-hosted phone board: who may write what, and how.

The phone board page (``openloops/data/board/index.html``) keeps its state in a small
document store: collections of JSON documents. On claude.ai that store is the
Artifact ``db`` capability. On your own server it is whatever serves the **board store
API** below, and this module is that API's logic, written once so every server that
hosts a board enforces the same rules:

==========================  =====================================================
``GET  {api}/{collection}``        ``{"docs": [{"id", "data", "version"}, ...]}``
``GET  {api}/{collection}/{id}``   ``{"id", "data", "version"}``, or 404
``PUT  {api}/{collection}/{id}``   body = the document (a JSON object); returns
                                   ``{"id", "version", "created"}``. ``If-Match:
                                   <version>`` pins the write to a version and
                                   ``If-None-Match: *`` makes it create-if-absent;
                                   either failing is 412.
==========================  =====================================================

The rules (:data:`WRITERS`, :func:`put_doc`) are the page's persistence model, enforced
rather than trusted:

- ``outbox`` events are **immutable**: the first write creates, an identical retry is
  a no-op success, anything else is 409. Only the page (role ``viewer``) and a
  migration import (role ``receiver``) create them.
- ``drafts`` are newest-wins by their own ``at``: an older write is acknowledged and
  ignored, so a slow phone cannot overwrite a newer note. The receiver may write them too,
  for a migration import.
- ``receipts``, ``meta``, ``questions`` (and the legacy ``state``/``answers``) are
  written only by the receiving session (role ``receiver``), never by the page.

**Roles are the server's job, not this module's.** A server maps each request to
``viewer`` (the owner's browser login) or ``receiver`` (the receiving session's token)
and refuses everything else before calling in here. Like the rest of openloops this
module never reaches the network: it reads and writes a ``MutableMapping`` (a ``dict``,
a ``dol`` files store, anything with the same interface).

    >>> store = {}
    >>> put_doc(store, 'outbox', 'e1', {'action': 'done'}, role='viewer')['created']
    True
    >>> put_doc(store, 'outbox', 'e1', {'action': 'done'}, role='viewer')['created']
    False
    >>> put_doc(store, 'outbox', 'e1', {'action': 'undo'}, role='viewer')
    Traceback (most recent call last):
      ...
    openloops.board_store.BoardStoreError: 409: outbox/e1 exists and events never change
    >>> put_doc(store, 'receipts', 'e1', {'status': 'posted'}, role='viewer')
    Traceback (most recent call last):
      ...
    openloops.board_store.BoardStoreError: 403: role 'viewer' may not write receipts
    >>> [d['id'] for d in list_docs(store, 'outbox')['docs']]
    ['e1']
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

__all__ = [
    "COLLECTIONS",
    "ROLES",
    "WRITERS",
    "BoardStoreError",
    "get_doc",
    "list_docs",
    "put_doc",
]

#: Who may write each collection. Every role may read every collection.
WRITERS: Mapping[str, frozenset[str]] = {
    "outbox": frozenset({"viewer", "receiver"}),
    "drafts": frozenset({"viewer", "receiver"}),
    "receipts": frozenset({"receiver"}),
    "meta": frozenset({"receiver"}),
    "questions": frozenset({"receiver"}),
    "state": frozenset({"receiver"}),
    "answers": frozenset({"receiver"}),
}
COLLECTIONS = tuple(WRITERS)
ROLES = ("viewer", "receiver")
#: Largest accepted document, in bytes of its JSON: a note typed on a phone, with room.
DFLT_MAX_BYTES = 64 * 1024
#: Largest collection a single listing returns. A board has hundreds, not thousands.
DFLT_MAX_DOCS = 5000

# Ids the page and the receiver actually use: event ids, `owner~repo@N` doc ids,
# `run:<key>`. No slash, so an id can never name another collection's key.
_DOC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~@:+-]{0,199}$")
_SUFFIX = ".json"


class BoardStoreError(Exception):
    """A refused request, carrying the HTTP status a server should answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _key(collection: str, doc_id: str | None = None) -> str:
    if collection not in WRITERS:
        raise BoardStoreError(404, f"no collection {collection!r}")
    if doc_id is None:
        return f"{collection}/"
    if not _DOC_ID.match(doc_id or ""):
        raise BoardStoreError(400, f"bad document id {doc_id!r}")
    return f"{collection}/{doc_id}{_SUFFIX}"


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read(store: Mapping[str, Any], key: str) -> str | None:
    try:
        raw = store[key]
    except KeyError:
        return None
    return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)


def list_docs(
    store: Mapping[str, Any], collection: str, *, max_docs: int = DFLT_MAX_DOCS
) -> dict[str, Any]:
    """Every document of ``collection``, sorted by id."""
    prefix = _key(collection)
    docs = []
    for key in sorted(k for k in store if k.startswith(prefix) and k.endswith(_SUFFIX)):
        doc_id = key[len(prefix) : -len(_SUFFIX)]
        if "/" in doc_id:
            continue
        text = _read(store, key)
        if text is None:
            continue
        docs.append({"id": doc_id, "data": json.loads(text), "version": _version(text)})
        if len(docs) >= max_docs:
            raise BoardStoreError(
                507, f"{collection} holds more than {max_docs} documents"
            )
    return {"docs": docs}


def get_doc(store: Mapping[str, Any], collection: str, doc_id: str) -> dict[str, Any]:
    """One document, or a 404 :class:`BoardStoreError`."""
    text = _read(store, _key(collection, doc_id))
    if text is None:
        raise BoardStoreError(404, f"no {collection}/{doc_id}")
    return {"id": doc_id, "data": json.loads(text), "version": _version(text)}


def put_doc(
    store: MutableMapping[str, Any],
    collection: str,
    doc_id: str,
    data: Any,
    *,
    role: str,
    if_match: str | None = None,
    if_none_match: bool = False,
    max_bytes: int = DFLT_MAX_BYTES,
) -> dict[str, Any]:
    """Write one document under the collection's rules; return its id and version.

    ``created`` is ``False`` for an idempotent repeat of an event and for a draft
    older than the one stored, both of which change nothing.
    """
    key = _key(collection, doc_id)
    if role not in WRITERS[collection]:
        raise BoardStoreError(403, f"role {role!r} may not write {collection}")
    if not isinstance(data, Mapping):
        raise BoardStoreError(400, "a document is a JSON object")
    text = _canonical(data)
    if len(text.encode("utf-8")) > max_bytes:
        raise BoardStoreError(413, f"document is larger than {max_bytes} bytes")

    current = _read(store, key)
    if collection == "outbox" and current is not None:
        if current == text:
            return {"id": doc_id, "version": _version(text), "created": False}
        raise BoardStoreError(409, f"outbox/{doc_id} exists and events never change")
    if if_none_match and current is not None:
        raise BoardStoreError(412, f"{collection}/{doc_id} already exists")
    if if_match is not None and (current is None or _version(current) != if_match):
        raise BoardStoreError(
            412, f"{collection}/{doc_id} is not at version {if_match}"
        )
    if collection == "drafts" and current is not None:
        if str(json.loads(current).get("at", "")) > str(data.get("at", "")):
            return {"id": doc_id, "version": _version(current), "created": False}

    store[key] = text
    return {"id": doc_id, "version": _version(text), "created": current is None}
