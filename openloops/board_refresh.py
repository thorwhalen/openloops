"""Keep the phone board within a day of GitHub, without a session remembering to.

The board (:mod:`openloops.board`) is built by hand once: gather, classify, build. Left
alone it goes stale (a board built 2026-10-27 was still that build on 2026-11-09, with
210 of its 420 cards closed and 222 new items missing). :func:`refresh_board` is the
rebuild as one deterministic, model-free step meant to run from a timer (``ol
install-refresh-job``) or by hand (``ol board-refresh WORK``):

1. gather the open items (:func:`openloops.tasks.gather`) over the scope saved in
   ``WORK/refresh.json`` (flags given on the command line are saved there first, and
   what ``OPENLOOPS_OWNERS``/``OPENLOOPS_EXCLUDE_REPOS`` or the default owners resolve
   to is saved as explicit lists, so a timer without that environment sweeps the same
   scope: :func:`pin_env_scope`);
2. merge them with the live ``WORK/board/tasks.json`` (:func:`merge_refresh`, pure):
   the earlier record of every id still open is kept, with its title and url
   refreshed from GitHub and nothing re-classified; each new id gets the free
   heuristic record;
3. if nothing opened, closed or was retitled, stop (``rebuilt: False``);
4. otherwise rebuild into a temporary directory and move each file into place
   (``os.replace``: the receiver job reads ``tasks.json`` at any moment); the new ids
   accumulate in ``WORK/new-items.json`` for a session's classifier brief;
5. publish (a directory, or ``host:dir`` through ``scp``) whenever the local board's
   files differ from the last ones published, and only then record it.

Guards, because a wrong rebuild is worse than a stale one:

* an incomplete sweep (``listed: false``) never rebuilds;
* a saturated sweep (some search hit its cap) adds but never closes;
* closing more than ``max_close_fraction`` of a board of at least
  :data:`GUARD_MIN_LIVE` cards is refused unless ``force``: those closes are withheld
  (and named in ``refresh.json``), while additions and retitles still go through, so
  a refusal never freezes the board;
* a ``tasks.json``, ``board.json`` or ``refresh.json`` that exists but does not parse
  (or, for ``refresh.json``, holds a value of the wrong shape) raises rather than being
  read as empty, and a first run with no ``board.json`` raises rather than publishing
  default settings;
* an owner-edited ``kit.html`` (one that differs from the packaged template) is kept.

A board whose page keeps its state in a claude.ai Artifact cannot be republished from
here: the result says ``needs_republish: True`` and a session republishes it.

What it touches: GitHub through ``gather`` (read-only); files under ``WORK``; and, when
publishing, the destination directory or the remote host (``scp`` with the user's own
keys). It never calls a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openloops import board as _board
from openloops import obligations as _obligations
from openloops import tasks as _tasks

__all__ = [
    "DFLT_MAX_CLOSE_FRACTION",
    "GUARD_MIN_LIVE",
    "NEW_ITEMS_FILE",
    "PublishError",
    "STATE_FILE",
    "RefreshPlan",
    "dir_publisher",
    "is_remote_destination",
    "load_state",
    "merge_refresh",
    "pin_env_scope",
    "plan_refresh",
    "refresh_board",
    "remember_scope",
]

#: Where the items that got only the heuristic record are listed, for a classifier brief.
NEW_ITEMS_FILE = "new-items.json"
#: The gathered envelope of the last rebuild, which `board-build -c` reads for dates.
CANDIDATES_FILE = "candidates.json"
#: The refresh's own state: the gather scope, run specs/extras, where to publish, and
#: the hash of the ``tasks.json`` last published.
STATE_FILE = "refresh.json"
#: A rebuild may close at most this fraction of the live cards without ``force``...
DFLT_MAX_CLOSE_FRACTION = 0.5
#: ...once the board has at least this many cards (a small board may empty legitimately).
GUARD_MIN_LIVE = 10
#: What a kept record takes from the fresh sweep. Everything else is the earlier record.
REFRESHED_FIELDS = ("title", "url")
#: What ``refresh.json`` remembers between runs, and the default of each.
DFLT_SCOPE: dict[str, Any] = {
    "owners": None,
    "exclude_owners": [],
    "exclude_repos": None,
    "searches": list(_tasks.DFLT_SEARCHES),
    "review_prs": True,
    "run_specs": None,
    "run_extras": None,
    "publish_to": None,
}
#: Scope values that are local paths, saved absolute so the timer (another cwd) finds them.
_PATH_KEYS = ("run_specs", "run_extras")
#: The JSON shape each scope value in ``refresh.json`` must have (``None`` = may be null).
_STR_LIST_KEYS = ("owners", "exclude_owners", "exclude_repos")
_STR_KEYS = ("publish_to", "run_specs", "run_extras")


class PublishError(RuntimeError):
    """Publishing the rebuilt board failed. The local board is in place; the next run
    retries, because the published marker is recorded only after a success."""


@dataclass(frozen=True)
class RefreshPlan:
    """What a fresh sweep changes relative to the live board.

    ``withheld`` are ids missing from a saturated sweep, kept rather than closed;
    ``updated`` are kept ids whose title or url changed on GitHub.
    """

    kept: tuple[str, ...]
    added: tuple[str, ...]
    closed: tuple[str, ...]
    withheld: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.added or self.closed or self.updated)


def plan_refresh(current: Iterable[str], previous: Iterable[str]) -> RefreshPlan:
    """Diff the ids now open against the ids on the live board.

    >>> plan = plan_refresh(['a#1', 'a#2', 'a#4'], ['a#1', 'a#3'])
    >>> plan.kept, plan.added, plan.closed, plan.changed
    (('a#1',), ('a#2', 'a#4'), ('a#3',), True)
    >>> plan_refresh(['a#1'], ['a#1']).changed
    False
    """
    now, before = list(dict.fromkeys(current)), list(dict.fromkeys(previous))
    now_set, before_set = set(now), set(before)
    return RefreshPlan(
        kept=tuple(i for i in now if i in before_set),
        added=tuple(i for i in now if i not in before_set),
        closed=tuple(i for i in before if i not in now_set),
    )


def merge_refresh(
    live: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    saturated: Sequence[str] = (),
    withhold_closes: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], RefreshPlan]:
    """The rebuild's records, the new candidates, and the plan. No I/O.

    Every id still open keeps its earlier record (never re-classified), with
    :data:`REFRESHED_FIELDS` taken from the sweep; new ids get the heuristic record. A
    ``saturated`` sweep did not list everything, so an id it did not see is kept
    (``withheld``), never closed; ``withhold_closes`` does the same for a sweep whose
    closes were refused.

    >>> live = [{'id': 'a/b#1', 'title': 'Old', 'ask': 'ENRICHED'}, {'id': 'a/b#2'}]
    >>> seen = [{'id': 'a/b#1', 'title': 'New', 'url': 'https://github.com/a/b/issues/1'}]
    >>> records, fresh, plan = merge_refresh(live, seen)
    >>> [(r['id'], r['title'], r['ask']) for r in records], plan.closed, plan.updated
    ([('a/b#1', 'New', 'ENRICHED')], ('a/b#2',), ('a/b#1',))
    >>> records, _, plan = merge_refresh(live, seen, saturated=['label:manual-task'])
    >>> [r['id'] for r in records], plan.closed, plan.withheld
    (['a/b#1', 'a/b#2'], (), ('a/b#2',))
    """
    raw = plan_refresh((c["id"] for c in candidates), (t["id"] for t in live))
    earlier = {t["id"]: t for t in live}
    by_id = {c["id"]: c for c in candidates}

    kept, updated = [], []
    for i in raw.kept:
        fresh_fields = {k: by_id[i][k] for k in REFRESHED_FIELDS if by_id[i].get(k)}
        record = {**earlier[i], **fresh_fields}
        if record != earlier[i]:
            updated.append(i)
        kept.append(record)
    withhold = bool(saturated) or withhold_closes
    withheld = raw.closed if withhold else ()
    fresh = [dict(by_id[i]) for i in raw.added]
    records = kept + [dict(earlier[i]) for i in withheld] + _tasks.classify(fresh)
    plan = RefreshPlan(
        kept=raw.kept,
        added=raw.added,
        closed=() if withhold else raw.closed,
        withheld=tuple(withheld),
        updated=tuple(updated),
    )
    return records, fresh, plan


def _refusal(
    plan: RefreshPlan, n_live: int, max_close_fraction: float, *, remedy: str
) -> str | None:
    """Why closing this much of the board should not go ahead, if it should not."""
    if n_live >= GUARD_MIN_LIVE and len(plan.closed) > max_close_fraction * n_live:
        return (
            f"the sweep would close {len(plan.closed)} of {n_live} cards (more than "
            f"{max_close_fraction:.0%}); those closes were withheld (additions and "
            f"retitles still apply). If they are real, run `{remedy}`"
        )
    return None


# --------------------------------------------------------------------------------
# Files: missing is empty, corrupt is an error, writes are atomic.


def _read_json(path: Path, *, default: Any, kind: type) -> Any:
    """``default`` when ``path`` is missing; its content when it parses as ``kind``; else raise.

    A file that exists but cannot be read is never treated as empty: that would rebuild
    the board from nothing and drop every enrichment, silently.
    """
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(
            f"{path} exists but is not valid JSON ({exc}); fix or remove it, the "
            "refresh will not treat it as empty"
        ) from exc
    if not isinstance(data, kind):
        raise ValueError(
            f"{path} should hold a JSON {'object' if kind is dict else 'list'}, "
            f"found {type(data).__name__}"
        )
    return data


def _write_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` atomically (a temp file beside it, then ``os.replace``)."""
    _replace_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def _replace_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _live_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = _read_json(path, default=[], kind=list)
    bad = [
        t for t in tasks if not (isinstance(t, dict) and isinstance(t.get("id"), str))
    ]
    if bad:
        raise ValueError(
            f"{path} has {len(bad)} entries that are not task records with an 'id' "
            f"(first: {str(bad[0])[:80]})"
        )
    return tasks


