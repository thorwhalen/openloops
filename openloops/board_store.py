"""The board store's rules, for a self-hosted phone board: who may write what, and how.

The phone board page (``openloops/data/board/index.html``) keeps its state in a small
document store: collections of JSON documents. On claude.ai that store is the
Artifact ``db`` capability. On your own server it is whatever serves the **board store
API** below, and this module is that API's logic, written once so every server that
hosts a board enforces the same rules:

==========================  =====================================================
``GET  {api}/{collection}``        ``{"docs": [{"id", "data", "version"}, ...],
                                   "skipped": N}`` (``skipped``: unreadable files)
``GET  {api}/{collection}/{id}``   ``{"id", "data", "version"}``, or 404
``PUT  {api}/{collection}/{id}``   body = the document (a JSON object); returns
                                   ``{"id", "version", "created"}``. ``If-Match:
                                   <version>`` pins the write to a version
                                   (``If-Match: *``: to any existing version) and
                                   ``If-None-Match: *`` makes it create-if-absent;
                                   either failing is 412.
==========================  =====================================================

The rules (:data:`WRITERS`, :func:`put_doc`) are the page's persistence model, enforced
rather than trusted:

- ``outbox`` events are **immutable**: the first write creates, an identical retry is
  a no-op success, anything else is 409. Only the page (role ``viewer``) creates them.
- ``drafts`` are newest-wins by their own ``at``: an older write is acknowledged and
  ignored, so a slow phone cannot overwrite a newer note.
- ``receipts``, ``meta``, ``questions`` (and the legacy ``state``/``answers``) are
  written only by the receiving session (role ``receiver``), never by the page.
- **Imports** (moving a board here: ``allow_import=True``) additionally let the
  ``receiver`` create ``outbox`` events and write ``drafts``. Off by default, and meant
  to be on only while a migration runs: otherwise the receiver's credentials would be
  as powerful as the owner's taps, since the receiver acts on events.

**Roles are the server's job, not this module's.** A server maps each request to
``viewer`` (the owner's browser login) or ``receiver`` (the receiving session's account)
and refuses everything else before calling in here. Like the rest of openloops this
module never reaches the network: it reads and writes a ``MutableMapping`` (a ``dict``,
a files store, anything with the same interface).

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
    "IMPORT_WRITERS",
    "ROLES",
    "WRITERS",
    "BoardStoreError",
    "get_doc",
    "list_docs",
    "parse_body",
    "put_doc",
]

#: Who may write each collection. Every role may read every collection.
WRITERS: Mapping[str, frozenset[str]] = {
    "outbox": frozenset({"viewer"}),
    "drafts": frozenset({"viewer"}),
    "receipts": frozenset({"receiver"}),
    "meta": frozenset({"receiver"}),
    "questions": frozenset({"receiver"}),
    "state": frozenset({"receiver"}),
    "answers": frozenset({"receiver"}),
}
#: What an import may additionally write, and by whom (see ``allow_import``).
IMPORT_WRITERS: Mapping[str, frozenset[str]] = {
    "outbox": frozenset({"receiver"}),
    "drafts": frozenset({"receiver"}),
}
COLLECTIONS = tuple(WRITERS)
ROLES = ("viewer", "receiver")
#: Largest accepted document, in bytes of its JSON: a note typed on a phone, with room.
DFLT_MAX_BYTES = 64 * 1024
#: Largest collection a single listing returns. A board's outbox grows by a few hundred
#: events a week; long before this, archive receipted events.
DFLT_MAX_DOCS = 20000

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
    # `allow_nan=False`: a stored NaN would be unreadable by every JSON client after it.
    try:
        return json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except ValueError as exc:
        raise BoardStoreError(400, f"not storable as JSON: {exc}") from None


def parse_body(raw: bytes | str) -> Any:
    """A request body as JSON, refusing ``NaN``/``Infinity``, which JSON does not have.

    >>> parse_body(b'{"a": 1}')
    {'a': 1}
    >>> parse_body(b'{"a": NaN}')
    Traceback (most recent call last):
      ...
    openloops.board_store.BoardStoreError: 400: body is not JSON
    """

    def refuse(name):
        raise ValueError(name)

    try:
        return json.loads(raw or b"null", parse_constant=refuse)
    except ValueError:
        raise BoardStoreError(400, "body is not JSON") from None


def _version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read(store: Mapping[str, Any], key: str) -> str | None:
    try:
        raw = store[key]
    except KeyError:
        return None
    return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)


def _loads_or_empty(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def list_docs(
    store: Mapping[str, Any], collection: str, *, max_docs: int = DFLT_MAX_DOCS
) -> dict[str, Any]:
    """Every document of ``collection``, sorted by id.

    A file that is not valid JSON (a hand edit, a write cut short by a store that does
    not write atomically) is counted in ``skipped`` rather than failing the listing.
    """
    prefix = _key(collection)
    docs, skipped = [], 0
    for key in sorted(k for k in store if k.startswith(prefix) and k.endswith(_SUFFIX)):
        doc_id = key[len(prefix) : -len(_SUFFIX)]
        if "/" in doc_id:
            continue
        text = _read(store, key)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            skipped += 1
            continue
        docs.append({"id": doc_id, "data": data, "version": _version(text)})
        if len(docs) > max_docs:
            raise BoardStoreError(
                507, f"{collection} holds more than {max_docs} documents"
            )
    return {"docs": docs, "skipped": skipped}


def get_doc(store: Mapping[str, Any], collection: str, doc_id: str) -> dict[str, Any]:
    """One document, or a 404 :class:`BoardStoreError`."""
    text = _read(store, _key(collection, doc_id))
    if text is None:
        raise BoardStoreError(404, f"no {collection}/{doc_id}")
    try:
        data = json.loads(text)
    except ValueError:
        raise BoardStoreError(500, f"{collection}/{doc_id} is unreadable") from None
    return {"id": doc_id, "data": data, "version": _version(text)}


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
    allow_import: bool = False,
) -> dict[str, Any]:
    """Write one document under the collection's rules; return its id and version.

    ``created`` is ``False`` for an idempotent repeat of an event and for an unpinned
    draft older than the one stored, both of which change nothing. A *pinned* draft
    write that loses to a newer one is a 412, so a caller who pinned learns it lost.
    """
    key = _key(collection, doc_id)
    writers = WRITERS[collection]
    if allow_import:
        writers = writers | IMPORT_WRITERS.get(collection, frozenset())
    if role not in writers:
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
    if if_match is not None and (
        current is None or (if_match != "*" and _version(current) != if_match)
    ):
        raise BoardStoreError(
            412, f"{collection}/{doc_id} is not at version {if_match}"
        )
    if collection == "drafts" and current is not None:
        if str(_loads_or_empty(current).get("at", "")) > str(data.get("at", "")):
            if if_match is not None:
                raise BoardStoreError(412, f"drafts/{doc_id} holds a newer draft")
            return {"id": doc_id, "version": _version(current), "created": False}

    store[key] = text
    return {"id": doc_id, "version": _version(text), "created": current is None}
