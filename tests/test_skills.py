"""The agent-facing surface: the files ship, they parse, and installing twice is once.

Three kinds of check, and the middle one is the one that actually bites in practice:

1. the skills and the subagent exist and are spec-clean, so an agent host will load
   them and `gh skill publish` will not reject them;
2. **they are in the wheel.** A skill that is not in the built distribution is not
   shipped, nothing at runtime says so, and the failure surfaces as "the skill just
   isn't there" on somebody else's machine a week later;
3. the installer is idempotent, dry-runnable, and never eats a file it did not write.

Nothing here touches the real agent host: every install is given an explicit ``target``
under ``tmp_path``. A test that forgot would rewrite the developer's own ``~/.claude``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from openloops import skills
from openloops.obligations import DFLT_LABEL

#: The Agent Skills spec: lowercase, hyphen-separated, no leading/trailing/double hyphen.
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: The spec's top-level keys. Anything else — notably a bare ``audience:`` — is rejected
#: by ``gh skill publish``, and the failure is at publish time rather than at load time.
SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}

#: The spec's own limit on the field a model reads before deciding to open the skill.
MAX_DESCRIPTION = 1024


def front_matter(text: str) -> dict[str, str]:
    """The YAML header as a flat dict, without taking on a YAML dependency.

    Handles the two shapes these files actually use: ``key: value`` and a folded
    ``key: >-`` block. A nested mapping (``metadata:``) collapses into its parent's
    value, which is all the assertions below need of it.
    """
    lines = text.splitlines()
    assert lines[0].strip() == "---", "no front matter"
    end = lines.index("---", 1)
    out: dict[str, str] = {}
    key = None
    for line in lines[1:end]:
        if line[:1] not in (" ", "\t") and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            out[key] = "" if value in (">", ">-", "|", "|-") else value
        elif key is not None:
            out[key] = (out[key] + " " + line.strip()).strip()
    return {k: v.strip().strip('"') for k, v in out.items()}


def skill_paths() -> list[Path]:
    return sorted(skills.skills_dir().glob("*/SKILL.md"))


def agent_paths() -> list[Path]:
    return sorted(skills.agents_dir().glob("*.md"))


# --------------------------------------------------------------------------------
# The files themselves.


def test_the_bundled_directories_are_inside_the_installed_package():
    """`Path(__file__).parent`, never a configured root: a wheel has no repo around it."""
    package = Path(skills.__file__).parent
    assert skills.skills_dir() == package / "data" / "skills"
    assert skills.agents_dir() == package / "data" / "agents"
    assert skills.skills_dir().is_dir() and skills.agents_dir().is_dir()


def test_bundled_lists_the_read_skill_the_capture_skill_and_the_subagent():
    found = {(asset.kind, asset.name) for asset in skills.bundled()}
    assert found == {
        ("skill", "openloops"),
        ("skill", "openloops-needs-human"),
        ("agent", "openloops-sweep"),
    }


@pytest.mark.parametrize("path", skill_paths(), ids=lambda p: p.parent.name)
def test_every_skill_is_spec_clean(path):
    header = front_matter(path.read_text(encoding="utf-8"))
    assert header["name"] == path.parent.name, "folder name must equal `name:`"
    assert NAME_RE.match(header["name"]) and len(header["name"]) <= 64
    # The description is the whole trigger surface — the only thing a model sees before
    # deciding to open the file — and it is also the field with a hard limit.
    assert 0 < len(header["description"]) <= MAX_DESCRIPTION
    assert set(header) <= SPEC_KEYS, f"non-spec top-level keys: {set(header) - SPEC_KEYS}"
    assert "audience" in header.get("metadata", ""), "audience belongs under metadata:"


@pytest.mark.parametrize("path", agent_paths(), ids=lambda p: p.stem)
def test_every_subagent_declares_what_it_is_and_what_it_may_touch(path):
    header = front_matter(path.read_text(encoding="utf-8"))
    assert header["name"] == path.stem
    assert header["description"]
    # A subagent inherits every tool unless it names some. This one reads and reports;
    # an unbounded tool list would hand a read-only sweep the ability to write.
    assert header["tools"], "give the subagent only the tools it needs"
    assert "Write" not in header["tools"] and "Edit" not in header["tools"]


def test_the_read_skill_still_matches_what_the_renderers_actually_print():
    """The skill teaches an agent to read `ol` output; the renderers produce it.

    Nothing links the two, so a renamed verb or a reworded verdict would leave the skill
    confidently teaching a vocabulary the command no longer speaks — and the agent would
    report the state it was taught rather than the state it was shown.
    """
    from openloops.__main__ import _BLOCKED_MARKS, _STATE_MARKS, _owed_report

    text = (skills.skills_dir() / "openloops" / "SKILL.md").read_text(encoding="utf-8")
    for command in ("`ol`", "`ol owed`", "`ol blocked`", "--no-verify"):
        assert command in text
    for mark in {**_STATE_MARKS, **_BLOCKED_MARKS}.values():
        assert mark in text, f"the skill never mentions the `{mark}` verdict"
    # The exact line a failed listing prints. This is the one the skill must not let an
    # agent read as "nothing owed", so it quotes it verbatim.
    refusal = _owed_report({"listed": False, "error": "gh: not logged in"})
    assert refusal.split(" - ")[0] in text


def test_the_capture_skill_still_names_what_owed_keys_on():
    """The label and the field are the contract between the two halves of the package.

    Nothing links them at runtime: the capture skill writes an issue, `ol owed` reads it
    back, and the only thing joining them is the spelling of a label and a field name.
    Changing either in code without changing the skill breaks the loop silently.
    """
    text = (
        skills.skills_dir() / "openloops-needs-human" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert DFLT_LABEL in text
    assert "**Verify:**" in text
    assert "none possible" in text, "the documented wording for an unverifiable ask"


# --------------------------------------------------------------------------------
# Installing.


def test_a_dry_run_says_what_it_would_do_and_does_none_of_it(tmp_path):
    host = tmp_path / "host"
    plan = skills.install_skills(target=host, dry_run=True)
    assert plan["dry_run"] and plan["counts"]["install"] == 3
    assert not host.exists(), "a dry run must not create the host directory"
    assert all(Path(row["source"]).exists() for row in plan["actions"])


def test_installing_twice_is_installing_once(tmp_path):
    host = tmp_path / "host"
    first = skills.install_skills(target=host)
    assert first["counts"] == {"install": 3, "ok": 0, "conflict": 0}
    for row in first["actions"]:
        assert Path(row["destination"]).exists()

    second = skills.install_skills(target=host)
    assert second["counts"] == {"install": 0, "ok": 3, "conflict": 0}


def test_copying_twice_is_also_installing_once(tmp_path):
    """The Windows path. Symlinks need a privilege there, so copy mode is the real one.

    Without the content comparison behind it, a re-run would report a conflict against
    its own previous run — which reads as "somebody else's file is in the way".
    """
    host = tmp_path / "host"
    first = skills.install_skills(target=host, copy=True)
    assert first["method"] == "copy" and first["counts"]["install"] == 3
    installed = host / "skills" / "openloops" / "SKILL.md"
    assert not installed.is_symlink() and installed.read_text(encoding="utf-8")

    assert skills.install_skills(target=host, copy=True)["counts"]["ok"] == 3


def test_nothing_that_is_already_there_is_ever_overwritten(tmp_path):
    """Someone's hand-written skill of the same name is theirs."""
    host = tmp_path / "host"
    mine = host / "skills" / "openloops"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine, not yours", encoding="utf-8")

    plan = skills.install_skills(target=host)
    assert plan["counts"] == {"install": 2, "ok": 0, "conflict": 1}
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "mine, not yours"

    forced = skills.install_skills(target=host, force=True)
    assert forced["counts"]["conflict"] == 0
    assert (mine / "SKILL.md").read_text(encoding="utf-8") != "mine, not yours"


