"""The ``ol`` command: the one surface v0.1.0 builds.

Every verb here is a thin renderer over a function in :mod:`openloops.tools`, which is
the single list all surfaces dispatch from. The core prints nothing and exits nothing;
that discipline is what keeps a later MCP or HTTP adapter from needing the core to
change, and it is why the formatting lives here rather than there.

Bare ``ol`` syncs and then shows the open loops, because a tool whose read path is not
reached daily is a tool that failed — the fewest possible keystrokes have to produce
the useful thing.
"""

# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import sys
from datetime import datetime, timezone

from openloops import job as _job
from openloops import tools
from openloops.blockers import DFLT_CANDIDATE_LIMIT, UNBLOCKED, UNKNOWN

__all__ = ["main"]

#: What bare ``ol`` runs.
DEFAULT_COMMAND = "brief"


def _age(epoch: float | None) -> str:
    if not epoch:
        return "never"
    seconds = max(0.0, datetime.now(timezone.utc).timestamp() - epoch)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds / size:.0f}{unit} ago"
    return f"{seconds:.0f}s ago"


def _rows_table(rows: list[dict]) -> str:
    if not rows:
        return "(no digests)"
    lines = []
    for row in rows:
        when = (row.get("last_turn") or "")[:16].replace("T", " ")
        session = (row.get("session") or "")[:8]
        where = row.get("project") or row.get("source") or ""
        title = row.get("ai_title") or row.get("title") or ""
        mark = " " if row.get("confidence", "high") == "high" else "?"
        lines.append(f"{when:<17}{mark} {session:<10}{where:<22}{title}")
    return "\n".join(lines)


#: argh infers an argparse ``type=`` from the *default value*, not the annotation, so a
#: numeric option defaulting to ``None`` is handed through as a string and blows up deep
#: inside the reader. A negative sentinel gives argh a float to key on and means "all".
ALL_HISTORY = -1.0


def sync(
    *,
    source: str = None,
    since_days: float = ALL_HISTORY,
    force: bool = False,
):
    """Read what changed in your sessions and write the digests.

    `--since-days` bounds the scan to transcripts modified that recently; the default
    reads all of them.
    """
    from openloops._sync import sync_report_lines

    result = tools.sync(
        source=source,
        since_days=None if since_days is None or since_days < 0 else since_days,
        force=force,
    )
    report = "\n".join(sync_report_lines(result))
    if result["errors"]:
        print(report, file=sys.stderr)
        sys.exit(1)
    return report


def ls(
    *,
    state: str = "open",
    source: str = None,
    project: str = None,
    confidence: str = None,
    limit: int = 20,
):
    """List digests, newest last-turn first. State is open, archive or all.

    `--confidence high` drops the ones that are open only because nothing in them said
    they were finished.
    """
    return _rows_table(
        tools.ls(
            state=state,
            source=source,
            project=project,
            confidence=confidence,
            limit=limit,
        )
    )


def show(session: str, *, source: str = None):
    """Print one digest in full, by session id or a unique prefix of one.

    `--source` narrows a store several machines write into.
    """
    return tools.show(session, source=source)["text"]


def status():
    """Where the digests are, how many there are, and how stale the cache is."""
    info = tools.status()
    counts = info["digests"]
    return "\n".join(
        [
            f"source        {info['source']}",
            f"digests       {counts.get('open', 0)} open, {counts.get('archive', 0)} archive",
            f"sessions      {info['sessions_on_disk']} transcripts on disk",
            f"retained      {info['retained']} digests whose transcript is gone",
            f"digest store  {info['data_dir']}/digests",
            f"cache         {info['cache_file']} ({_age(info['cache_mtime'])})",
        ]
    )


def brief(*, limit: int = 20):
    """Sync, then show what your sessions left open. This is what bare `ol` runs.

    A `?` in the second column marks a session that is open only because nothing in it
    said it was finished.
    """
    from openloops._sync import sync_report_lines

    result = tools.sync()
    rows = tools.ls(state="open", limit=limit)
    lines = sync_report_lines(result)
    if result["errors"]:
        # The answer goes to stdout regardless. A session that cannot be digested is
        # worth shouting about, but it must not silence the other hundred and sixty —
        # a read command that prints nothing at all is the worse failure.
        print("\n".join(lines[1:]), file=sys.stderr)
        lines = lines[:1]
    return "\n".join([_rows_table(rows), "", *lines])


