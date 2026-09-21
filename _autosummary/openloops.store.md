# openloops.store

Where digests live, and where the change-detection cache lives — two different things.

The digest store is **data**: a local directory of markdown files under
`~/.local/share/openloops/digests/`, addressed as a `MutableMapping[str, str]` so
that swapping it for a git-synced directory or an S3-backed store is one keyword
argument rather than a rewrite. Nothing in openloops opens a file by path.

The sync cache is **not data**: it is a per-machine record of which transcript
revisions have already been read, and deleting it is a distinct operation from deleting
digests. That separation is ADR-010’s rule — a cache purge must not be able to reach
the thing being cached — and it is what makes the regeneration test meaningful: wipe
both, sync again, and every digest comes back byte-identical.

Keys are `{source}/{state}/{session}.md`. The source segment is the machine (or
person) that wrote the digest, so two machines syncing into one git repository never
write the same path and there is nothing to reconcile. The state segment is `open` or
`archive` — **loop state, not process state**. If it ever came to mean “a process is
running”, this would be a session dashboard rather than a record of what sessions said.

```pycon
>>> digest_key('laptop', 'open', 'abc-123')
'laptop/open/abc-123.md'
>>> parse_digest_key('laptop/open/abc-123.md')
('laptop', 'open', 'abc-123')
```

### Functions

| [`data_dir`](#openloops.store.data_dir)()                             | The project's data root.                                         |
|-----------------------------------------------------------------------------------------|------------------------------------------------------------------|
| [`state_dir`](#openloops.store.state_dir)()                            | Where per-machine caches and job logs go.                        |
| [`default_source`](#openloops.store.default_source)([directory])            | This machine's label for its digest folder.                      |
| [`digests_store`](#openloops.store.digests_store)([rootdir])               | The default `digests_store`: markdown files under the data root. |
| [`digest_key`](#openloops.store.digest_key)(source, state, session_key) | The store key for one session's digest.                          |
| [`parse_digest_key`](#openloops.store.parse_digest_key)(key)                  | Split a store key back into `(source, state, session_key)`.      |
| [`load_sync_state`](#openloops.store.load_sync_state)([directory])           | Session id → the transcript revision last read.                  |
| [`save_sync_state`](#openloops.store.save_sync_state)(state[, directory])    | Write the mtime cache, creating its directory.                   |
| [`sync_state_path`](#openloops.store.sync_state_path)([directory])           | Where the mtime cache lives.                                     |

### Classes

| [`Utf8TextFiles`](#openloops.store.Utf8TextFiles)(\*args[, delete_func])   | `dol`'s text-file store with the encoding pinned rather than inherited.   |
|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------|

### *class* openloops.store.Utf8TextFiles(\*args, delete_func=None, \*\*kwargs)

Bases: `PrefixRelativizationMixin`, `Store`

`dol`’s text-file store with the encoding pinned rather than inherited.

`dol` opens text with `encoding=None`, i.e. whatever the locale says. Every
digest contains an em dash, so on a machine where the locale resolves to ASCII — a
container or a cron job with `LANG` unset, an Alpine image — writing one raises,
and in a store two machines share it is worse: one writes bytes the other cannot
read back. Pinning UTF-8 is the whole fix.

#### is_valid_key(k, \*args, \_\_name='is_valid_key', \*\*kwargs)

`is_valid_key` on the inner key – see `mk_relative_path_store`.

#### validate_key(k, \*args, \_\_name='validate_key', \*\*kwargs)

`validate_key` on the inner key – see `mk_relative_path_store`.

### openloops.store.data_dir()

The project’s data root. Override with `OPENLOOPS_DATA_DIR`.

Per-kind subdirectories hang off this; nothing is written directly into it, so a
later kind of data needs no second migration.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.store.default_source(directory=None)

This machine’s label for its digest folder. Override with `OPENLOOPS_SOURCE`.

A short, filename-safe name. It exists so several machines can sync digests into one
place without colliding — not to identify anybody, though on a machine whose
hostname was never changed it may well do; every `ol sync` prints it, and
`OPENLOOPS_SOURCE` overrides it.

**It is sticky.** The hostname is a *seed*, written once to a file under the state
directory and read thereafter. macOS rewrites the hostname when it joins a network
where the name collides — appending `-2`, `-3` — and a label that moved would
fork the store into two complete copies with no dedup and no warning.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.store.digest_key(source, state, session_key)

The store key for one session’s digest.

Both segments are validated, not just the state. `transcript_source=` is a seam
whose documented purpose is “another machine’s synced transcripts”, so a session id
can come from a listing this process did not produce — and a key containing `..`
would make a file-backed store write outside its own root while `sync` reported
success. Validating here means every backend inherits the check.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> digest_key('mac', 'archive', 's1')
'mac/archive/s1.md'
>>> digest_key('mac', 'open', '../../etc/passwd')
Traceback (most recent call last):
    ...
ValueError: session key must be a single safe path segment, got '../../etc/passwd'
```

### openloops.store.digests_store(rootdir=None)

The default `digests_store`: markdown files under the data root.

Any `MutableMapping[str, str]` works in its place — a plain `dict` for tests,
a git-synced directory, an S3-backed store. The keys are what carry the layout, so
a different backend gets the same `{source}/{state}/{session}.md` structure for
free.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> store = digests_store(rootdir='/tmp/openloops-doctest-store')
>>> store['demo/open/s1.md'] = '# hi'
>>> sorted(store)
['demo/open/s1.md']
>>> del store['demo/open/s1.md']
```

### openloops.store.load_sync_state(directory=None)

Session id → the transcript revision last read. Missing or corrupt reads empty.

A corrupt cache is treated as an absent one on purpose: the only cost of being
wrong here is re-deriving digests that were already correct.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### openloops.store.parse_digest_key(key)

Split a store key back into `(source, state, session_key)`.

Both separators are accepted. A file-backed store hands keys back joined with the
platform’s separator, so on Windows every key would fail to parse and every read
path would quietly return nothing while `sync` reported digests written.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> parse_digest_key('mac/archive/s1.md')
('mac', 'archive', 's1')
>>> parse_digest_key('mac' + chr(92) + 'archive' + chr(92) + 's1.md')
('mac', 'archive', 's1')
```

### openloops.store.save_sync_state(state, directory=None)

Write the mtime cache, creating its directory. Returns the path written.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.store.state_dir()

Where per-machine caches and job logs go. Override with `OPENLOOPS_STATE_DIR`.

Deliberately not under [`data_dir()`](#openloops.store.data_dir): everything here is disposable, and keeping
it elsewhere means “clear the cache” can never be mistyped into “delete the digests”.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.store.sync_state_path(directory=None)

Where the mtime cache lives. Deleting this file forces a full re-read.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
