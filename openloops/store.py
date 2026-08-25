"""Where digests live, and where the change-detection cache lives — two different things.

The digest store is **data**: a local directory of markdown files under
``~/.local/share/openloops/digests/``, addressed as a ``MutableMapping[str, str]`` so
that swapping it for a git-synced directory or an S3-backed store is one keyword
argument rather than a rewrite. Nothing in openloops opens a file by path.

The sync cache is **not data**: it is a per-machine record of which transcript
revisions have already been read, and deleting it is a distinct operation from deleting
digests. That separation is ADR-010's rule — a cache purge must not be able to reach
the thing being cached — and it is what makes the regeneration test meaningful: wipe
both, sync again, and every digest comes back byte-identical.

Keys are ``{source}/{state}/{session}.md``. The source segment is the machine (or
person) that wrote the digest, so two machines syncing into one git repository never
write the same path and there is nothing to reconcile. The state segment is ``open`` or
``archive`` — **loop state, not process state**. If it ever came to mean "a process is
running", this would be a session dashboard rather than a record of what sessions said.

>>> digest_key('laptop', 'open', 'abc-123')
'laptop/open/abc-123.md'
>>> parse_digest_key('laptop/open/abc-123.md')
('laptop', 'open', 'abc-123')
"""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Iterator, MutableMapping
from pathlib import Path

from openloops.base import ARCHIVE, OPEN, STATES

__all__ = [
    "DigestFiles",
    "data_dir",
    "state_dir",
    "default_source",
    "digests_store",
    "digest_key",
    "parse_digest_key",
    "load_sync_state",
    "save_sync_state",
    "sync_state_path",
]


