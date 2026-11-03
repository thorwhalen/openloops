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
import shutil
import subprocess
import sys
from pathlib import Path

from openloops.store import state_dir, sync_state_path

__all__ = [
    "DFLT_LABEL",
    "DFLT_INTERVAL",
    "RECEIVER_LABEL",
    "RECEIVER_INTERVAL",
    "install",
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
)


#: launchd label of the board-receiver job (ADR-011).
RECEIVER_LABEL = "openloops.board-receiver"

#: Seconds between receiver ticks. A tick that finds nothing pending costs a few HTTP
#: calls and no model, so this can be as short as the phone board's latency wants.
RECEIVER_INTERVAL = 300

#: Tools the unattended receiver session may use without asking: it runs `gh`, `curl`
#: and `python3` through Bash, writes backups and comment bodies, and reads the skill.
RECEIVER_TOOLS = "Bash Read Write Edit Glob Grep"

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
        smoke=[*args[:2], "openloops", "--help"],
        env=env,
    )
    return {"plist": str(plist_path), "log": str(log_path), "interval": str(interval)}


def _bootstrap(
    label: str,
    plist_path: Path,
    log_path: Path,
    xml: str,
    *,
    smoke: list[str],
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
    check = subprocess.run(smoke, env=env, capture_output=True, text=True, timeout=120)
    if check.returncode != 0:
        raise RuntimeError(
            f"installed {label}, but the command cannot run under the pinned "
            f"environment — it would fail silently every tick:\n"
            f"  {(check.stderr or check.stdout).strip()[:400]}"
        )


def _receiver_prompt() -> str:
    return (Path(__file__).parent / "data" / "board" / "receiver-prompt.md").read_text(
        encoding="utf-8"
    )


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
) -> dict[str, object]:
    """The receiver job as data: program arguments, environment, plist. Pure but for
    looking up where ``claude`` and ``node`` are, so it can be tested anywhere.

    The job runs ``python -m openloops.receiver_tick``, which asks the board store
    whether anything is pending and only then replaces itself with ``claude -p`` and the
    packaged receiver prompt. The credentials stay in *env_file*; nothing about them
    is in the plist, the arguments or the environment (``PASSED_THROUGH`` names none).
    """
    claude_path = claude or shutil.which("claude")
    if not claude_path:
        raise FileNotFoundError(
            "`claude` is not on PATH: install Claude Code, or pass its absolute path"
        )
    claude_path = str(Path(claude_path).expanduser().resolve())
    work = Path(work_dir).expanduser().resolve()
    env_path = Path(env_file).expanduser()
    env = job_environment()
    for var in RECEIVER_PASSED_THROUGH:
        if os.environ.get(var):
            env[var] = os.environ[var]
    # claude is a node script: launchd's PATH finds neither it nor node unless told.
    extra = [str(Path(claude_path).parent)]
    node = shutil.which("node")
    if node:
        extra.append(str(Path(node).resolve().parent))
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
        "program_args": args,
        "env": env,
        "interval": interval,
        "work_dir": str(work),
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
    spec = receiver_job_spec(work_dir, **kwargs)
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
        smoke=[sys.executable, "-m", "openloops.receiver_tick", "--help"],
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


def job_status(*, label: str = DFLT_LABEL) -> dict[str, object]:
    """Installed? loaded? and — the question that matters — when did it last write?

    ``launchctl list`` says the job is registered, which is not the same as the job
    doing anything. The cache's modification time is the only evidence that a tick
    completed, so it is reported alongside.
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
    if label == RECEIVER_LABEL:
        # Nothing here writes a cache; the log is touched only when a tick had work, and
        # the board's own `meta/receiver` heartbeat is the authority on liveness.
        evidence = log.stat().st_mtime if log.exists() else None
    else:
        evidence = cache.stat().st_mtime if cache.exists() else None
    return {
        "label": label,
        "platform_supported": sys.platform == "darwin",
        "plist": str(plist_path),
        "installed": plist_path.exists(),
        "loaded": loaded,
        "log": str(log),
        "last_write": evidence,
        "state_dir": str(state_dir()),
    }