def _board_settings(path: Path, settings: Mapping[str, Any] | None) -> dict[str, Any]:
    if not path.exists() and settings is None:
        raise ValueError(
            f"{path} not found: build the board once by hand (`ol board-gather`, "
            "`ol board-classify`, `ol board-build WORK/board ...`) so its settings are "
            "known; the refresh never builds or publishes a board with default settings"
        )
    config = {**_read_json(path, default={}, kind=dict), **(settings or {})}
    if not isinstance(config.get("store") or {}, Mapping):
        raise ValueError(
            f"{path}: 'store' should be an object, not {config['store']!r}"
        )
    return config


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _board_digest(board_dir: Path) -> str | None:
    """One hash over every published board file (``None`` before the first build).

    Every file counts, not only ``tasks.json``: a ``board.json`` or ``runs.json`` edit,
    an edited ``kit.html`` or a forced rebuild must reach the destination too.
    """
    if not (board_dir / "tasks.json").exists():
        return None
    h = hashlib.sha256()
    for name in sorted(_board.BOARD_FILES):
        h.update(f"{name}\0{_sha256(board_dir / name) or ''}\n".encode())
    return h.hexdigest()


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _check_state(path: Path, state: Mapping[str, Any]) -> None:
    """Raise a ``ValueError`` naming the first scope value of the wrong shape."""

    def wrong(key: str, expected: str) -> ValueError:
        return ValueError(
            f"{path}: {key!r} should be {expected}, found {state[key]!r}; fix it or "
            "remove the key (a flag given on the next run sets it again)"
        )

    for key in _STR_LIST_KEYS:
        if state.get(key) is not None and not _is_str_list(state[key]):
            raise wrong(key, "a list of strings (or null)")
    if "searches" in state and not _is_str_list(state["searches"]):
        raise wrong("searches", "a list of strings (or absent, for every search)")
    for key in _STR_KEYS:
        if state.get(key) is not None and not isinstance(state[key], str):
            raise wrong(key, "a string (or null)")
    if "review_prs" in state and not isinstance(state["review_prs"], bool):
        raise wrong("review_prs", "true or false")


