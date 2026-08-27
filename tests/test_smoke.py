"""The one-command test: the whole path end to end, every seam on its default.

If this stops passing, the release is broken however green the unit tests are. It is
also the check that each seam's default is a real implementation rather than a stub
wearing a keyword argument as a disguise.
"""

import subprocess
import sys

from fixtures import asking_session, closed_session, write_transcripts

from openloops.__main__ import main


def run(*argv, capsys):
    main(list(argv))
    return capsys.readouterr().out


def test_the_whole_path_end_to_end_on_the_defaults(projects_dir, capsys):
    write_transcripts(projects_dir, {"s1": closed_session("s1"), "s2": asking_session("s2")})

    assert "2 sessions scanned" in run("sync", capsys=capsys)

    listed = run("ls", "--state", "open", capsys=capsys)
    assert "s2" in listed and "s1" not in listed

    shown = run("show", "s2", capsys=capsys)
    assert "state: open" in shown and "Do you want me to land it" in shown

    reported = run("status", capsys=capsys)
    assert "1 open, 1 archive" in reported
    assert "2 transcripts on disk" in reported


def test_bare_ol_syncs_and_shows_the_open_loops(projects_dir, capsys):
    write_transcripts(projects_dir, {"s2": asking_session("s2")})
    out = run(capsys=capsys)
    assert "s2" in out
    assert "1 digest written" in out


def test_it_runs_on_a_machine_that_has_never_run_claude_code(isolated_dirs, capsys):
    out = run("sync", capsys=capsys)
    assert "0 sessions scanned" in out
    assert "(no digests)" in run("ls", capsys=capsys)


def test_importing_openloops_does_not_import_the_cli_library():
    """A surface's dependency must not become an import-time cost for the library."""
    code = "import sys, openloops; print('argh' in sys.modules, 'argcomplete' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False False"


def test_importing_openloops_reaches_no_network():
    """`import openloops` must not open a socket — a job on a plane still has to run."""
    code = (
        "import socket\n"
        "socket.socket = None\n"
        "socket.create_connection = None\n"
        "import openloops\n"
        "print('ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "ok"


def test_the_console_script_entry_point_resolves():
    from importlib.metadata import entry_points

    scripts = {e.name: e.value for e in entry_points(group="console_scripts")}
    assert scripts.get("ol") == "openloops.__main__:main"


def test_no_surface_exposes_a_mutating_operation():
    """Enforcement by omission (ADR-012 `no-mutating-tools`), made mechanical.

    This replaces an earlier guard that forbade obligation vocabulary anywhere in the
    package. That guard encoded the first release's decision to withhold the read path
    pending a measurement; the measurement was cancelled and the read path shipped, so
    the guard now forbids the module it was waiting for. What has *not* changed — and
    is what this checks instead — is that openloops only ever reads.

    Two halves, both over the source rather than over prose. No operation any surface
    exposes is named for a write, and nowhere in the package is `gh` handed a
    subcommand or an HTTP method that would change something on GitHub. An obligation
    is discharged by a human, never by this package's judgement of a predicate.
    """
    import ast
    import re
    from pathlib import Path

    from openloops import tools
    from openloops.__main__ import _commands

    mutating_name = re.compile(
        r"close|reopen|relabel|assign|comment|create_issue|delete|patch|post"
    )
    exposed = {f.__name__ for f in tools._dispatch_funcs} | {
        f.__name__ for f in _commands
    }
    named = sorted(n for n in exposed if mutating_name.search(n))
    assert not named, f"a read-only tool exposes a mutating verb: {named}"

    mutating_call = re.compile(
        r"issue\s+(close|create|edit|comment|reopen|delete|lock|transfer)"
        r"|label\s+(create|edit|delete|clone)"
        r"|(--method|-X)\s*[\"\']?\s*(POST|PATCH|PUT|DELETE)"
    )
    package = Path(__file__).resolve().parent.parent / "openloops"
    offenders = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if mutating_call.search(node.value):
                    offenders.append(f"{path.name}:{node.lineno}: {node.value[:60]!r}")
    assert not offenders, "a read-only package builds a write call:\n" + "\n".join(
        offenders
    )
