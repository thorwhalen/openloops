"""The periodic job: launchd runs ``ol sync``, writes, and exits. No daemon.

ADR-003's decision, applied to digests. A resident process would have to be kept alive,
and when it dies its output latches at whatever it last wrote — a confident, months-old
answer with nothing scheduled to correct it. A ``StartInterval`` job is self-healing by
construction: a tick that crashes is repaired by the next one, and the only thing to
supervise is launchd itself.

The environment is captured at install time and pinned into the plist, because launchd
hands a job a nearly empty environment. The interpreter is invoked directly rather than
by console-script name, for the same reason: a name resolved against a minimal ``PATH``
is a lottery whose losing ticket is a job that dies instantly, every tick, silently.

macOS only. On Linux the equivalent is a systemd user timer or a crontab line running
the same command, and :func:`install` says so rather than pretending.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from openloops.store import state_dir, sync_state_path

__all__ = [
    "DFLT_LABEL",
    "DFLT_INTERVAL",
    "REFRESH_INTERVAL",
    "REFRESH_LABEL",
    "RECEIVER_LABEL",
    "RECEIVER_INTERVAL",
    "REMIND_LABEL",
    "REMIND_INTERVAL",
    "install",
    "install_remind",
    "remind_job_spec",
    "install_receiver",
    "receiver_job_spec",
    "uninstall",
    "job_status",
    "plist_xml",
]

#: launchd job label. Also the plist filename and the log filename.
DFLT_LABEL = "openloops.sync"

#: Seconds between ticks. A digest is a record of what a session said, so being a
#: quarter of an hour behind costs nothing; running every few seconds would cost a
#: full scan of the transcript directory for no gain.
DFLT_INTERVAL = 900

#: Environment variables that configure openloops and must survive into the job — a
#: shell that overrode where digests go would otherwise find the job writing elsewhere.
PASSED_THROUGH = (
    "OPENLOOPS_DATA_DIR",
    "OPENLOOPS_STATE_DIR",
    "OPENLOOPS_SOURCE",
    "CLAUDE_PROJECTS_DIR",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "OPENLOOPS_TZ",
    "OPENLOOPS_REMIND_CHANNEL",
    "OPENLOOPS_REMIND_HORIZON_HOURS",
    "OPENLOOPS_PILE_REPO",
    "NTFY_TOPIC",
    "CORRESPOND_CONFIG",
    "XDG_CONFIG_HOME",
)


#: launchd label of the board-receiver job (ADR-011).
RECEIVER_LABEL = "openloops.board-receiver"

#: Seconds between receiver ticks. A tick that finds nothing pending costs a few HTTP
#: calls and no model, so this can be as short as the phone board's latency wants.
RECEIVER_INTERVAL = 300
#: The board-rebuild job (`ol board-refresh` on a timer; issue #39): no model, so it can
#: run often; six hours keeps the board within a day of GitHub with margin.
REMIND_LABEL = "openloops.remind-tick"
#: Hourly: a reminder is armed on the channel up to three days ahead, so the tick only
#: needs to catch loops entering that horizon and record the ones that fired.
REMIND_INTERVAL = 3600
PILE_NUDGE_LABEL = "openloops.pile-nudge"
#: Every six hours: the nudge is idempotent, and a pending one is never duplicated.
PILE_NUDGE_INTERVAL = 21600
REFRESH_LABEL = "openloops.board-refresh"
REFRESH_INTERVAL = 21600

#: Tools the unattended receiver session may use without asking. Bash is limited to the
#: commands the receiver procedure runs (`gh`, `curl`, `python3`, the worker dispatch,
#: and the shell steps of the sign-in); everything else is refused, not asked about.
#: `python3` is still arbitrary code, so the real guard is the prompt's rule that
#: GitHub and store text is data. Widen with `ol install-receiver-job --allowed-tools`.
RECEIVER_TOOLS = " ".join(
    [
        *(
            f"Bash({cmd}:*)"
            for cmd in (
                "gh",
                "curl",
                "python3",
                "crowsnest",
                "mkdir",
                "date",
                "set",
                "umask",
                "source",
                "jq",
                "cat",
                "ls",
                "shasum",
                "vm_stat",
                "sysctl",
            )
        ),
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Skill",
    ]
)

#: Commands the receiver session runs (receiver.md): `node` runs `claude`, `crowsnest`
#: dispatches the follow-up worker, `gh`/`jq` reach GitHub. launchd's PATH finds none of
#: them unless their folder is pinned; a missing `crowsnest` leaves every answer `queued`.
RECEIVER_COMMANDS = ("node", "gh", "jq", "crowsnest")

#: Environment variables the receiver session reads, passed through like the others.
RECEIVER_PASSED_THROUGH = (
    "OPENLOOPS_OWNERS",
    "OPENLOOPS_READ_ONLY_ORGS",
    "OPENLOOPS_EXCLUDE_REPOS",
)

#: Where the receiver's credentials live (receiver-http.md). Read by the job, never
#: written into the plist.
RECEIVER_ENV_FILE = Path("~/.config/openloops/board-receiver.env")


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plist_xml(
    *,
    label: str,
    program_args: list[str],
    env: dict[str, str],
    interval: int,
    log_path: Path,
    working_dir: str | Path | None = None,
) -> str:
    """The launchd property list, as text. Pure, so it can be tested on any platform.

    >>> xml = plist_xml(label='x', program_args=['a'], env={'HOME': '/h'},
    ...                 interval=60, log_path=Path('/tmp/x.log'))
    >>> '<key>StartInterval</key>' in xml and '<integer>60</integer>' in xml
    True
    """
    args = "\n".join(f"        <string>{_esc(a)}</string>" for a in program_args)
    env_items = "\n".join(
        f"        <key>{_esc(k)}</key>\n        <string>{_esc(v)}</string>"
        for k, v in env.items()
    )
    cwd = (
        f"    <key>WorkingDirectory</key>\n    <string>{_esc(working_dir)}</string>\n"
        if working_dir
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_esc(label)}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>EnvironmentVariables</key>
    <dict>
{env_items}
    </dict>
{cwd}    <key>StartInterval</key>
    <integer>{int(interval)}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{_esc(log_path)}</string>
    <key>StandardErrorPath</key>
    <string>{_esc(log_path)}</string>
</dict>
</plist>
"""