def load_state(work_dir: str | Path) -> dict[str, Any]:
    """``WORK/refresh.json``: ``{}`` when missing, an error when it exists but is
    unreadable or holds a scope value of the wrong shape."""
    path = Path(work_dir).expanduser() / STATE_FILE
    state = _read_json(path, default={}, kind=dict)
    _check_state(path, state)
    return state


def _save_state(work: Path, state: Mapping[str, Any]) -> None:
    _write_json(work / STATE_FILE, dict(state))


def _normalise(key: str, value: Any) -> Any:
    if key in _PATH_KEYS:
        return str(Path(value).expanduser().resolve())
    if key == "publish_to" and not is_remote_destination(value):
        return str(Path(value).expanduser().resolve())
    if isinstance(value, (tuple, list)):
        return list(value)
    return value


def remember_scope(work_dir: str | Path, **given: Any) -> dict[str, Any]:
    """Save the ``given`` scope values (``None`` = not given) into ``WORK/refresh.json``.

    Returns the full scope: what was saved, then defaults. Both ``ol board-refresh``
    and ``ol install-refresh-job`` go through here, so the timer needs only ``WORK``.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     _ = remember_scope(tmp, owners=['me'])
    ...     scope = remember_scope(tmp, exclude_repos=None)
    >>> scope['owners'], scope['review_prs']
    (['me'], True)
    """
    unknown = set(given) - set(DFLT_SCOPE)
    if unknown:
        raise TypeError(f"not a refresh scope setting: {sorted(unknown)}")
    work = Path(work_dir).expanduser()
    state = load_state(work)
    updates = {k: _normalise(k, v) for k, v in given.items() if v is not None}
    if any(state.get(k) != v for k, v in updates.items()):
        state = {**state, **updates}
        _save_state(work, state)
    return {k: state.get(k, default) for k, default in DFLT_SCOPE.items()}


