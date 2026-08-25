"""The periodic job. Nothing here touches launchd — only the parts that are pure."""

import sys

import pytest

from openloops import job


def test_the_plist_is_a_start_interval_agent_not_a_daemon():
    xml = job.plist_xml(
        label="openloops.sync",
        program_args=[sys.executable, "-m", "openloops", "sync"],
        env={"HOME": "/h", "PATH": "/bin"},
        interval=900,
        log_path="/h/Library/Logs/openloops.sync.log",
    )
    assert "<key>StartInterval</key>" in xml
    assert "<integer>900</integer>" in xml
    assert "KeepAlive" not in xml, "a resident process is the shape ADR-003 rejected"
    assert "<key>Label</key>" in xml and "openloops.sync" in xml


def test_the_plist_escapes_what_xml_requires():
    xml = job.plist_xml(
        label="a&b", program_args=["<x>"], env={"K": "a<b"}, interval=1, log_path="/l"
    )
    assert "a&amp;b" in xml and "&lt;x&gt;" in xml and "a&lt;b" in xml


def test_the_job_invokes_the_interpreter_not_a_console_script():
    """launchd gives a job a nearly empty PATH; a name resolved there is a lottery."""
    result = job.install(dry_run=True) if sys.platform == "darwin" else None
    if result is None:
        pytest.skip("macOS only")
    assert sys.executable in result["xml"]
    assert "<string>-m</string>" in result["xml"]


def test_the_pinned_environment_carries_the_configuration(monkeypatch):
    monkeypatch.setenv("OPENLOOPS_DATA_DIR", "/somewhere/data")
    monkeypatch.setenv("OPENLOOPS_SOURCE", "boxy")
    env = job.job_environment()
    assert env["OPENLOOPS_DATA_DIR"] == "/somewhere/data"
    assert env["OPENLOOPS_SOURCE"] == "boxy"
    assert env["HOME"] and env["PATH"]


def test_unset_variables_are_simply_absent(monkeypatch):
    for var in job.PASSED_THROUGH:
        monkeypatch.delenv(var, raising=False)
    env = job.job_environment()
    assert not any(var in env for var in job.PASSED_THROUGH)


def test_status_reports_the_last_write_not_just_registration(isolated_dirs):
    """`launchctl list` says the job exists; only a write says it works."""
    info = job.job_status()
    assert info["last_write"] is None
    assert set(info) >= {"label", "installed", "loaded", "log", "last_write"}


def test_installing_off_macos_explains_the_alternative(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(NotImplementedError, match="crontab"):
        job.install()
    with pytest.raises(NotImplementedError):
        job.uninstall()
    assert job.job_status()["platform_supported"] is False