def job_environment() -> dict[str, str]:
    """The environment pinned into the plist: a usable PATH, HOME, and our own vars."""
    path_parts = [
        str(Path(sys.executable).parent),
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    env = {"PATH": ":".join(dict.fromkeys(path_parts)), "HOME": str(Path.home())}
    for var in PASSED_THROUGH:
        value = os.environ.get(var)
        if value:
            env[var] = value
    return env


def _plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def _log_path(label: str) -> Path:
    return Path.home() / "Library" / "Logs" / f"{label}.log"


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise NotImplementedError(
            "the supervised job is a macOS launchd agent. On Linux, run the same "
            "command from a systemd user timer or crontab:\n"
            f"    */15 * * * * {sys.executable} -m openloops sync\n"
            "openloops itself is cross-platform; only this installer is not."
        )


def install(
    *, label: str = DFLT_LABEL, interval: int = DFLT_INTERVAL, dry_run: bool = False
) -> dict[str, str]:
    """Install (or replace) the periodic sync job. Returns the paths it wrote.

    A smoke run follows the bootstrap, because a job that cannot start produces exactly
    the same silence as a job with nothing to do.
    """
    _require_macos()
    args = [sys.executable, "-m", "openloops", "sync"]
    env = job_environment()
    label = label or DFLT_LABEL
    plist_path, log_path = _plist_path(label), _log_path(label)
    xml = plist_xml(
        label=label,
        program_args=args,
        env=env,
        interval=interval,
        log_path=log_path,
    )
    if dry_run:
        return {"plist": str(plist_path), "log": str(log_path), "xml": xml}

    _bootstrap(
        label,
        plist_path,
        log_path,
        xml,
        smoke=[[*args[:2], "openloops", "--help"]],
        env=env,
    )
    return {"plist": str(plist_path), "log": str(log_path), "interval": str(interval)}


def _bootstrap(
    label: str,
    plist_path: Path,
    log_path: Path,
    xml: str,
    *,
    smoke: list[list[str]],
    env: dict[str, str],
) -> None:
    """Write the plist, (re)load it, and prove the command can start under *env*."""
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(xml)

    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
    loaded = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if loaded.returncode != 0:
        raise RuntimeError(
            f"wrote {plist_path} but launchctl bootstrap failed: "
            f"{(loaded.stderr or loaded.stdout).strip()}"
        )
    for command in smoke:
        check = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=120
        )
        if check.returncode != 0:
            raise RuntimeError(
                f"installed {label}, but `{' '.join(command[:3])}` cannot run under "
                f"the pinned environment — it would fail silently every tick:\n"
                f"  {(check.stderr or check.stdout).strip()[:400]}"
            )