def _words(raw: str | None) -> list[str]:
    return [p for p in re.split(r"[,\s]+", raw or "") if p]


def pin_env_scope(
    work_dir: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    resolve_owners: Callable[[], Sequence[str]] | None = None,
) -> dict[str, list[str]]:
    """Save what the environment makes the sweep's scope into ``WORK/refresh.json``.

    A launchd timer does not get the shell's ``OPENLOOPS_OWNERS`` or
    ``OPENLOOPS_EXCLUDE_REPOS``, so a scope that lives only there would make the timer
    sweep a different set of repositories than a run by hand (and could put an excluded
    client repo on the board). Each is written as an explicit list, but only where
    ``refresh.json`` has no value yet (a flag given earlier, or an earlier pin, wins).
    With no ``OPENLOOPS_OWNERS``, ``resolve_owners`` (e.g.
    :func:`openloops.obligations.configured_owners`) supplies the default owners; when
    it is not given they stay unset here and the first sweep's resolved owners are
    pinned instead. Returns what was saved.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     env = {'OPENLOOPS_OWNERS': 'me, org', 'OPENLOOPS_EXCLUDE_REPOS': 'org/x-*'}
    ...     first = pin_env_scope(tmp, environ=env)
    ...     second = pin_env_scope(tmp, environ={'OPENLOOPS_OWNERS': 'other'})
    >>> first, second
    ({'owners': ['me', 'org'], 'exclude_repos': ['org/x-*']}, {})
    """
    environ = os.environ if environ is None else environ
    work = Path(work_dir).expanduser()
    state = load_state(work)
    pins: dict[str, list[str]] = {}
    if state.get("owners") is None:
        owners = _words(environ.get(_obligations.OWNERS_ENV_VAR))
        if not owners and resolve_owners is not None:
            owners = list(resolve_owners())
        if owners:
            pins["owners"] = owners
    if state.get("exclude_repos") is None:
        globs = _words(environ.get(_tasks.EXCLUDE_ENV_VAR))
        if globs:
            pins["exclude_repos"] = globs
    if pins:
        _save_state(work, {**state, **pins})
    return pins


