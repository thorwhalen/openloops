"""The board-receiver job (ADR-011): its plist, its no-model pre-check, its hand-over.

No test starts launchd, a Claude session or reaches a real board: the store is a local
fake that speaks the sign-in and listing calls of references/receiver-http.md.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from openloops import job, receiver_tick
from openloops.receiver_tick import pending_work

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def iso(delta):
    return (NOW + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def fake_claude(tmp_path):
    """`claude` as installers lay it out: a link to a versioned file an update deletes."""
    versioned = tmp_path / "share" / "versions" / "2.1.0"
    versioned.parent.mkdir(parents=True)
    versioned.write_text("#!/bin/sh\n")
    versioned.chmod(0o755)
    link = tmp_path / "bin" / "claude"
    link.parent.mkdir()
    link.symlink_to(versioned)
    return link


# --- the job spec ---------------------------------------------------------------------


def test_the_receiver_plist_is_a_start_interval_job_that_pins_its_inputs(
    tmp_path, fake_claude
):
    spec = job.receiver_job_spec(tmp_path, claude=str(fake_claude))
    xml = spec["xml"]
    assert "<key>StartInterval</key>" in xml and "KeepAlive" not in xml
    assert "<key>WorkingDirectory</key>" in xml and str(tmp_path.resolve()) in xml
    args = spec["program_args"]
    assert args[:3] == [sys.executable, "-m", "openloops.receiver_tick"]
    # The link, never the versioned file it points to today: an update deletes that.
    assert args[args.index("--") + 1] == str(fake_claude)
    assert spec["claude"] == str(fake_claude)
    assert "versions" not in " ".join(args)
    assert "-p" in args and "--max-budget-usd" in args and "--allowedTools" in args
    assert "phone-board receiver" in args[args.index("-p") + 1]
    assert str(fake_claude.parent) in spec["env"]["PATH"]
    assert "Skill" in args[args.index("--allowedTools") + 1].split()


def test_no_credential_name_or_value_reaches_the_plist(
    tmp_path, fake_claude, monkeypatch
):
    monkeypatch.setenv("BOARD_PASSWORD", "hunter2-do-not-leak")
    monkeypatch.setenv("BOARD_EMAIL", "receiver@example.org")
    xml = job.receiver_job_spec(tmp_path, claude=str(fake_claude))["xml"]
    assert "hunter2" not in xml and "receiver@example.org" not in xml
    assert "BOARD_PASSWORD" not in xml and "BOARD_EMAIL" not in xml


def test_the_owner_configuration_is_passed_through(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("OPENLOOPS_READ_ONLY_ORGS", "client-org")
    spec = job.receiver_job_spec(tmp_path, claude=str(fake_claude))
    assert spec["env"]["OPENLOOPS_READ_ONLY_ORGS"] == "client-org"


def test_a_missing_claude_is_an_error_not_a_job_that_dies_every_tick(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="claude"):
        job.receiver_job_spec(tmp_path)


def test_a_dry_run_needs_neither_credentials_nor_launchd(tmp_path, fake_claude):
    out = job.install_receiver(tmp_path, claude=str(fake_claude), dry_run=True)
    assert "StartInterval" in out["xml"] and out["plist"].endswith(
        "openloops.board-receiver.plist"
    )


def test_a_real_install_refuses_inputs_that_would_fail_silently(tmp_path, fake_claude):
    env_file = tmp_path / "board-receiver.env"
    with pytest.raises(FileNotFoundError, match="tasks.json"):
        job.install_receiver(tmp_path, claude=str(fake_claude), env_file=env_file)
    (tmp_path / "board").mkdir()
    (tmp_path / "board" / "tasks.json").write_text("[]")
    with pytest.raises(FileNotFoundError, match="board-receiver.env"):
        job.install_receiver(tmp_path, claude=str(fake_claude), env_file=env_file)
    env_file.write_text("BOARD_PASSWORD=x\n")
    env_file.chmod(0o644)
    with pytest.raises(PermissionError, match="chmod 600"):
        job.install_receiver(tmp_path, claude=str(fake_claude), env_file=env_file)


def test_receiver_status_reads_the_log_not_the_sync_cache(isolated_dirs, monkeypatch):
    monkeypatch.setenv("HOME", str(isolated_dirs))
    assert job.job_status(label=job.RECEIVER_LABEL)["last_write"] is None
    log = isolated_dirs / "Library" / "Logs" / "openloops.board-receiver.log"
    log.parent.mkdir(parents=True)
    log.write_text("pending: 1 event(s) without a receipt\n")
    assert job.job_status(label=job.RECEIVER_LABEL)["last_write"] == pytest.approx(
        log.stat().st_mtime
    )


def test_importing_the_cli_never_loads_the_network_module():
    code = (
        "import sys, openloops.__main__; "
        "print('openloops.receiver_tick' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


# --- what counts as pending -----------------------------------------------------------


def test_nothing_is_pending_when_every_event_has_a_final_receipt():
    outbox = {"e1": {"action": "done"}, "e2": {"action": "note"}}
    receipts = {"e1": {"status": "posted"}, "e2": {"status": "recorded"}}
    assert pending_work(outbox, receipts, now=NOW) == []


def test_each_part_of_the_work_set_is_pending():
    receipts = {
        "fresh": {"status": "processing", "claimedAt": iso(-timedelta(minutes=3))},
        "stale": {"status": "processing", "claimedAt": iso(-timedelta(minutes=30))},
        "queued": {"status": "queued"},
        "transient": {"status": "failed", "result": {"transient": True}},
        "permanent": {"status": "failed", "result": {"transient": False}},
        "done": {"status": "posted"},
    }
    reasons = " | ".join(pending_work({"new": {}}, receipts, now=NOW))
    for part in (
        "1 event(s) without a receipt",
        "1 stale claim(s)",
        "1 queued receipt(s)",
        "1 transient failure(s)",
    ):
        assert part in reasons
    assert "2 " not in reasons, "the fresh claim and the permanent failure are not work"


# --- talking to the store, and the tick -----------------------------------------------


class FakeBoard(BaseHTTPRequestHandler):
    collections: dict = {}
    logins = 0
    anonymous_status = 401

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"{}", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/auth/csrf":
            return self._send(200, b'{"csrf": "tok"}')
        if "session=ok" not in (self.headers.get("Cookie") or ""):
            return self._send(type(self).anonymous_status)
        name = self.path.rsplit("/", 1)[-1]
        docs = [
            {"id": k, "data": v, "version": "1"}
            for k, v in self.collections.get(name, {}).items()
        ]
        self._send(200, json.dumps({"docs": docs}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length))
        ok = self.headers.get("X-CSRF-Token") == "tok" and body["password"] == "pw"
        if not ok:
            return self._send(403)
        type(self).logins += 1
        self._send(200, b"{}", [("Set-Cookie", "session=ok; Path=/")])


@pytest.fixture
def board(tmp_path):
    FakeBoard.collections, FakeBoard.logins = {}, 0
    FakeBoard.anonymous_status = 401
    server = HTTPServer(("127.0.0.1", 0), FakeBoard)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env_file = tmp_path / "board-receiver.env"
    env_file.write_text(
        f"export BOARD_ORIGIN=http://127.0.0.1:{server.server_port}\n"
        "export BOARD_API=/api/board-store\n"
        "export BOARD_EMAIL=receiver@example.org\n"
        "export BOARD_PASSWORD='pw'\n"
    )
    env_file.chmod(0o600)
    yield env_file
    server.shutdown()


def test_the_check_signs_in_once_reads_the_store_and_reuses_the_cookie(board):
    FakeBoard.collections = {"outbox": {"e1": {"action": "done"}}, "receipts": {}}
    first = receiver_tick.check(board)
    assert first == ["1 event(s) without a receipt"]
    assert FakeBoard.logins == 1
    jar = board.with_name("board-receiver.cookies")
    assert jar.exists() and (jar.stat().st_mode & 0o077) == 0
    receiver_tick.check(board)
    assert FakeBoard.logins == 1, "a second tick uses the saved cookie"


def test_a_tick_with_nothing_pending_never_starts_the_session(
    board, monkeypatch, capsys
):
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    code = receiver_tick.main(
        ["--env-file", str(board), "--", "/bin/claude", "-p", "x"]
    )
    assert code == 0 and started == []
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "", (
        "an idle tick leaves the log alone"
    )


def test_a_tick_with_work_replaces_itself_with_the_session(board, monkeypatch):
    FakeBoard.collections = {"outbox": {"e1": {"action": "done"}}}
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    receiver_tick.main(["--env-file", str(board), "--", "/bin/claude", "-p", "x"])
    assert started == [("/bin/claude", ["/bin/claude", "-p", "x"])]


def test_a_failing_check_starts_the_session_anyway(tmp_path, monkeypatch, capsys):
    """Fail open: a broken check must not silently stop taps reaching GitHub."""
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    missing = tmp_path / "nope.env"
    receiver_tick.main(["--env-file", str(missing), "--", "/bin/claude", "-p", "x"])
    assert started, "the session must start when the check cannot run"
    assert "starting anyway" in capsys.readouterr().err


def test_a_failing_check_starts_at_most_one_session_an_hour(
    tmp_path, monkeypatch, capsys
):
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    broken = tmp_path / "nope.env"
    argv = ["--env-file", str(broken), "--", "/bin/claude", "-p", "x"]
    receiver_tick.main(argv)
    assert len(started) == 1
    assert receiver_tick.main(argv) == 1, "the second failing tick waits"
    assert len(started) == 1 and "waiting" in capsys.readouterr().err
    stamp = tmp_path / "board-receiver.failopen"
    old = stamp.stat().st_mtime - 2 * 3600
    os.utime(stamp, (old, old))
    receiver_tick.main(argv)
    assert len(started) == 2, "an hour later it tries again"


def test_a_working_check_clears_the_back_off(board, monkeypatch):
    stamp = board.with_name("board-receiver.failopen")
    stamp.touch()
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: None)
    receiver_tick.main(["--env-file", str(board), "--", "/bin/claude"])
    assert not stamp.exists()


def test_a_session_that_cannot_start_is_reported_not_a_traceback(
    board, monkeypatch, capsys
):
    FakeBoard.collections = {"outbox": {"e1": {"action": "done"}}}

    def gone(*a):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(receiver_tick.os, "execv", gone)
    argv = ["--env-file", str(board), "--", "/gone/claude", "-p", "x"]
    assert receiver_tick.main(argv) == 127
    assert "cannot start /gone/claude" in capsys.readouterr().err


def test_a_first_tick_signs_in_even_if_anonymous_requests_get_a_403(board):
    FakeBoard.collections = {"outbox": {"e1": {"action": "done"}}}
    FakeBoard.anonymous_status = 403
    assert receiver_tick.check(board) == ["1 event(s) without a receipt"]
    assert FakeBoard.logins == 1


def test_help_needs_no_network_or_credentials(capsys):
    assert receiver_tick.main(["--help"]) == 0
    assert "usage" in capsys.readouterr().out


def test_check_only_reports_and_never_execs(board, monkeypatch, capsys):
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: pytest.fail("exec"))
    assert receiver_tick.main(["--check-only", "--env-file", str(board)]) == 0
    assert capsys.readouterr().out.strip() == "pending: nothing"
