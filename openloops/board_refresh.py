"""Keep the phone board within a day of GitHub, without a session remembering to.

The board (:mod:`openloops.board`) is rebuilt by hand: gather, classify, build. Left
alone it goes stale (a board built 2026-10-27 was still that build on 2026-11-09, with
210 of its 420 cards closed and 222 new items missing). :func:`refresh_board` is that
rebuild as one deterministic, model-free step meant to run from a timer (``ol
install-refresh-job``) or by hand (``ol board-refresh WORK``):

1. gather the open items (:func:`openloops.tasks.gather`);
2. diff their ids against the live ``WORK/board/tasks.json``;
3. if nothing was opened or closed, stop (``rebuilt: False``);
4. otherwise rebuild, **reusing the earlier record of every id still open** (so what a
   classifier brief or the owner's review added survives) and giving each new id the
   free heuristic record; the new ones are listed in ``WORK/new-items.json`` for a
   session to enrich with the classifier brief when it next looks;
5. optionally publish the five files (a directory or ``host:dir``).

An incomplete sweep (``listed: false``) never rebuilds: a board built from half the
items would silently drop the rest. The board's own settings (title, session,
read-only organisations, machine, store) are read from the existing
``board.json``, so the timer needs to be told nothing the board already knows.

Nothing here reaches GitHub except through ``gather``, writes anything outside
``WORK``, or calls a model.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openloops import board as _board
from openloops import tasks as _tasks

__all__ = [
    "NEW_ITEMS_FILE",
    "RefreshPlan",
    "dir_publisher",
    "plan_refresh",
    "refresh_board",
]

#: Where the items that got only the heuristic record are listed, for a classifier brief.
NEW_ITEMS_FILE = "new-items.json"
#: The gathered envelope of the last rebuild, which `board-build -c` reads for dates.
CANDIDATES_FILE = "candidates.json"


@dataclass(frozen=True)
class RefreshPlan:
    """What a fresh sweep changes relative to the live board."""

    kept: tuple[str, ...]
    added: tuple[str, ...]
    closed: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.closed)


def plan_refresh(current: Iterable[str], previous: Iterable[str]) -> RefreshPlan:
    """Diff the ids now open against the ids on the live board.

    >>> plan = plan_refresh(['a#1', 'a#2', 'a#4'], ['a#1', 'a#3'])
    >>> plan.kept, plan.added, plan.closed, plan.changed
    (('a#1',), ('a#2', 'a#4'), ('a#3',), True)
    >>> plan_refresh(['a#1'], ['a#1']).changed
    False
    """
    now, before = list(dict.fromkeys(current)), list(dict.fromkeys(previous))
    return RefreshPlan(
        kept=tuple(i for i in now if i in set(before)),
        added=tuple(i for i in now if i not in set(before)),
        closed=tuple(i for i in before if i not in set(now)),
    )


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def dir_publisher(destination: str) -> Callable[[Path], None]:
    """A publisher that copies the board's files to ``destination``.

    ``destination`` is a directory, or ``host:dir`` (anything with a colon that is not
    an existing local path), which goes through ``scp``. A failure raises, so a timer's
    log says the board did not move.
    """

    def publish(board_dir: Path) -> None:
        files = [board_dir / name for name in _board.BOARD_FILES]
        if ":" in destination and not Path(destination).expanduser().exists():
            subprocess.run(
                ["scp", "-q", *map(str, files), destination.rstrip("/") + "/"],
                check=True,
                timeout=300,
            )
            return
        target = Path(destination).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        for file in files:
            shutil.copyfile(file, target / file.name)

    return publish


def refresh_board(
    work_dir: str | Path,
    *,
    owners: Sequence[str] | None = None,
    exclude_owners: Sequence[str] = (),
    exclude_repos: Sequence[str] | None = None,
    searches: Sequence[str] | None = None,
    review_prs: bool = True,
    force: bool = False,
    publish: Callable[[Path], None] | None = None,
    gather: Callable[..., Mapping[str, Any]] = _tasks.gather,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild ``WORK/board`` when the set of open items changed. Returns what happened.

    ``searches`` defaults to every kind (the label, ``decide``, ``needs-user``,
    ``agent-decided``) and ``review_prs`` to on, matching ``board-gather --all-kinds``.
    ``force`` rebuilds even when the ids are unchanged. ``publish`` is called with the
    board directory after a rebuild (see :func:`dir_publisher`); ``gather`` replaces
    the sweep; ``settings`` override what the existing ``board.json`` holds.

    >>> import tempfile
    >>> item = {'id': 'a/b#1', 'url': 'https://github.com/a/b/issues/1',
    ...         'repo': 'a/b', 'title': 'Add a key', 'src': 'label:manual-task'}
    >>> sweep = lambda **kw: {'listed': True, 'candidates': [item], 'error': None}
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     first = refresh_board(tmp, gather=sweep)
    ...     again = refresh_board(tmp, gather=sweep)
    >>> first['rebuilt'], first['added'], again['rebuilt']
    (True, 1, False)
    """
    work = Path(work_dir).expanduser()
    board_dir = work / "board"
    live = _read_json(board_dir / "tasks.json", [])
    config = {**_read_json(board_dir / "board.json", {}), **(settings or {})}
    report = gather(
        owners=owners,
        exclude_owners=exclude_owners,
        exclude_repos=exclude_repos,
        searches=list(_tasks.DFLT_SEARCHES) if searches is None else list(searches),
        review_prs=review_prs,
    )
    if not report.get("listed"):
        return {
            "rebuilt": False,
            "reason": f"the sweep was incomplete, board left as it was: {report.get('error')}",
        }
    candidates = list(report["candidates"])
    plan = plan_refresh((c["id"] for c in candidates), (t["id"] for t in live))
    if not plan.changed and not force and live:
        return {
            "rebuilt": False,
            "reason": "no item opened or closed",
            "kept": len(plan.kept),
        }

    by_id = {c["id"]: c for c in candidates}
    earlier = {t["id"]: t for t in live}
    fresh = [by_id[i] for i in plan.added]
    records = [earlier[i] for i in plan.kept if i in earlier] + _tasks.classify(fresh)
    store = config.get("store") or {}
    work.mkdir(parents=True, exist_ok=True)
    _write_json(work / CANDIDATES_FILE, dict(report))
    _write_json(work / NEW_ITEMS_FILE, fresh)
    built = _board.build_board(
        records,
        board_dir,
        candidates=candidates,
        title=config.get("title") or _board.DFLT_TITLE,
        session=config.get("session"),
        read_only_orgs=config.get("read_only_orgs") or (),
        machine=config.get("machine"),
        store=store.get("kind", "artifact")
        if isinstance(store, Mapping)
        else "artifact",
        api=store.get("api") if isinstance(store, Mapping) else None,
        moved_to=config.get("moved_to"),
    )
    if publish is not None:
        publish(board_dir)
    return {
        "rebuilt": True,
        "published": publish is not None,
        "tasks": built["tasks"],
        "added": len(plan.added),
        "closed": len(plan.closed),
        "kept": len(plan.kept),
        "needs_enrichment": len(fresh),
        "saturated": list(report.get("saturated") or []),
        "new_items": str(work / NEW_ITEMS_FILE),
    }
