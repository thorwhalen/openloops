"""Test isolation: no network, no credentials, and never the real ``~/.claude``.

The suite has to pass on a machine that has never run Claude Code, so every test that
touches a path gets a temporary one, and the environment overrides are set for the
whole session rather than per-test — a single test that forgot would otherwise write
into the developer's own digest store.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Point every openloops directory at a fresh temporary one."""
    monkeypatch.setenv("OPENLOOPS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENLOOPS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OPENLOOPS_SOURCE", "testhost")
    monkeypatch.setenv("CLAUDE_PROJECTS_DIR", str(tmp_path / "projects"))
    # The obligation reader resolves its owner list from the environment first. A
    # developer who has one set would otherwise get a different answer from CI, and
    # the failure would be an owner list nobody wrote down in the test.
    monkeypatch.delenv("OPENLOOPS_OWNERS", raising=False)
    return tmp_path


@pytest.fixture
def projects_dir(isolated_dirs):
    """An empty Claude-Code-shaped projects directory."""
    path = isolated_dirs / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path