# --------------------------------------------------------------------------------
# Publishing.


def is_remote_destination(destination: str) -> bool:
    """Whether ``destination`` names ``host:dir`` (for ``scp``) rather than a local path.

    Remote only when the text before the first colon is a plausible host (non-empty, no
    ``/`` or ``\\``, not a one-letter Windows drive such as ``C:``) and the whole thing
    is not an existing local path.

    >>> [is_remote_destination(d) for d in ('tw:/srv/board', 'me@host:board')]
    [True, True]
    >>> [is_remote_destination(d) for d in (r'C:\\Users\\x\\dest', '/tmp/a:b', 'board')]
    [False, False, False]
    """
    head, colon, _ = destination.partition(":")
    if not colon or not head or "/" in head or "\\" in head:
        return False
    if len(head) == 1 and head.isalpha():
        return False
    return not Path(destination).expanduser().exists()


def dir_publisher(destination: str, *, timeout: float = 300) -> Callable[[Path], None]:
    """A publisher that copies the board's files to ``destination``.

    ``destination`` is a directory, or ``host:dir`` (see
    :func:`is_remote_destination`), which goes through ``scp -o BatchMode=yes`` (never a
    password prompt that would hang a timer) with ``timeout`` seconds. A local copy
    replaces each file atomically; the remote copy does not (``scp`` writes in place),
    so a reader on the host can, for a moment, see a partly written file. A failure
    raises, so a timer's log says the board did not move.
    """

    def publish(board_dir: Path) -> None:
        files = [board_dir / name for name in _board.BOARD_FILES]
        if is_remote_destination(destination):
            subprocess.run(
                [
                    "scp",
                    "-q",
                    "-o",
                    "BatchMode=yes",
                    *map(str, files),
                    destination.rstrip("/") + "/",
                ],
                check=True,
                timeout=timeout,
            )
            return
        target = Path(destination).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        for file in files:
            fd, tmp = tempfile.mkstemp(dir=target, prefix=f".{file.name}.")
            os.close(fd)
            shutil.copyfile(file, tmp)
            os.replace(tmp, target / file.name)

    return publish


# --------------------------------------------------------------------------------
# The I/O shell.


def _install_board(built: Path, board_dir: Path) -> None:
    """Move a freshly built board into place, file by file, ``tasks.json`` last.

    ``kit.html`` is left alone when the live one differs from the packaged template:
    the owner edited it.
    """
    board_dir.mkdir(parents=True, exist_ok=True)
    kit = board_dir / "kit.html"
    packaged_kit = (_board.board_dir() / "kit.html").read_bytes()
    order = [n for n in _board.BOARD_FILES if n != "tasks.json"] + ["tasks.json"]
    for name in order:
        if name == "kit.html" and kit.exists() and kit.read_bytes() != packaged_kit:
            continue
        os.replace(built / name, board_dir / name)


def _record_refusal(work: Path, refused: Sequence[str]) -> None:
    """Name the withheld closes in ``refresh.json``, or clear them once none are refused."""
    state = load_state(work)
    if refused:
        update = {"refused_closes": len(refused), "refused_close_ids": list(refused)}
        if any(state.get(k) != v for k, v in update.items()):
            _save_state(work, {**state, **update})
    elif "refused_closes" in state or "refused_close_ids" in state:
        _save_state(
            work,
            {
                k: v
                for k, v in state.items()
                if k not in ("refused_closes", "refused_close_ids")
            },
        )