class DigestFiles(MutableMapping):
    """The default digest store: markdown files under a root, keyed ``a/b/c.md``.

    Deliberately small and owned. The seam is the ``MutableMapping`` interface, not any
    particular library — a ``dol`` store, an ``s3dol`` bucket or a plain ``dict`` all
    substitute for this without anything else changing. What a general file store gave
    for free it also gave wrongly for this use: text opened in the *locale* encoding, so
    a cron job with ``LANG`` unset dies on the em dash in every digest; and a delete that
    sends the file to the desktop Trash, which for session digests is an undeclared
    second copy of every superseded one, outside the store, indefinitely.

    Keys are POSIX-style regardless of platform, because they are identifiers that get
    written into a git-synced directory two machines may share — not paths.

    >>> import tempfile
    >>> store = DigestFiles(tempfile.mkdtemp())
    >>> store['mac/open/s1.md'] = 'hello'
    >>> store['mac/open/s1.md'], list(store), 'mac/open/s1.md' in store
    ('hello', ['mac/open/s1.md'], True)
    >>> del store['mac/open/s1.md']
    >>> list(store)
    []
    """

    #: What counts as a digest. Anything else under the root is somebody else's.
    suffix = ".md"

    def __init__(self, rootdir: str | Path):
        self.rootdir = Path(rootdir).expanduser()

    def _path(self, key: str) -> Path:
        parts = [p for p in re.split(r"[\\/]", str(key)) if p]
        if not parts or any(p in (".", "..") for p in parts):
            raise KeyError(f"not a usable digest key: {key!r}")
        return self.rootdir.joinpath(*parts)

    def __getitem__(self, key: str) -> str:
        try:
            return self._path(key).read_text(encoding="utf-8")
        except OSError as exc:
            raise KeyError(key) from exc

    def __setitem__(self, key: str, value: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def __delitem__(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except OSError as exc:
            raise KeyError(key) from exc

    def __iter__(self) -> Iterator[str]:
        if not self.rootdir.is_dir():
            return
        for path in sorted(self.rootdir.rglob(f"*{self.suffix}")):
            if path.is_file():
                yield path.relative_to(self.rootdir).as_posix()

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __contains__(self, key: object) -> bool:
        try:
            return self._path(str(key)).is_file()
        except KeyError:
            return False


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _xdg(env_var: str, fallback: str) -> Path:
    base = os.environ.get(env_var)
    return Path(base).expanduser() if base else Path.home() / fallback


def data_dir() -> Path:
    """The project's data root. Override with ``OPENLOOPS_DATA_DIR``.

    Per-kind subdirectories hang off this; nothing is written directly into it, so a
    later kind of data needs no second migration.
    """
    override = os.environ.get("OPENLOOPS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _xdg("XDG_DATA_HOME", ".local/share") / "openloops"


def state_dir() -> Path:
    """Where per-machine caches and job logs go. Override with ``OPENLOOPS_STATE_DIR``.

    Deliberately not under :func:`data_dir`: everything here is disposable, and keeping
    it elsewhere means "clear the cache" can never be mistyped into "delete the digests".
    """
    override = os.environ.get("OPENLOOPS_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return _xdg("XDG_STATE_HOME", ".local/state") / "openloops"


def default_source(directory: str | Path | None = None) -> str:
    """This machine's label for its digest folder. Override with ``OPENLOOPS_SOURCE``.

    A short, filename-safe name. It exists so several machines can sync digests into one
    place without colliding — not to identify anybody, though on a machine whose
    hostname was never changed it may well do; every ``ol sync`` prints it, and
    ``OPENLOOPS_SOURCE`` overrides it.

    **It is sticky.** The hostname is a *seed*, written once to a file under the state
    directory and read thereafter. macOS rewrites the hostname when it joins a network
    where the name collides — appending ``-2``, ``-3`` — and a label that moved would
    fork the store into two complete copies with no dedup and no warning.
    """
    override = os.environ.get("OPENLOOPS_SOURCE")
    if override:
        return _safe_source(override)
    path = Path(directory).expanduser() if directory else state_dir()
    remembered = path / "source"
    try:
        return _safe_source(remembered.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    label = _safe_source(socket.gethostname().split(".")[0])
    try:
        path.mkdir(parents=True, exist_ok=True)
        remembered.write_text(label, encoding="utf-8")
    except OSError:
        pass
    return label


def _safe_source(raw: str) -> str:
    """A filename-safe source label, or ``local`` when nothing usable is left.

    >>> _safe_source('Some Host.local'), _safe_source('///')
    ('some-host.local', 'local')
    """
    cleaned = _UNSAFE.sub("-", raw or "").strip("-")
    return cleaned.lower() or "local"


def digests_store(rootdir: str | Path | None = None) -> MutableMapping[str, str]:
    """The default ``digests_store``: markdown files under the data root.

    Any ``MutableMapping[str, str]`` works in its place — a plain ``dict`` for tests,
    a git-synced directory, an S3-backed store. The keys are what carry the layout, so
    a different backend gets the same ``{source}/{state}/{session}.md`` structure for
    free.

    >>> store = digests_store(rootdir='/tmp/openloops-doctest-store')
    >>> store['demo/open/s1.md'] = '# hi'
    >>> sorted(store)
    ['demo/open/s1.md']
    >>> del store['demo/open/s1.md']
    """
    root = Path(rootdir).expanduser() if rootdir else data_dir() / "digests"
    root.mkdir(parents=True, exist_ok=True)
    # Delete means delete. The default sends the file to the desktop Trash, which for a
    # store of session digests is an undeclared second copy of every superseded one,
    # outside the store, indefinitely — and reclassification alone produces those daily.
    return DigestFiles(root)


def digest_key(source: str, state: str, session_key: str) -> str:
    """The store key for one session's digest.

    Both segments are validated, not just the state. ``transcript_source=`` is a seam
    whose documented purpose is "another machine's synced transcripts", so a session id
    can come from a listing this process did not produce — and a key containing ``..``
    would make a file-backed store write outside its own root while ``sync`` reported
    success. Validating here means every backend inherits the check.

    >>> digest_key('mac', 'archive', 's1')
    'mac/archive/s1.md'
    >>> digest_key('mac', 'open', '../../etc/passwd')
    Traceback (most recent call last):
        ...
    ValueError: session key must be a single safe path segment, got '../../etc/passwd'
    """
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}, got {state!r}")
    _check_segment(session_key, "session key")
    _check_segment(source, "source")
    return f"{source}/{state}/{session_key}.md"


def _check_segment(value: str, what: str) -> None:
    """Refuse anything that is not one ordinary filename component."""
    if not value or _UNSAFE.search(value) or value in (".", "..") or "/" in value:
        raise ValueError(f"{what} must be a single safe path segment, got {value!r}")


def parse_digest_key(key: str) -> tuple[str, str, str]:
    """Split a store key back into ``(source, state, session_key)``.

    Both separators are accepted. A file-backed store hands keys back joined with the
    platform's separator, so on Windows every key would fail to parse and every read
    path would quietly return nothing while ``sync`` reported digests written.

    >>> parse_digest_key('mac/archive/s1.md')
    ('mac', 'archive', 's1')
    >>> parse_digest_key('mac' + chr(92) + 'archive' + chr(92) + 's1.md')
    ('mac', 'archive', 's1')
    """
    parts = re.split(r"[\\/]", key)
    if len(parts) != 3 or not parts[2].endswith(".md"):
        raise ValueError(f"not a digest key: {key!r}")
    return parts[0], parts[1], parts[2][: -len(".md")]


def other_state(state: str) -> str:
    """The loop state a digest is not in.

    >>> other_state('open'), other_state('archive')
    ('archive', 'open')
    """
    return ARCHIVE if state == OPEN else OPEN


def sync_state_path(directory: str | Path | None = None) -> Path:
    """Where the mtime cache lives. Deleting this file forces a full re-read."""
    base = Path(directory).expanduser() if directory else state_dir()
    return base / "sync-state.json"


def load_sync_state(directory: str | Path | None = None) -> dict[str, str]:
    """Session id → the transcript revision last read. Missing or corrupt reads empty.

    A corrupt cache is treated as an absent one on purpose: the only cost of being
    wrong here is re-deriving digests that were already correct.
    """
    path = sync_state_path(directory)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return (
        {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}
    )


def save_sync_state(state: dict[str, str], directory: str | Path | None = None) -> Path:
    """Write the mtime cache, creating its directory. Returns the path written."""
    path = sync_state_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    return path
