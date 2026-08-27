"""The agent-facing surface: two skills, one subagent, and the command that installs them.

The ``ol`` command is plumbing. What most people actually want is an agent that knows
how to use the plumbing and tells them what matters -- "what is being done, and what
needs my attention?" -- without their ever typing ``ol owed``. That agent is a file:
a ``SKILL.md`` an agent host loads when the question comes up. So openloops ships three
of them, inside the package, and this module is how they get from the wheel to the host.

===========================  ==================================================
``openloops``                the **read** skill. Runs the three commands, and
                             synthesises rather than pastes. The one to load.
``openloops-needs-human``    the **capture** skill. Without something filing
                             ``manual-task`` issues, ``ol owed`` reads an empty
                             list forever -- which is the state a stranger
                             installs into.
``openloops-sweep``          a subagent: the same sweep in a fresh context,
                             returning a page instead of three screens of output.
===========================  ==================================================

**Nothing here is openloops-specific machinery.** A skill is a markdown file in a
directory an agent host reads; installing one is a symlink. The whole module is a
hundred lines because that is genuinely all it is, and the alternative -- a copy of
each skill pasted into every user's config -- is a copy that goes stale the first time
``pip install -U openloops`` lands.

Two decisions worth stating, because both are the kind that get quietly reversed:

**A symlink, not a copy.** The point is that upgrading the package upgrades the skill.
Copying is the *fallback*, taken only where symlinks are unavailable (Windows without
Developer Mode, where creating one needs a privilege an ordinary process lacks), and
the plan says which happened rather than pretending they are the same thing.

**Nothing already there is ever overwritten.** A destination holding something that is
not ours reads ``conflict``: it is reported, not replaced, and ``force=True`` is the
only way past. Someone's hand-written skill of the same name is theirs, and silently
eating it would be a worse failure than not installing at all.

This is deliberately *not* in :mod:`openloops.tools`. That module is the list every
surface dispatches from -- an MCP server, an HTTP endpoint -- and "symlink files into
this machine's agent config" is not an operation a remote surface could honestly offer.
It belongs beside :mod:`openloops.job`, the other installer, which the CLI also wraps
directly.

    >>> skills_dir().name, agents_dir().name
    ('skills', 'agents')
    >>> sorted(asset.name for asset in bundled())
    ['openloops', 'openloops-needs-human', 'openloops-sweep']
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "HOST_ENV_VAR",
    "Asset",
    "agents_dir",
    "bundled",
    "host_dir",
    "install_skills",
    "skills_dir",
]

#: Where Claude Code keeps skills and subagents, and the variable that relocates it.
#: Honoured rather than reimplemented: a user who has moved their config has done so
#: for a reason, and an installer that ignores it writes to a directory nobody reads.
HOST_ENV_VAR = "CLAUDE_CONFIG_DIR"
DFLT_HOST = "~/.claude"

#: Where each kind of asset lands under the host directory. A skill is a *directory*
#: (it may carry ``references/``); a subagent is a single markdown file.
_HOST_SUBDIR = {"skill": "skills", "agent": "agents"}


class SkillsNotBundled(RuntimeError):
    """This installation has no bundled skills, which means the wheel lost its data."""


def skills_dir() -> Path:
    """The bundled skills directory, inside the installed package.

    ``Path(__file__).parent`` rather than a configured root, so this answers correctly
    from a wheel, an editable install, a zip and a virtualenv without being told which.
    """
    return Path(__file__).parent / "data" / "skills"


def agents_dir() -> Path:
    """The bundled subagent definitions, inside the installed package."""
    return Path(__file__).parent / "data" / "agents"


def host_dir(target: str | Path | None = None) -> Path:
    """The agent host's config directory: ``target``, ``CLAUDE_CONFIG_DIR``, or ``~/.claude``.

    >>> import os
    >>> host_dir('/somewhere/else').name
    'else'
    """
    if target:
        return Path(target).expanduser()
    override = os.environ.get(HOST_ENV_VAR)
    return Path(override).expanduser() if override else Path(DFLT_HOST).expanduser()


@dataclass(frozen=True)
class Asset:
    """One installable thing: a skill directory or a subagent file.

    ``name`` is what the host will call it, and it is the file or folder name too --
    the agent-skill spec requires the folder name to equal the skill's ``name:``, so
    deriving one from the other cannot drift.
    """

    kind: str
    name: str
    source: Path

    def destination(self, host: Path) -> Path:
        """Where this asset goes under *host*."""
        directory = host / _HOST_SUBDIR[self.kind]
        return directory / self.name if self.kind == "skill" else directory / f"{self.name}.md"


def _existing(path: Path, what: str) -> Path:
    """`path`, or a readable failure naming what to do about it.

    A wheel built without the package data is the one failure mode of shipping skills
    this way, and it turns the first command a new user types into a traceback. Say what
    happened instead.
    """
    if path.is_dir():
        return path
    raise SkillsNotBundled(
        f"this openloops installation carries no bundled {what}: {path} does not exist. "
        "That means the wheel was built without its package data -- reinstall from PyPI "
        "(`pip install --force-reinstall openloops`), or from a source checkout with "
        "`pip install -e .`."
    )


def bundled() -> list[Asset]:
    """Every skill and subagent this package ships, sorted by name.

    Discovered from the directories rather than listed here: a list would be a second
    place to update, and the one that gets forgotten.
    """
    assets = [
        Asset("skill", path.name, path)
        for path in _existing(skills_dir(), "skills").iterdir()
        if (path / "SKILL.md").is_file()
    ]
    assets += [
        Asset("agent", path.stem, path)
        for path in agents_dir().glob("*.md")
        if path.is_file()
    ]
    return sorted(assets, key=lambda asset: asset.name)


def _identical(source: Path, destination: Path) -> bool:
    """Is *destination* a byte-for-byte copy of *source*?

    This is what makes copy-mode idempotent. Without it, every re-run on a platform
    where symlinks are unavailable would report a conflict against its own last run.
    """
    if source.is_dir():
        if not destination.is_dir():
            return False
        left = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
        right = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
        return left == right and all(
            (source / rel).read_bytes() == (destination / rel).read_bytes() for rel in left
        )
    return destination.is_file() and source.read_bytes() == destination.read_bytes()


def _symlinks_work() -> bool:
    """Can this process create a symlink at all?

    On Windows it usually cannot: ``os.symlink`` needs Developer Mode or an elevated
    process, and the failure is a ``OSError`` at call time rather than anything you can
    read off the platform name. Probing in a temporary directory answers it without
    touching the host's config, so a dry run predicts the same thing the real run does.
    """
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink(tmp, Path(tmp) / "probe", target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


def _verdict(asset: Asset, destination: Path, *, force: bool) -> tuple[str, str]:
    """What to do about one destination, and why. Never destructive on its own."""
    exists = destination.exists() or destination.is_symlink()
    if not exists:
        return "install", "not present"
    if destination.is_symlink():
        try:
            resolved = destination.resolve()
        except OSError:  # a symlink loop, or a broken one on a platform that raises
            resolved = None
        if resolved == asset.source.resolve():
            return "ok", "already linked to this package"
        if force:
            return "install", "replacing a link that pointed elsewhere"
        return "conflict", "a link pointing somewhere else is already there"
    if _identical(asset.source, destination):
        return "ok", "an identical copy is already there"
    if force:
        return "install", "replacing different content"
    return "conflict", "something else with this name is already there"


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def install_skills(
    *,
    target: str | Path | None = None,
    only: Sequence[str] | None = None,
    copy: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Make the bundled skills and subagent visible to an agent host. Idempotent.

    Links each one into ``target`` (default: ``CLAUDE_CONFIG_DIR`` or ``~/.claude``) so
    that upgrading the package upgrades the skill. ``copy=True`` takes a copy instead,
    which is also what happens by itself where symlinks are unavailable.

    Returns the plan it carried out -- one row per asset, each carrying its verdict and
    the reason for it. ``dry_run=True`` returns the same plan having touched nothing,
    which is the only way to see what a run would do *before* it does it.

    Nothing that is already there is overwritten: an occupied destination reads
    ``conflict`` and is left exactly as it was until ``force=True``.

    ``only=`` installs a subset by name. The case it exists for: you already have your
    own capture skill, adapted to your own fleet, and a second one competing for the same
    triggers is worse than either alone -- so take the reader and the subagent and leave
    the capture skill out.

    >>> plan = install_skills(target='/nonexistent/host', only=['openloops'], dry_run=True)
    >>> [row['name'] for row in plan['actions']]
    ['openloops']

    >>> plan = install_skills(target='/nonexistent/host', dry_run=True)
    >>> plan['counts']['install'], plan['dry_run']
    (3, True)
    >>> sorted({row['action'] for row in plan['actions']})
    ['install']
    """
    host = host_dir(target)
    linking = not copy and _symlinks_work()
    rows: list[dict[str, str]] = []
    assets = list(bundled())
    if only is not None:
        wanted = {str(name).strip() for name in only if str(name).strip()}
        known = {asset.name for asset in assets}
        unknown = wanted - known
        if unknown:
            raise ValueError(
                f"no bundled asset named {', '.join(sorted(unknown))}; "
                f"available: {', '.join(sorted(known))}"
            )
        assets = [asset for asset in assets if asset.name in wanted]
    for asset in assets:
        destination = asset.destination(host)
        action, reason = _verdict(asset, destination, force=force)
        method = ("symlink" if linking else "copy") if action == "install" else ""
        if action == "install" and not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _remove(destination)
            if linking:
                try:
                    os.symlink(
                        asset.source, destination, target_is_directory=asset.source.is_dir()
                    )
                except OSError:
                    # The probe said yes and this said no -- a network share, a
                    # different filesystem. Copying still gets the skill installed; the
                    # row says which happened, because a silent copy is a skill that
                    # stops tracking the package.
                    method = "copy"
                    linking = False
                    _copy(asset.source, destination)
            else:
                _copy(asset.source, destination)
        rows.append(
            {
                "kind": asset.kind,
                "name": asset.name,
                "source": str(asset.source),
                "destination": str(destination),
                "action": action,
                "method": method,
                "reason": reason,
            }
        )
    counts = {state: sum(row["action"] == state for row in rows) for state in ("install", "ok", "conflict")}
    return {
        "target": str(host),
        "method": "symlink" if linking else "copy",
        "dry_run": dry_run,
        "actions": rows,
        "counts": counts,
    }


def _copy(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