#: How the three states print. ASCII on purpose: this goes to a Windows console too,
#: and a surface that raises `UnicodeEncodeError` instead of answering is no surface.
_STATE_MARKS = {"open": "open", "discharged": "done", "unknown": "?"}


def _owed_report(report: dict) -> str:
    """Render :func:`openloops.tools.owed`. Every verdict prints its own predicate."""
    if not report["listed"]:
        # ADR-013's rule, and the only line in this file that really matters: a surface
        # that says `0` because it could not check is worse than no surface at all.
        return f"owed ?  could not check - {report['error']}"

    counts = report["counts"]
    headline = (
        f"{counts['open']} open, {counts['discharged']} discharged, "
        f"{counts['unknown']} unknown"
    )
    notes = [f"owners: {', '.join(report['owners']) or '(none)'}"]
    notes.append(f"predicates: {counts['with_predicate']} of {counts['total']}")
    if not report["checked"]:
        notes.append("NOT evaluated (--no-verify): every predicate row reads ?")
    if report["truncated"]:
        notes.append("TRUNCATED: the result set hit its cap, so this count is a floor")
    lines = [headline, "  " + "  |  ".join(notes), ""]

    for row in report["rows"]:
        mark = _STATE_MARKS.get(row["state"], row["state"])
        where = f"{row['repo']}#{row['number']}"
        lines.append(f"{mark:<5}{row['age_days']:>4}d  {where:<26} {row['title']}")
        # The predicate is never abbreviated. It is the reason to believe the verdict,
        # and a truncated one is something you cannot check for yourself.
        lines.append(f"          verify: {row['predicate'] or '(none)'}")
        if row["evidence"]:
            lines.append(f"                  -> {row['evidence']}")
    if not report["rows"]:
        lines.append("(nothing owed)")
    return "\n".join(lines)


def owed(*, limit: int = 50, no_verify: bool = False, owners: str = None):
    """What you still owe your agents, re-checked before it is shown.

    Lists the open `manual-task` issues and runs the `**Verify:**` predicate each one
    carries. `done` means the predicate returned 0 — the ask is finished and the issue
    is merely still open; nothing here ever closes it for you. `?` means nothing could
    be checked, which is never the same as nothing being owed.

    Running a predicate executes a command out of an issue body, so it happens only for
    the owners you configured. `--no-verify` lists without executing anything.
    """
    return _owed_report(
        tools.owed(
            verify=not no_verify,
            limit=limit,
            owners=[o for o in (owners or "").replace(",", " ").split()] or None,
        )
    )


#: How the cross-repo states print. ASCII again, and the words are the actions: a
#: `ready` row is work you can start now, a `waits` row is work you cannot.
_BLOCKED_MARKS = {"unblocked": "ready", "blocked": "waits", "unknown": "?"}


def _blocked_report(report: dict) -> str:
    """Render :func:`openloops.tools.blocked`. Every verdict prints its own edges."""
    if not report["listed"]:
        # Same rule as `owed`, for the same reason: a clean board that was never read
        # is worse than no board at all.
        return f"blocked ?  could not check - {report['error']}"

    counts = report["counts"]
    headline = (
        f"{counts['unblocked']} unblocked, {counts['blocked']} blocked, "
        f"{counts['unknown']} unknown"
    )
    scope = ", ".join(report["repos"] or report["owners"]) or "(none)"
    notes = [f"scope: {scope}", f"candidates: {counts['candidates']}"]
    if counts["without_edges"]:
        # Search over-reports; saying by how much is what keeps discovery honest.
        notes.append(f"{counts['without_edges']} had no dependency edge at all")
    if not report["resolved"]:
        notes.append("NOT resolved (--no-resolve): every row reads ?")
    if report["truncated"]:
        notes.append("TRUNCATED: the candidate list hit its cap, so this is a floor")
    lines = [headline, "  " + "  |  ".join(notes), ""]

    for row in report["rows"]:
        mark = _BLOCKED_MARKS.get(row["state"], row["state"])
        where = f"{row['repo']}#{row['number']}"
        lines.append(f"{mark:<6}{row['age_days']:>4}d  {where:<28} {row['title']}")
        # The edges are never abbreviated. They are the reason to believe the verdict,
        # and the foreign repository they name is the answer to "waiting on whom".
        refs = " ".join(blocker["ref"] for blocker in row["blockers"])
        lines.append(f"        blocked by: {refs or '(unresolved)'}")
        if row["state"] == UNBLOCKED:
            # The number nobody currently has: how long the work has been free.
            lines.append(
                f"                    -> free for {row['unblocked_days']}d, "
                "and nothing has said so"
            )
        elif row["state"] == UNKNOWN and row["evidence"]:
            # Why it could not be read. For a `waits` row the line above already
            # carries every blocker and its state, and repeating it is noise.
            lines.append(f"                    -> {row['evidence']}")
    if not report["rows"]:
        lines.append("(nothing is waiting on another repo)")
    return "\n".join(lines)


