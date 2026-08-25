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


def test_no_module_command_or_field_represents_an_obligation():
    """ADR-002's line between what ships and what stays withheld, made mechanical.

    Checked over **identifiers**, not prose. The package must say plainly that the
    ledger is absent — the module docstring does — and a naive grep would forbid the
    very sentence that documents the absence. What must not exist is a module, a
    command, a class, a function, an argument or a field that *represents* one.
    """
    import ast
    import re
    from pathlib import Path

    forbidden = re.compile(r"obligation|manual_task|manualtask|\bowe[ds]?\b|ledger")
    package = Path(__file__).resolve().parent.parent / "openloops"
    offenders = []
    for path in sorted(package.rglob("*.py")):
        if forbidden.search(path.stem):
            offenders.append(f"module name: {path.name}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
                names.update(a.arg for a in node.args.args + node.args.kwonlyargs)
            elif isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        for name in sorted(names):
            if forbidden.search(name.lower()):
                offenders.append(f"{path.name}: identifier {name!r}")

    assert not offenders, "a release with no ledger names one anyway:\n" + "\n".join(
        offenders
    )