def test_a_link_pointing_somewhere_else_is_a_conflict_not_a_silent_relink(tmp_path):
    host = tmp_path / "host"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (host / "skills").mkdir(parents=True)
    try:
        os.symlink(elsewhere, host / "skills" / "openloops", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not let this process create a symlink")

    plan = skills.install_skills(target=host)
    row = next(r for r in plan["actions"] if r["name"] == "openloops")
    assert row["action"] == "conflict"
    assert (host / "skills" / "openloops").resolve() == elsewhere.resolve()


def test_every_row_carries_the_reason_for_its_own_verdict(tmp_path):
    """`conflict` with no reason is a refusal you cannot act on."""
    plan = skills.install_skills(target=tmp_path / "host", dry_run=True)
    assert all(row["reason"] for row in plan["actions"])
    assert {row["action"] for row in plan["actions"]} <= {"install", "ok", "conflict"}


def test_the_host_directory_is_the_target_then_the_env_var_then_the_default(monkeypatch):
    monkeypatch.delenv(skills.HOST_ENV_VAR, raising=False)
    assert skills.host_dir() == Path("~/.claude").expanduser()
    monkeypatch.setenv(skills.HOST_ENV_VAR, str(Path("~", "elsewhere")))
    assert skills.host_dir() == Path("~", "elsewhere").expanduser()
    assert skills.host_dir(Path("a", "b")) == Path("a", "b")


def test_the_cli_verb_renders_a_plan_without_writing_anything(tmp_path, capsys):
    from openloops.__main__ import main

    host = tmp_path / "host"
    main(["install-skills", "--target", str(host), "--dry-run"])
    printed = capsys.readouterr().out
    assert "would install into" in printed
    assert "openloops-sweep" in printed
    assert not host.exists()


# --------------------------------------------------------------------------------
# Shipping.


def test_the_wheel_actually_carries_the_skills(tmp_path):
    """The single most common way this whole feature silently fails.

    Everything above passes against the source tree whether or not the build includes
    ``openloops/data/``, so it is the only check that would notice the omission -- and it must build the way a RELEASE
    builds. `uv build --wheel` builds from SOURCE and passes while the release, which
    builds the wheel from the SDIST, ships nothing. Measured 2026-08-27: that is exactly
    how two skills reached a review missing from the artifact — and
    the symptom without it is a `pip install` whose skills directory does not exist.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not available to build a wheel")
    repo = Path(__file__).resolve().parent.parent
    built = subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if built.returncode != 0:
        pytest.skip(f"could not build a wheel: {built.stderr.strip()[:200]}")
    wheels = list(tmp_path.glob("*.whl"))
    assert wheels, "uv build produced no wheel"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    for asset in skills.bundled():
        relative = asset.source.relative_to(Path(skills.__file__).parent.parent)
        expected = relative.as_posix() + ("/SKILL.md" if asset.kind == "skill" else "")
        assert expected in names, f"{expected} is missing from the wheel"


def test_every_shipped_file_is_utf8_text():
    """Every one of them carries an em dash, so a locale-default read is a real risk.

    ``openloops.store`` pins UTF-8 for exactly this reason; these files are read by the
    agent host rather than by us, but the check that they *are* UTF-8 is still ours.
    """
    for path in [*skill_paths(), *agent_paths()]:
        assert path.read_bytes().decode("utf-8").strip()
