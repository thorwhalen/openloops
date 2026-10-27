# openloops.board_store

The board store’s rules, for a self-hosted phone board: who may write what, and how.

The phone board page (`openloops/data/board/index.html`) keeps its state in a small
document store: collections of JSON documents. On claude.ai that store is the
Artifact `db` capability. On your own server it is whatever serves the \*\*board store
API\*\* below, and this module is that API’s logic, written once so every server that
hosts a board enforces the same rules:

The rules ([`WRITERS`](#openloops.board_store.WRITERS), [`put_doc()`](#openloops.board_store.put_doc)) are the page’s persistence model, enforced
rather than trusted:

- `outbox` events are **immutable**: the first write creates, an identical retry is
  a no-op success, anything else is 409. Only the page (role `viewer`) creates them.
- `drafts` are newest-wins by their own `at`: an older write is acknowledged and
  ignored, so a slow phone cannot overwrite a newer note.
- `receipts`, `meta`, `questions` (and the legacy `state`/`answers`) are
  written only by the receiving session (role `receiver`), never by the page.
- **Imports** (moving a board here: `allow_import=True`) additionally let the
  `receiver` create `outbox` events and write `drafts`. Off by default, and meant
  to be on only while a migration runs: otherwise the receiver’s credentials would be
  as powerful as the owner’s taps, since the receiver acts on events.

**Roles are the server’s job, not this module’s.** A server maps each request to
`viewer` (the owner’s browser login) or `receiver` (the receiving session’s account)
and refuses everything else before calling in here. Like the rest of openloops this
module never reaches the network: it reads and writes a `MutableMapping` (a `dict`,
a files store, anything with the same interface).

```pycon
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
```

### Module Attributes

| [`WRITERS`](#openloops.board_store.WRITERS)        | Who may write each collection.                                           |
|-----------------------------------------------------------------|--------------------------------------------------------------------------|
| [`IMPORT_WRITERS`](#openloops.board_store.IMPORT_WRITERS) | What an import may additionally write, and by whom (see `allow_import`). |

### Functions

| [`get_doc`](#openloops.board_store.get_doc)(store, collection, doc_id)                 | One document, or a 404 [`BoardStoreError`](#openloops.board_store.BoardStoreError).   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`list_docs`](#openloops.board_store.list_docs)(store, collection, \*[, max_docs])       | Every document of `collection`, sorted by id.                                              |
| [`parse_body`](#openloops.board_store.parse_body)(raw)                                    | A request body as JSON, refusing `NaN`/`Infinity`, which JSON does not have.               |
| [`put_doc`](#openloops.board_store.put_doc)(store, collection, doc_id, data, \*, role) | Write one document under the collection's rules; return its id and version.                |

### Exceptions

| [`BoardStoreError`](#openloops.board_store.BoardStoreError)(status, message)   | A refused request, carrying the HTTP status a server should answer with.   |
|-------------------------------------------------------------------------------------|----------------------------------------------------------------------------|

### *exception* openloops.board_store.BoardStoreError(status, message)

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

A refused request, carrying the HTTP status a server should answer with.

### openloops.board_store.IMPORT_WRITERS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= {'drafts': frozenset({'receiver'}), 'outbox': frozenset({'receiver'})}*

What an import may additionally write, and by whom (see `allow_import`).

### openloops.board_store.WRITERS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= {'answers': frozenset({'receiver'}), 'drafts': frozenset({'viewer'}), 'meta': frozenset({'receiver'}), 'outbox': frozenset({'viewer'}), 'questions': frozenset({'receiver'}), 'receipts': frozenset({'receiver'}), 'state': frozenset({'receiver'})}*

Who may write each collection. Every role may read every collection.

### openloops.board_store.get_doc(store, collection, doc_id)

One document, or a 404 [`BoardStoreError`](#openloops.board_store.BoardStoreError).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.board_store.list_docs(store, collection, , max_docs=20000)

Every document of `collection`, sorted by id.

A file that is not valid JSON (a hand edit, a write cut short by a store that does
not write atomically) is counted in `skipped` rather than failing the listing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### openloops.board_store.parse_body(raw)

A request body as JSON, refusing `NaN`/`Infinity`, which JSON does not have.

```pycon
>>> parse_body(b'{"a": 1}')
{'a': 1}
>>> parse_body(b'{"a": NaN}')
Traceback (most recent call last):
  ...
openloops.board_store.BoardStoreError: 400: body is not JSON
```

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### openloops.board_store.put_doc(store, collection, doc_id, data, , role, if_match=None, if_none_match=False, max_bytes=65536, allow_import=False)

Write one document under the collection’s rules; return its id and version.

`created` is `False` for an idempotent repeat of an event and for an unpinned
draft older than the one stored, both of which change nothing. A *pinned* draft
write that loses to a newer one is a 412, so a caller who pinned learns it lost.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