def _accumulated_new_items(
    previous: list[Any], fresh: list[dict[str, Any]], open_ids: set[str]
) -> list[dict[str, Any]]:
    """The previous list's items still open, then the fresh ones, once each by id."""
    merged: dict[str, dict[str, Any]] = {}
    for item in [*previous, *fresh]:
        if isinstance(item, dict) and item.get("id") in open_ids:
            merged[item["id"]] = {**merged.get(item["id"], {}), **item}
    return list(merged.values())


def refresh_board(
    work_dir: str | Path,
    *,
    owners: Sequence[str] | None = None,
    exclude_owners: Sequence[str] | None = None,
    exclude_repos: Sequence[str] | None = None,
    searches: Sequence[str] | None = None,
    review_prs: bool | None = None,
    run_specs: str | None = None,
    run_extras: str | None = None,
    publish_to: str | None = None,
    force: bool = False,
    max_close_fraction: float = DFLT_MAX_CLOSE_FRACTION,
    publish: Callable[[Path], None] | None = None,
    gather: Callable[..., Mapping[str, Any]] = _tasks.gather,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild ``WORK/board`` when the set of open items changed. Returns what happened.

    The scope keywords (``owners`` to ``publish_to``) are saved into
    ``WORK/refresh.json`` when given and read from it when not (:func:`remember_scope`);
    their defaults are every kind of item and PRs awaiting review, like
    ``board-gather --all-kinds``. ``run_specs``/``run_extras`` are passed to every
    rebuild, as ``board-build`` takes them. ``force`` rebuilds even when nothing
    changed and overrides the close guard (never the incomplete-sweep one). What the
    environment sets (``OPENLOOPS_OWNERS``, ``OPENLOOPS_EXCLUDE_REPOS``) and, failing
    that, the owners the sweep resolved, are pinned into ``refresh.json`` where it has no
    value yet (:func:`pin_env_scope`).
    ``publish`` replaces the publisher built from ``publish_to`` (see
    :func:`dir_publisher`); ``gather`` replaces the sweep; ``settings`` override the
    existing ``board.json`` (and are required when there is none).

    ``status`` is ``rebuilt``, ``unchanged``, ``incomplete``, ``partial`` (rebuilt with
    additions/retitles while a mass close was refused) or ``refused`` (a mass close was
    refused and nothing else changed). Refused closes are withheld, never dropped:
    ``refused_closes`` (a count) and ``refused_close_ids`` are returned and kept in
    ``refresh.json`` until a run no longer refuses, and ``remedy`` is the command that
    applies them. A publish failure raises :class:`PublishError` after the local rebuild
    is in place.

    >>> import tempfile
    >>> item = {'id': 'a/b#1', 'url': 'https://github.com/a/b/issues/1',
    ...         'repo': 'a/b', 'title': 'Add a key', 'src': 'label:manual-task'}
    >>> sweep = lambda **kw: {'listed': True, 'candidates': [item], 'error': None}
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     first = refresh_board(tmp, gather=sweep, settings={'title': 'Mine'})
    ...     again = refresh_board(tmp, gather=sweep)
    >>> first['rebuilt'], first['added'], again['status']
    (True, 1, 'unchanged')
    """
    work = Path(work_dir).expanduser()
    board_dir = work / "board"
    tasks_path = board_dir / "tasks.json"
    scope = remember_scope(
        work,
        owners=owners,
        exclude_owners=exclude_owners,
        exclude_repos=exclude_repos,
        searches=searches,
        review_prs=review_prs,
        run_specs=run_specs,
        run_extras=run_extras,
        publish_to=publish_to,
    )
    pinned = pin_env_scope(work)
    scope = {**scope, **pinned}
    live = _live_tasks(tasks_path)
    config = _board_settings(board_dir / "board.json", settings)
    store = config.get("store") or {}
    if publish is None and scope["publish_to"]:
        publish = dir_publisher(scope["publish_to"])
    destination = scope["publish_to"] if publish is not None else None

    report = gather(
        owners=scope["owners"],
        exclude_owners=scope["exclude_owners"] or (),
        exclude_repos=scope["exclude_repos"],
        searches=list(scope["searches"]),
        review_prs=scope["review_prs"],
    )
    saturated = list(report.get("saturated") or [])
    outcome: dict[str, Any] = {
        "rebuilt": False,
        "needs_republish": False,
        "saturated": saturated,
        "refused_closes": 0,
        "refused_close_ids": [],
    }
    if not report.get("listed"):
        outcome.update(
            status="incomplete",
            reason=f"the sweep was incomplete, board left as it was: {report.get('error')}",
        )
    else:
        if scope["owners"] is None and report.get("owners"):
            # The default owners (gh alias or login), resolved by the sweep: pinned so
            # the timer, which lacks the shell's environment, sweeps the same owners.
            _save_state(work, {**load_state(work), "owners": list(report["owners"])})
        candidates = list(report["candidates"])
        records, fresh, plan = merge_refresh(live, candidates, saturated=saturated)
        remedy = f"ol board-refresh {work} --force"
        refusal = (
            None
            if force
            else _refusal(plan, len(live), max_close_fraction, remedy=remedy)
        )
        refused: tuple[str, ...] = ()
        if refusal:
            refused = plan.closed
            records, fresh, plan = merge_refresh(
                live, candidates, saturated=saturated, withhold_closes=True
            )
        outcome.update(
            added=len(plan.added),
            closed=len(plan.closed),
            kept=len(plan.kept),
            withheld=0 if refused else len(plan.withheld),
            updated=len(plan.updated),
            refused_closes=len(refused),
            refused_close_ids=list(refused),
        )
        if refused:
            outcome.update(remedy=remedy)
        _record_refusal(work, refused)
        if not plan.changed and not force and tasks_path.exists():
            outcome.update(
                status="refused" if refused else "unchanged",
                reason=refusal or "no item opened, closed or retitled",
            )
        else:
            open_ids = {r["id"] for r in records}
            new_items = _accumulated_new_items(
                _read_json(work / NEW_ITEMS_FILE, default=[], kind=list),
                fresh,
                open_ids,
            )
            work.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=work, prefix=".board-") as tmp:
                built = _board.build_board(
                    records,
                    tmp,
                    candidates=candidates,
                    specs=_board.run_specs(scope["run_specs"])
                    if scope["run_specs"]
                    else None,
                    extras=_board.run_extras(scope["run_extras"]),
                    title=config.get("title") or _board.DFLT_TITLE,
                    session=config.get("session"),
                    read_only_orgs=config.get("read_only_orgs") or (),
                    machine=config.get("machine"),
                    store=store.get("kind", "artifact"),
                    api=store.get("api"),
                    moved_to=config.get("moved_to"),
                )
                _install_board(Path(tmp), board_dir)
            _write_json(work / CANDIDATES_FILE, dict(report))
            _write_json(work / NEW_ITEMS_FILE, new_items)
            outcome.update(
                status="partial" if refused else "rebuilt",
                rebuilt=True,
                tasks=built["tasks"],
                needs_enrichment=len(new_items),
                new_items=str(work / NEW_ITEMS_FILE),
                needs_republish=store.get("kind", "artifact") == "artifact",
            )
            if refusal:
                outcome["reason"] = refusal

    outcome["published"] = False
    digest = _board_digest(board_dir)
    state = load_state(work)
    unpublished = (
        state.get("last_published") != digest
        or state.get("last_published_to") != destination
    )
    if publish is not None and digest and unpublished:
        try:
            publish(board_dir)
        except Exception as exc:  # any publisher's failure, named as one
            raise PublishError(
                f"publishing {board_dir} to {destination or 'the publisher'} failed "
                f"(the local board is up to date; the next run retries): {exc}"
            ) from exc
        _save_state(
            work,
            {**state, "last_published": digest, "last_published_to": destination},
        )
        outcome["published"] = True
    return outcome