#: The receiver's procedure, as packaged: the prompt points here rather than at an
#: installed skill, so a job never depends on `ol install-skills` having run.
RECEIVER_REFERENCES = (
    Path(__file__).parent / "data" / "skills" / "openloops-phone-board" / "references"
)


def _receiver_prompt() -> str:
    text = (Path(__file__).parent / "data" / "board" / "receiver-prompt.md").read_text(
        encoding="utf-8"
    )
    return text.replace("{references}", str(RECEIVER_REFERENCES))


def receiver_job_spec(
    work_dir: str | Path,
    *,
    claude: str | None = None,
    model: str = "sonnet",
    max_budget_usd: float = 1.0,
    allowed_tools: str = RECEIVER_TOOLS,
    env_file: str | Path = RECEIVER_ENV_FILE,
    interval: int = RECEIVER_INTERVAL,
    label: str = RECEIVER_LABEL,
    require_claude: bool = True,
) -> dict[str, object]:
    """The receiver job as data: program arguments, environment, plist. Pure but for
    looking up where ``claude`` and ``node`` are, so it can be tested anywhere.

    The job runs ``python -m openloops.receiver_tick``, which asks the board store
    whether anything is pending and only then replaces itself with ``claude -p`` and the
    packaged receiver prompt. The credentials stay in *env_file*; nothing about them
    is in the plist, the arguments or the environment (``PASSED_THROUGH`` names none).
    With ``require_claude=False`` (a dry run) a missing ``claude`` is shown as a bare
    name instead of refused.
    """
    claude_path = claude or shutil.which("claude")
    if claude_path:
        # Not resolved: `claude` is usually a symlink to a versioned file that an
        # update deletes, and the link is what keeps pointing at the current one.
        claude_path = os.path.abspath(Path(claude_path).expanduser())
    elif require_claude:
        raise FileNotFoundError(
            "`claude` is not on PATH: install Claude Code, or pass its absolute path"
        )
    else:
        claude_path = "claude"
    work = Path(work_dir).expanduser().resolve()
    env_path = Path(env_file).expanduser()
    env = job_environment()
    for var in RECEIVER_PASSED_THROUGH:
        if os.environ.get(var):
            env[var] = os.environ[var]
    # claude is a node script, and the session calls RECEIVER_COMMANDS: launchd's PATH
    # finds none of them unless their folders are pinned.
    extra = [str(Path(claude_path).parent)]
    missing = []
    for name in RECEIVER_COMMANDS:
        found = shutil.which(name)
        if found:
            extra.append(str(Path(found).parent))
        else:
            missing.append(name)
    env["PATH"] = ":".join(dict.fromkeys([*extra, *env["PATH"].split(":")]))
    args = [
        sys.executable,
        "-m",
        "openloops.receiver_tick",
        "--env-file",
        str(env_path),
        "--",
        claude_path,
        "-p",
        _receiver_prompt(),
        "--model",
        model,
        "--allowedTools",
        allowed_tools,
        "--max-budget-usd",
        str(max_budget_usd),
    ]
    log_path = _log_path(label)
    return {
        "label": label,
        "claude": claude_path,
        "program_args": args,
        "env": env,
        "interval": interval,
        "work_dir": str(work),
        "missing_commands": missing,
        "env_file": str(env_path),
        "log": str(log_path),
        "plist": str(_plist_path(label)),
        "xml": plist_xml(
            label=label,
            program_args=args,
            env=env,
            interval=interval,
            log_path=log_path,
            working_dir=work,
        ),
    }


