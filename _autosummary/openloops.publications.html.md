# openloops.publications

What your agents handed you lately: recently published annals documents, per session.

openloops answers “what do I owe?”; this answers its sibling, “what did my agents hand
me?”, from the documents sessions published with `annals publish --session <name>`.
It is read-only and does not depend on annals being installed: the list of documents
comes through one seam, `source=`, which is either the documents themselves (the
`docs` of `annals ls`) or a zero-argument callable returning them. The default seam
runs `annals ls` and says so, as an unlisted report, when annals is absent – an
empty list would read as “nothing was published”.

```pycon
>>> docs = [{'id': 'a1', 'title': 'Report', 'created': '2026-01-02T00:00:00Z',
...          'source': {'session': 'sweep'}}]
>>> report = published(source=docs)
>>> report['listed'], report['rows'][0]['session'], report['rows'][0]['url']
(True, 'sweep', 'https://apps.thorwhalen.com/annals/d/a1')
```

### Module Attributes

| [`DFLT_DOCUMENT_BASE`](#openloops.publications.DFLT_DOCUMENT_BASE)   | Where a published document's page lives (the prefix of `DFLT_DOCUMENT_URL` in [`openloops.obligations`](openloops.obligations.html.md#module-openloops.obligations)).   |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_LIMIT`](#openloops.publications.DFLT_LIMIT)           | How many recent documents to read.                                                                                                                                                    |
| [`DFLT_TIMEOUT`](#openloops.publications.DFLT_TIMEOUT)         | Seconds to wait for `annals ls`.                                                                                                                                                      |

### Functions

| [`published`](#openloops.publications.published)(\*[, limit, session, source, ...])   | Recently published documents, newest first, each with its session and link.   |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### openloops.publications.DFLT_DOCUMENT_BASE *= 'https://apps.thorwhalen.com/annals/d/'*

Where a published document’s page lives (the prefix of `DFLT_DOCUMENT_URL` in
[`openloops.obligations`](openloops.obligations.html.md#module-openloops.obligations)).

### openloops.publications.DFLT_LIMIT *= 50*

How many recent documents to read.

### openloops.publications.DFLT_TIMEOUT *= 20.0*

Seconds to wait for `annals ls`.

### openloops.publications.published(, limit=50, session=None, source=None, base_url='https://apps.thorwhalen.com/annals/d/', timeout=20.0)

Recently published documents, newest first, each with its session and link.

`session` keeps one session’s documents. The result is an envelope:
`listed=False` with an `error` means the documents could not be read, which
must not be mistaken for “none were published”.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
