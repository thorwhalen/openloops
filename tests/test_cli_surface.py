"""The command line itself: the argv spellings `ol` accepts, and what they exit.

Most of the suite calls :func:`openloops.__main__.main` with a list of arguments, which
does exercise the parser — but it only ever passes argv that works. What is pinned here
is the shape of the surface: which spellings exist, what the failures cost, and the
three behaviours that a dispatcher swap silently moves.

Recorded from the ``argh`` implementation before the ``cw`` migration and replayed
after: 28 argv vectors — top-level and per-subcommand ``--help``, the no-argument case,
four usage errors, both hand-caught error paths, and eight real runs against a scratch
store — produced byte-identical stdout, stderr and exit codes. That full-body diff
cannot live in CI, because CPython rewrites argparse's own option column between
versions and this repo's matrix spans several, so what is asserted here is the grammar
and the exit codes, which do not move between interpreters.

The three things worth stating plainly, because each one is invisible to every other
test in this suite:

* **``main`` returns ``None`` on success and raises on failure.** ``cw.run`` *returns*
  the exit code where ``argh`` raised it. Every other test calls ``main`` for its
  stdout and would pass just as well if ``ol`` had stopped exiting non-zero.
* **Bare ``ol`` is ``ol brief``**, not a usage error. That is a deliberate departure
  from argparse's required-subparser default and the reason the tool gets used.
* **A mistyped state and an unknown session id are user error, not a traceback** —
  ``main`` catches ``ValueError``/``KeyError`` and exits 2 with one line.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import openloops
from openloops.__main__ import DEFAULT_COMMAND, _commands

_ROOT = Path(openloops.__file__).resolve().parent.parent
_CLI_TIMEOUT = 120

#: Every verb the CLI exposes, spelled as the command line spells it.
COMMAND_NAMES = [f.__name__.replace("_", "-") for f in _commands]

_RUNNER = """
import sys
sys.argv = ['ol'] + {argv!r}
from openloops.__main__ import main
main()
"""


@pytest.fixture
def cli_env(isolated_dirs):
    """The environment a subprocess needs to see the same scratch dirs as the fixture."""
    return {
        "PYTHONPATH": str(_ROOT),
        "PATH": "/usr/bin:/bin",
        "COLUMNS": "80",
        "OPENLOOPS_DATA_DIR": str(isolated_dirs / "data"),
        "OPENLOOPS_STATE_DIR": str(isolated_dirs / "state"),
        "OPENLOOPS_SOURCE": "testhost",
        "CLAUDE_PROJECTS_DIR": str(isolated_dirs / "projects"),
    }


def run_cli(*argv, env, cwd):
    """Run ``ol <argv>`` in a subprocess, with ``argv[0]`` pinned to the script name."""
    return subprocess.run(
        [sys.executable, "-c", _RUNNER.format(argv=list(argv))],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT,
        env=env,
    )


def test_every_command_is_reachable_and_documents_itself(cli_env, isolated_dirs):
    top = run_cli("--help", env=cli_env, cwd=isolated_dirs)
    assert top.returncode == 0
    assert top.stdout.startswith("usage: ol")
    for name in COMMAND_NAMES:
        assert name in top.stdout, f"{name} missing from `ol --help`"
        sub = run_cli(name, "--help", env=cli_env, cwd=isolated_dirs)
        assert sub.returncode == 0, sub.stderr
        assert sub.stdout.startswith(f"usage: ol {name}")


def test_prog_stays_ol_under_python_dash_m(cli_env, isolated_dirs):
    """``prog`` is pinned, so the usage line reads ``ol`` however the module was entered."""
    result = subprocess.run(
        [sys.executable, "-m", "openloops", "--help"],
        cwd=str(isolated_dirs),
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT,
        env=cli_env,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("usage: ol")


def test_bare_ol_runs_the_default_command(cli_env, isolated_dirs):
    """Bare ``ol`` is ``ol brief`` — a read path nobody reaches daily is a failed tool."""
    bare = run_cli(env=cli_env, cwd=isolated_dirs)
    named = run_cli(DEFAULT_COMMAND, env=cli_env, cwd=isolated_dirs)
    assert bare.returncode == 0
    assert bare.stdout == named.stdout


def test_since_days_is_read_as_a_number(cli_env, isolated_dirs):
    """``--since-days`` takes its ``type=`` from the ``float`` annotation, not the default.

    A string here reaches the reader and fails deep inside it, which is what the
    ``ALL_HISTORY`` sentinel was originally there to avoid.
    """
    ok = run_cli("sync", "--since-days", "2", env=cli_env, cwd=isolated_dirs)
    assert ok.returncode == 0
    bad = run_cli("sync", "--since-days", "soon", env=cli_env, cwd=isolated_dirs)
    assert bad.returncode == 2
    assert "invalid float value" in bad.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ("no-such-command",),
        ("ls", "--no-such-flag"),
        ("show",),  # a required positional, omitted
        ("sync", "extra"),
    ],
)
def test_usage_errors_exit_two(argv, cli_env, isolated_dirs):
    """``cw.run`` returns the code, so ``main`` must raise on it.

    Dropping that raise turns every one of these into exit 0, which nothing else in
    this suite would notice.
    """
    assert run_cli(*argv, env=cli_env, cwd=isolated_dirs).returncode == 2


@pytest.mark.parametrize(
    "argv, needle",
    [
        (("ls", "--state", "bogus"), "state must be one of"),
        (("show", "nosuchsession"), "no digest for session"),
    ],
)
def test_user_error_is_one_line_and_exit_two_not_a_traceback(
    argv, needle, cli_env, isolated_dirs
):
    """``main`` catches ValueError/KeyError. A traceback also prints install paths."""
    result = run_cli(*argv, env=cli_env, cwd=isolated_dirs)
    assert result.returncode == 2
    assert result.stderr.startswith("ol: ")
    assert needle in result.stderr
    assert "Traceback" not in result.stderr


def test_main_returns_none_when_the_command_succeeded():
    """The in-process contract the rest of the suite is built on."""
    from openloops.__main__ import main

    assert main(["status"]) is None


def test_the_package_declares_the_cli_library_it_imports():
    pyproject = (_ROOT / "pyproject.toml").read_text()
    assert '"cw>=' in pyproject
    assert "argh" not in pyproject