def _check_receiver_inputs(work: Path, env_file: Path) -> None:
    """Refuse an install that would fail silently on every tick."""
    if not (work / "board" / "tasks.json").is_file():
        raise FileNotFoundError(
            f"{work} has no board/tasks.json: pass the board's working directory "
            "(the one `ol board-build` wrote into)"
        )
    if not env_file.is_file():
        raise FileNotFoundError(
            f"{env_file} does not exist. Create it (BOARD_ORIGIN, BOARD_API, "
            "BOARD_EMAIL, BOARD_PASSWORD; see the phone-board skill's "
            "references/receiver-http.md) and `chmod 600` it"
        )
    if env_file.stat().st_mode & 0o077:
        raise PermissionError(
            f"{env_file} is readable by others: `chmod 600 {env_file}` first"
        )


def install_receiver(
    work_dir: str | Path,
    *,
    dry_run: bool = False,
    **kwargs: object,
) -> dict[str, str]:
    """Install (or replace) the board-receiver job. Returns the paths it wrote.

    ``kwargs`` are those of :func:`receiver_job_spec`. A dry run builds and returns the
    plist without touching launchd and without requiring the credentials file.
    """
    spec = receiver_job_spec(work_dir, require_claude=not dry_run, **kwargs)
    if dry_run:
        return {k: str(v) for k, v in spec.items() if k in ("plist", "log", "xml")}
    _check_receiver_inputs(Path(str(spec["work_dir"])), Path(str(spec["env_file"])))
    _require_macos()
    label = str(spec["label"])
    _bootstrap(
        label,
        Path(str(spec["plist"])),
        Path(str(spec["log"])),
        str(spec["xml"]),
        smoke=[
            [sys.executable, "-m", "openloops.receiver_tick", "--help"],
            [str(spec["claude"]), "--version"],
        ],
        env=dict(spec["env"]),  # type: ignore[arg-type]
    )
    return {
        "plist": str(spec["plist"]),
        "log": str(spec["log"]),
        "interval": str(spec["interval"]),
        "missing_commands": ", ".join(spec["missing_commands"]),  # type: ignore[arg-type]
    }


def refresh_job_spec(
    work_dir: str | Path,
    *,
    refresh_args: Sequence[str] = (),
    interval: int = REFRESH_INTERVAL,
    label: str = REFRESH_LABEL,
) -> dict[str, object]:
    """The board-rebuild job as data: ``python -m openloops board-refresh WORK ...``.

    Pure, so it tests anywhere. The scope (owners, exclusions, run specs, where to
    publish) lives in ``WORK/refresh.json`` (``ol install-refresh-job`` saves it there),
    so the plist needs only ``WORK``; ``refresh_args`` are extra ``board-refresh``
    flags appended as they are, for a caller that wants them. The job runs with the
    sync job's minimal environment (``gh`` must be on its ``PATH`` and logged in for
    the same user) and carries no credential.
    """
    work = Path(work_dir).expanduser().resolve()
    args = [
        sys.executable,
        "-m",
        "openloops",
        "board-refresh",
        str(work),
        *refresh_args,
    ]
    env = job_environment()
    log_path = _log_path(label)
    return {
        "label": label,
        "program_args": args,
        "env": env,
        "interval": interval,
        "log": str(log_path),
        "plist": str(_plist_path(label)),
        "xml": plist_xml(
            label=label,
            program_args=args,
            env=env,
            interval=interval,
            log_path=log_path,
            working_dir=work,
        ),
    }


