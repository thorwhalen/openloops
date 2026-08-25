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
import subprocess
import sys
from pathlib import Path

from openloops.store import state_dir, sync_state_path

__all__ = [
    "DFLT_LABEL",
    "DFLT_INTERVAL",
    "install",
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


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plist_xml(
    *,
    label: str,
    program_args: list[str],
    env: dict[str, str],
    interval: int,
    log_path: Path,
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
    <key>StartInterval</key>
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
    smoke = subprocess.run(
        [*args[:2], "openloops", "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if smoke.returncode != 0:
        raise RuntimeError(
            f"installed {label}, but the command cannot run under the pinned "
            f"environment — it would fail silently every tick:\n"
            f"  {(smoke.stderr or smoke.stdout).strip()[:400]}"
        )
    return {"plist": str(plist_path), "log": str(log_path), "interval": str(interval)}


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
    return {
        "label": label,
        "platform_supported": sys.platform == "darwin",
        "plist": str(plist_path),
        "installed": plist_path.exists(),
        "loaded": loaded,
        "log": str(_log_path(label)),
        "last_write": cache.stat().st_mtime if cache.exists() else None,
        "state_dir": str(state_dir()),
    }
