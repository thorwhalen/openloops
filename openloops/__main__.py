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