def install_refresh(
    work_dir: str | Path, *, dry_run: bool = False, **kwargs: object
) -> dict[str, str]:
    """Install (or replace) the board-rebuild job. ``kwargs`` are :func:`refresh_job_spec`'s."""
    spec = refresh_job_spec(work_dir, **kwargs)  # type: ignore[arg-type]
    if dry_run:
        return {k: str(v) for k, v in spec.items() if k in ("plist", "log", "xml")}
    _require_macos()
    _bootstrap(
        str(spec["label"]),
        Path(str(spec["plist"])),
        Path(str(spec["log"])),
        str(spec["xml"]),
        smoke=[[sys.executable, "-m", "openloops", "board-refresh", "--help"]],
        env=dict(spec["env"]),  # type: ignore[arg-type]
    )
    return {
        "plist": str(spec["plist"]),
        "log": str(spec["log"]),
        "interval": str(spec["interval"]),
    }


def remind_job_spec(
    *, interval: int = REMIND_INTERVAL, label: str = REMIND_LABEL
) -> dict[str, object]:
    """The reminder tick as data: ``python -m openloops remind-tick`` every ``interval`` s.

    Pure, so it tests anywhere. The job carries no credential: the ntfy topic is resolved
    by correspond (``NTFY_TOPIC``, else the Keychain), and the owner's zone by
    ``OPENLOOPS_TZ`` when set in the job's environment.
    """
    args = [sys.executable, "-m", "openloops", "remind-tick"]
    env = job_environment()
    log_path = _log_path(label)
    return {
        "label": label,
        "program_args": args,
        "env": env,
        "interval": interval,
        "log": str(log_path),
        "plist": str(_plist_path(label)),
        "xml": plist_xml(
            label=label,
            program_args=args,
            env=env,
            interval=interval,
            log_path=log_path,
        ),
    }


def install_remind(*, dry_run: bool = False, **kwargs: object) -> dict[str, str]:
    """Install (or replace) the reminder tick job. ``kwargs`` are :func:`remind_job_spec`'s."""
    spec = remind_job_spec(**kwargs)  # type: ignore[arg-type]
    if dry_run:
        return {k: str(v) for k, v in spec.items() if k in ("plist", "log", "xml")}
    _require_macos()
    _bootstrap(
        str(spec["label"]),
        Path(str(spec["plist"])),
        Path(str(spec["log"])),
        str(spec["xml"]),
        smoke=[
            [sys.executable, "-m", "openloops", "remind-tick", "--help"],
            # The tick delivers through correspond: a job that cannot import it would
            # install cleanly and then fail every hour.
            [sys.executable, "-c", "import correspond.channels.ntfy"],
        ],
        env=dict(spec["env"]),  # type: ignore[arg-type]
    )
    return {
        "plist": str(spec["plist"]),
        "log": str(spec["log"]),
        "interval": str(spec["interval"]),
    }


def uninstall(*, label: str = DFLT_LABEL) -> dict[str, str]:
    """Unload the job and remove its plist. Idempotent."""
    _require_macos()
    plist_path = _plist_path(label)
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True
    )
    existed = plist_path.exists()
    if existed:
        plist_path.unlink()
    return {"plist": str(plist_path), "removed": str(existed).lower()}


def pinned_missing(plist: Path) -> list[str]:
    """Absolute paths a job's plist pins that no longer exist (empty: fine, or unreadable).

    The job pins ``sys.executable`` (often under ``~/.pyenv/versions/X.Y.Z``) and, for the
    receiver, the ``claude`` link. ``pyenv uninstall`` or an upgrade deletes them and the
    job then fails silently every tick; this is the check that says so.

    >>> pinned_missing(Path('/no/such/plist'))
    []
    """
    try:
        args = plistlib.loads(Path(plist).read_bytes()).get("ProgramArguments") or []
    except Exception:  # noqa: BLE001 - a diagnostic must not crash on a damaged plist
        return []
    args = [a for a in args if isinstance(a, str)]
    pinned = args[:1]
    if "--" in args:
        pinned += args[args.index("--") + 1 :][:1]  # the receiver's claude
    return [p for p in pinned if os.path.isabs(p) and not Path(p).exists()]


