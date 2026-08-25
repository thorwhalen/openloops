"""The egress rule turned on openloops' own repository.

ADR-017 requires the public/private boundary to be *mechanical* rather than advisory,
from the first commit. A ``.gitignore`` is advisory; a test that fails the build is
not. So every tracked file in this repository is scanned with exactly the code that
scrubs a user's digests: no absolute home path, no credential-shaped text.

If this fails on a file you just wrote, the fix is to rewrite the path (``~``- or
``$PP``-relative) or to build the credential-shaped fixture by concatenation, as
``tests/test_egress.py`` does. It is never to add an exclusion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openloops.egress import scan, scan_files

REPO = Path(__file__).resolve().parent.parent

#: Suffixes worth reading as text. Everything else is skipped by ``scan_files`` anyway,
#: but naming them keeps the scan fast and the failure list legible.
TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".cfg", ".ini",
    ".json", ".sh", ".plist", ".gitignore", ".editorconfig", ".gitattributes",
}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.skip("not a git repository")
    return result.stdout


def tracked_text_files() -> list[Path]:
    """Files git would publish: tracked, plus untracked-and-not-ignored.

    The second half matters before the first commit and on any branch with new files —
    a check that only looked at already-tracked files would pass on precisely the
    commit that introduced a violation.
    """
    names = set(_git("ls-files").splitlines())
    names |= set(_git("ls-files", "--others", "--exclude-standard").splitlines())
    paths = []
    for name in sorted(names):
        path = REPO / name
        if not path.is_file():
            continue
        if path.suffix in TEXT_SUFFIXES or path.name.startswith("."):
            paths.append(path)
    return paths


def test_no_tracked_file_carries_a_home_path_or_a_credential():
    files = tracked_text_files()
    assert files, "expected tracked files to scan"
    problems = scan_files(files, aliases={})
    assert not problems, "egress violations:\n" + "\n".join(problems)


def test_the_scan_would_actually_catch_something():
    """A check that never fires is indistinguishable from no check."""
    bad = REPO / "tests" / "_egress_canary.tmp"
    bad.write_text("/Us" + "ers/someone/x and " + "gh" + "p_" + "A" * 36 + "\n")
    try:
        problems = scan_files([bad], aliases={})
        assert len(problems) == 2
    finally:
        bad.unlink()


def test_the_scan_covers_what_the_build_actually_ships():
    """`git ls-files` and the sdist are not the same set, and the gap is not empty.

    ``--exclude-standard`` honours the user's *global* ignore file; the build reads only
    in-tree ``.gitignore``. Anything matched by one and not the other is invisible to the
    scan above and present in the tarball uploaded to PyPI — and the files a global
    ignore typically covers, like a local editor or agent config, are exactly the ones
    holding absolute paths.
    """
    import shutil
    import tarfile
    import tempfile

    if shutil.which("uv") is None:
        pytest.skip("uv is not available to build a distribution")
    with tempfile.TemporaryDirectory() as out:
        built = subprocess.run(
            ["uv", "build", "--sdist", "--out-dir", out],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        if built.returncode != 0:
            pytest.skip(f"could not build an sdist: {built.stderr.strip()[:200]}")
        tarballs = list(Path(out).glob("*.tar.gz"))
        assert tarballs, "uv build produced no sdist"
        problems = []
        with tarfile.open(tarballs[0]) as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                try:
                    text = handle.read().decode("utf-8")
                except UnicodeDecodeError:
                    continue
                problems.extend(scan(text, aliases={}, where=member.name))
    assert not problems, "egress violations in the sdist:\n" + "\n".join(problems)
