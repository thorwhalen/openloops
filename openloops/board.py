"""The phone task board: task records in, a static page and its data files out.

:func:`build_board` writes five files into a directory the caller names:

=============  ==================================================================
``tasks.json`` every record, sorted cheapest-first (tier, then minutes per thing
               it unblocks), with ``created`` joined from the gathered candidates
``runs.json``  repeated chores grouped into runs, one per pattern, from the run
               specs (data, not code: :func:`run_specs`)
``board.json`` the deployment settings the page reads: title, the session that
               receives the board's events, organisations it must never comment
               in, the default machine for a run's prompt
``index.html`` the page, shipped as package data (``openloops/data/board/``)
``kit.html``   the page's "Phone kit" tab
=============  ==================================================================

The page is meant to be published as a claude.ai Artifact with a ``db`` capability.
Its persistence model (immutable ``outbox/<eventId>`` events written by the page,
``receipts/<eventId>`` written only by the receiving session) is documented at the
top of its ``<script>``.

**What openloops does not do** (ADR-008): post the comments, close the issues or
dispatch the workers that the board's events ask for. That write side is a
procedure a Claude session follows, shipped as the ``openloops-phone-board`` skill.
This module writes files into ``out_dir`` and nothing else, and it never puts the
data anywhere near the repository: where the board lives is the caller's choice.

    >>> tasks = [
    ...     {'id': 'a/x#1', 'tier': 'browser', 'pattern': 'api-key', 'minutes': 3},
    ...     {'id': 'a/y#2', 'tier': 'browser', 'pattern': 'api-key', 'minutes': 5},
    ...     {'id': 'a/z#3', 'tier': 'tap', 'pattern': 'other', 'status': 'likely-done'},
    ... ]
    >>> [(r['key'], r['ids']) for r in group_runs(tasks)]
    [('cleanup', ['a/z#3']), ('api-key', ['a/x#1', 'a/y#2'])]
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from openloops.tasks import TIERS, Task

__all__ = [
    "BOARD_FILES",
    "DFLT_TITLE",
    "board_dir",
    "build_board",
    "group_runs",
    "join_created",
    "run_specs",
    "sort_tasks",
]

DFLT_TITLE = "Phone Task Board"
#: Statuses that put an item in the clean-up run rather than in its pattern's run.
CLEANUP_STATUSES = ("likely-done", "stale")
CLEANUP_KEY = "cleanup"
#: A run of one is not a run. A spec's ``min_items`` overrides this.
DFLT_MIN_ITEMS = 2
#: Assumed minutes for a record with none, when averaging a run.
DFLT_MINUTES = 5
#: The page's own files, copied from the package as they are.
TEMPLATE_FILES = ("index.html", "kit.html")
BOARD_FILES = ("tasks.json", "runs.json", "board.json", *TEMPLATE_FILES)

_TIER_RANK = {tier: rank for rank, tier in enumerate(TIERS)}


def board_dir() -> Path:
    """Where the page template and the default run specs ship, inside the package."""
    return Path(__file__).parent / "data" / "board"


def run_specs(path: str | Path | None = None) -> list[dict[str, Any]]:
    """The run specs: one per pattern, in display order. Packaged ones by default.

    Each spec is ``{key, title, why, steps, tier?, min_items?, prompt?, machine?}``;
    ``key`` is a pattern from :data:`openloops.tasks.PATTERNS`, or ``cleanup``.

    >>> run_specs()[0]['key']
    'cleanup'
    """
    source = Path(path) if path else board_dir() / "runs.json"
    return json.loads(source.read_text(encoding="utf-8"))


def sort_tasks(tasks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Cheapest first: by tier, then by minutes per thing the item unblocks.

    >>> [t['id'] for t in sort_tasks([{'id': 'b', 'tier': 'session'}, {'id': 'a', 'tier': 'tap'}])]
    ['a', 'b']
    """

    def cost(task):
        minutes = task.get("minutes") or 10
        return (
            _TIER_RANK.get(task.get("tier"), len(TIERS)),
            minutes / (1 + len(task.get("unblocks") or [])),
        )

    return sorted((dict(t) for t in tasks), key=cost)