def job_status(
    *, label: str = DFLT_LABEL, env_file: str | Path = RECEIVER_ENV_FILE
) -> dict[str, object]:
    """Installed? loaded? and — the question that matters — when did it last write?

    ``launchctl list`` says the job is registered, which is not the same as the job
    doing anything. The cache's modification time is the only evidence that a tick
    completed, so it is reported alongside. For the receiver, ``last_check`` is the
    last tick whose check succeeded (a stamp beside *env_file*) and ``last_write`` the
    last tick that had work (its log).
    """
    plist_path = _plist_path(label)
    loaded = None
    if sys.platform == "darwin":
        listed = subprocess.run(
            ["launchctl", "list", label], capture_output=True, text=True
        )
        loaded = listed.returncode == 0
    cache = sync_state_path()
    log = _log_path(label)
    last_check = None
    if label == RECEIVER_LABEL:
        # The log is touched only when a tick had work; a successful check touches its
        # own stamp and writes the board's `meta/receiver` heartbeat.
        evidence = log.stat().st_mtime if log.exists() else None
        stamp = Path(env_file).expanduser().with_name("board-receiver.lastcheck")
        last_check = stamp.stat().st_mtime if stamp.exists() else None
    else:
        evidence = cache.stat().st_mtime if cache.exists() else None
    return {
        "last_check": last_check,
        "label": label,
        "platform_supported": sys.platform == "darwin",
        "plist": str(plist_path),
        "installed": plist_path.exists(),
        "pinned_missing": pinned_missing(plist_path),
        "loaded": loaded,
        "log": str(log),
        "last_write": evidence,
        "state_dir": str(state_dir()),
    }


def pile_nudge_job_spec(
    *,
    interval: int = PILE_NUDGE_INTERVAL,
    stale_days: float = 3.0,
    label: str = PILE_NUDGE_LABEL,
) -> dict[str, object]:
    """The pile nudge as data: ``python -m openloops pile-nudge`` every ``interval`` s.

    Pure. It reads the pile through ``gh`` (the user's own login) and makes reminders
    through the reminder runner, so it needs both ``gh`` and correspond in the job.

    >>> spec = pile_nudge_job_spec(stale_days=2)
    >>> spec["program_args"][-3:]
    ['pile-nudge', '--stale-days', '2']
    """
    args = [
        sys.executable,
        "-m",
        "openloops",
        "pile-nudge",
        "--stale-days",
        f"{stale_days:g}",
    ]
    env = job_environment()
    log_path = _log_path(label)
    return {
        "label": label,
        "program_args": args,
        "env": env,
        "interval": interval,
        "log": str(log_path),
        "plist": str(_plist_path(label)),
        "xml": plist_xml(
            label=label,
            program_args=args,
            env=env,
            interval=interval,
            log_path=log_path,
        ),
    }


def install_pile_nudge(*, dry_run: bool = False, **kwargs: object) -> dict[str, str]:
    """Install (or replace) the pile nudge job. ``kwargs`` are :func:`pile_nudge_job_spec`'s."""
    spec = pile_nudge_job_spec(**kwargs)  # type: ignore[arg-type]
    if dry_run:
        return {k: str(v) for k, v in spec.items() if k in ("plist", "log", "xml")}
    _require_macos()
    _bootstrap(
        str(spec["label"]),
        Path(str(spec["plist"])),
        Path(str(spec["log"])),
        str(spec["xml"]),
        smoke=[
            [sys.executable, "-m", "openloops", "pile-nudge", "--help"],
            [sys.executable, "-c", "import correspond.channels.ntfy"],
        ],
        env=dict(spec["env"]),  # type: ignore[arg-type]
    )
    return {
        "plist": str(spec["plist"]),
        "log": str(spec["log"]),
        "interval": str(spec["interval"]),
    }