def blocked(
    *,
    limit: int = DFLT_CANDIDATE_LIMIT,
    no_resolve: bool = False,
    owners: str = None,
    repos: str = None,
):
    """What your repos are waiting on, and what stopped waiting without telling anyone.

    The sibling of `ol owed`: that one points at you, this one points at another repo.
    Lists the open issues carrying a `blocked_by` dependency and resolves every edge.
    `ready` means every blocker is closed — the work is free and nobody was told, which
    is the row worth reading. `waits` names the foreign repo it is still waiting on.
    `?` means nothing could be resolved, which is never the same as nothing waiting.

    Resolving costs one API call per candidate, so `--limit` bounds it and a saturated
    list says so. `--repos owner/name,owner/other` enumerates those repos exactly
    instead of trusting the search index. `--no-resolve` spends nothing and reads `?`.
    """
    return _blocked_report(
        tools.blocked(
            resolve=not no_resolve,
            limit=limit,
            owners=[o for o in (owners or "").replace(",", " ").split()] or None,
            repos=[r for r in (repos or "").replace(",", " ").split()],
        )
    )


def install_job(*, interval: int = _job.DFLT_INTERVAL, dry_run: bool = False):
    """Install the periodic sync job (macOS launchd). Re-run to change the interval."""
    result = _job.install(interval=interval, dry_run=dry_run)
    if dry_run:
        return result["xml"]
    return f"installed {_job.DFLT_LABEL} every {result['interval']}s\n  plist: {result['plist']}\n  log:   {result['log']}"


def uninstall_job():
    """Unload and remove the periodic sync job."""
    result = _job.uninstall()
    removed = result["removed"] == "true"
    return f"{'removed' if removed else 'nothing to remove at'} {result['plist']}"


def job_status():
    """Is the periodic job installed, loaded, and has it actually written anything?"""
    info = _job.job_status()
    return "\n".join(
        [
            f"label      {info['label']}",
            f"platform   {'supported' if info['platform_supported'] else 'NOT macOS — see `ol install-job` for the cron form'}",
            f"plist      {info['plist']} ({'present' if info['installed'] else 'ABSENT'})",
            f"loaded     {info['loaded']}",
            f"last write {_age(info['last_write'])}",
            f"log        {info['log']}",
        ]
    )


#: Every verb the CLI exposes, in the order `ol --help` lists them.
_commands = [
    brief,
    owed,
    blocked,
    sync,
    ls,
    show,
    status,
    install_job,
    uninstall_job,
    job_status,
]


def main(argv: list[str] | None = None) -> None:
    """Dispatch the ``ol`` command. Bare ``ol`` runs :func:`brief`."""
    import argh

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = [DEFAULT_COMMAND]
    parser = argh.ArghParser(prog="ol", description=__doc__.splitlines()[0])
    parser.add_commands(_commands)
    try:
        import argcomplete

        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    try:
        # `output_file` defaults to the `sys.stdout` argh captured at import time, which
        # is the wrong stream under any harness that replaces it. Pass the live one.
        parser.dispatch(argv=argv, output_file=sys.stdout)
    except (ValueError, KeyError) as exc:
        # A mistyped state or an unknown session id is ordinary user error. A traceback
        # is not an error message, and it prints this machine's install paths besides.
        message = exc.args[0] if exc.args else str(exc)
        print(f"ol: {message}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