def join_created(
    tasks: Iterable[Mapping[str, Any]], candidates: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fill each record's missing ``created`` from the gathered candidate with its URL.

    >>> join_created([{'url': 'u', 'created': None}], [{'url': 'u', 'created': '2026-01-02'}])
    [{'url': 'u', 'created': '2026-01-02'}]
    """
    created = {c.get("url"): c.get("created") for c in candidates}
    return [
        {**t, "created": t.get("created") or created.get(t.get("url"))} for t in tasks
    ]


def group_runs(
    tasks: Iterable[Mapping[str, Any]],
    *,
    specs: Sequence[Mapping[str, Any]] | None = None,
    extras: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Repeated chores grouped into runs, ordered as the specs are.

    Open items go to their pattern's run (a ``mac-only`` tier goes to ``mac-only``);
    ``likely-done`` and ``stale`` items go to ``cleanup``. A pattern with no spec, or
    with fewer items than its ``min_items``, has no run.

    ``extras`` overlays a run by key, for what only this deployment knows (a prompt, a
    package table, a better title). Its ``absorb`` names other runs whose items move
    into this one, and those runs disappear: two chores done in one session run.
    """
    specs = run_specs() if specs is None else specs
    extras = extras or {}
    by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for task in tasks:
        status = task.get("status") or "open"
        if status in CLEANUP_STATUSES:
            by_key[CLEANUP_KEY].append(task)
        elif status == "open":
            by_key[
                "mac-only"
                if task.get("tier") == "mac-only"
                else task.get("pattern") or "other"
            ].append(task)

    runs = []
    for spec in specs:
        items = sorted(
            by_key.get(spec["key"], []),
            key=lambda t: (t.get("pattern_key") or "", t["id"]),
        )
        if len(items) < spec.get("min_items", DFLT_MIN_ITEMS):
            continue
        tiers = [t.get("tier") for t in items]
        runs.append(
            {
                "key": spec["key"],
                "title": spec["title"],
                "why": spec.get("why"),
                "steps": list(spec.get("steps") or []),
                "tier": spec.get("tier") or max(dict.fromkeys(tiers), key=tiers.count),
                "minutes_each": round(
                    sum(t.get("minutes") or DFLT_MINUTES for t in items) / len(items)
                ),
                "ids": [t["id"] for t in items],
                **({"prompt": spec["prompt"]} if spec.get("prompt") else {}),
                **({"machine": spec["machine"]} if spec.get("machine") else {}),
            }
        )

    absorbed = set()
    for run in runs:
        extra = dict(extras.get(run["key"]) or {})
        for other in extra.pop("absorb", ()):
            for donor in runs:
                if donor["key"] == other and donor is not run:
                    run["ids"] += donor["ids"]
                    absorbed.add(other)
        run.update(extra)
    return [r for r in runs if r["key"] not in absorbed]


def build_board(
    records: Iterable[Mapping[str, Any]],
    out_dir: str | Path,
    *,
    candidates: Iterable[Mapping[str, Any]] = (),
    specs: Sequence[Mapping[str, Any]] | None = None,
    extras: Mapping[str, Mapping[str, Any]] | None = None,
    title: str = DFLT_TITLE,
    session: str | None = None,
    read_only_orgs: Sequence[str] = (),
    machine: str | None = None,
) -> dict[str, Any]:
    """Write the board's five files into ``out_dir`` and say what went in.

    ``session`` is the name of the Claude session that receives the board's events (the
    page names it in the prompts it copies); ``read_only_orgs`` are organisations whose
    items the page never offers to close or comment on; ``machine`` is the default
    machine named by a run's "have an agent start this run".
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tasks = sort_tasks(
        join_created([Task.from_mapping(r).as_dict() for r in records], candidates)
    )
    runs = group_runs(tasks, specs=specs, extras=extras)
    config = {
        "title": title,
        "session": session,
        "read_only_orgs": list(read_only_orgs),
        "machine": machine,
    }

    def dump(name, data):
        (out / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    dump("tasks.json", tasks)
    dump("runs.json", runs)
    dump("board.json", config)
    for name in TEMPLATE_FILES:
        shutil.copyfile(board_dir() / name, out / name)

    counts: dict[str, dict[str, int]] = {"tier": {}, "status": {}}
    for task in tasks:
        for axis in counts:
            counts[axis][task[axis]] = counts[axis].get(task[axis], 0) + 1
    return {
        "out_dir": str(out),
        "files": [str(out / name) for name in BOARD_FILES],
        "tasks": len(tasks),
        "runs": [{"key": r["key"], "items": len(r["ids"])} for r in runs],
        "counts": counts,
    }
