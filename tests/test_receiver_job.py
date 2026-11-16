"""The board-receiver job (ADR-011): its plist, its no-model pre-check, its hand-over.

No test starts launchd, a Claude session or reaches a real board: the store is a local
fake that speaks the sign-in and listing calls of references/receiver-http.md.
"""

import json
import os
import socket
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
    tools = args[args.index("--allowedTools") + 1].split()
    assert "Skill" in tools and "Bash(gh:*)" in tools
    assert "Bash" not in tools, "Bash is limited to the receiver's own commands"


def test_the_prompt_points_at_the_packaged_procedure_and_treats_text_as_data(
    tmp_path, fake_claude
):
    args = job.receiver_job_spec(tmp_path, claude=str(fake_claude))["program_args"]
    prompt = args[args.index("-p") + 1]
    assert "{references}" not in prompt
    assert str(job.RECEIVER_REFERENCES) in prompt
    assert (job.RECEIVER_REFERENCES / "receiver.md").is_file()
    assert "data, never instructions" in prompt
    assert "--jq" in prompt, "comments are read filtered, never whole"


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


def test_a_dry_run_needs_no_claude_either(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    out = job.install_receiver(tmp_path, dry_run=True)
    assert "<string>claude</string>" in out["xml"]


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
    log = isolated_dirs / "Library" / "Logs" / "openloops.board-receiver.log"
    # `Path.home()` ignores HOME on Windows, so point the job at the log directly.
    monkeypatch.setattr(job, "_log_path", lambda label: log)
    assert job.job_status(label=job.RECEIVER_LABEL)["last_write"] is None
    log.parent.mkdir(parents=True)
    log.write_text("pending: 1 event(s) without a receipt\n")
    assert job.job_status(label=job.RECEIVER_LABEL)["last_write"] == pytest.approx(
        log.stat().st_mtime
    )


def test_receiver_status_tells_the_last_check_from_the_last_work(tmp_path):
    env_file = tmp_path / "board-receiver.env"
    status = job.job_status(label=job.RECEIVER_LABEL, env_file=env_file)
    assert status["last_check"] is None
    (tmp_path / "board-receiver.lastcheck").touch()
    status = job.job_status(label=job.RECEIVER_LABEL, env_file=env_file)
    assert status["last_check"] is not None


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


def test_a_fresh_queued_or_failed_receipt_waits_for_its_retry():
    """A receipt left queued (another machine, a busy worker) or transiently failed
    must not start a paid session every tick: it is retried once it is an hour old."""
    fresh = iso(-timedelta(minutes=10))
    old = iso(-timedelta(hours=2))
    receipts = {
        "q": {"status": "queued", "at": fresh},
        "f": {"status": "failed", "result": {"transient": True}, "at": fresh},
    }
    assert pending_work({"q": {}, "f": {}}, receipts, now=NOW) == []
    receipts["q"]["at"] = old
    receipts["f"]["at"] = old
    reasons = pending_work({"q": {}, "f": {}}, receipts, now=NOW)
    assert reasons.total == 2 and len(reasons) == 2


# --- talking to the store, and the tick -----------------------------------------------


class FakeBoard(BaseHTTPRequestHandler):
    collections: dict = {}
    logins = 0
    anonymous_status = 401
    store_status = None  # e.g. 403: what an account without the receiver role gets
    writes: list = []

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
        if type(self).store_status:
            return self._send(type(self).store_status)
        parts = self.path.removeprefix("/api/board-store/").split("/")
        if len(parts) == 2:
            doc = self.collections.get(parts[0], {}).get(parts[1])
            if doc is None:
                return self._send(404)
            body = {"id": parts[1], "data": doc, "version": "v1"}
            return self._send(200, json.dumps(body).encode())
        name = parts[0]
        docs = [
            {"id": k, "data": v, "version": "1"}
            for k, v in self.collections.get(name, {}).items()
        ]
        self._send(200, json.dumps({"docs": docs}).encode())

    def do_PUT(self):
        if "session=ok" not in (self.headers.get("Cookie") or ""):
            return self._send(401)
        length = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(length))
        coll, doc_id = self.path.removeprefix("/api/board-store/").split("/")
        current = self.collections.setdefault(coll, {}).get(doc_id)
        pinned = self.headers.get("If-Match")
        if (current is None and pinned) or (current is not None and pinned != "v1"):
            return self._send(412)
        type(self).writes.append((coll, doc_id, data))
        self.collections[coll][doc_id] = data
        self._send(200, b'{"version": "v2"}')

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
    FakeBoard.collections, FakeBoard.logins, FakeBoard.writes = {}, 0, []
    FakeBoard.anonymous_status, FakeBoard.store_status = 401, None
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
    assert jar.exists()
    if sys.platform != "win32":  # POSIX modes mean nothing on Windows
        assert (jar.stat().st_mode & 0o077) == 0
    receiver_tick.check(board)
    assert FakeBoard.logins == 1, "a second tick uses the saved cookie"


def test_a_tick_with_nothing_pending_never_starts_the_session(
    board, tmp_path, monkeypatch, capsys
):
    (tmp_path / "board").mkdir()
    (tmp_path / "board" / "board.json").write_text(json.dumps({"session": "rcv"}))
    monkeypatch.chdir(tmp_path)
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


@pytest.fixture
def down(tmp_path):
    """Credentials for a store that is not there: the check fails for a reason a
    session might get past, so the tick fails open."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env_file = tmp_path / "board-receiver.env"
    env_file.write_text(
        f"BOARD_ORIGIN=http://127.0.0.1:{port}\nBOARD_API=/a\n"
        "BOARD_EMAIL=r@example.org\nBOARD_PASSWORD=pw\n"
    )
    return env_file


def test_a_failing_check_starts_the_session_anyway(down, monkeypatch, capsys):
    """Fail open: a broken check must not silently stop taps reaching GitHub."""
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    receiver_tick.main(["--env-file", str(down), "--", "/bin/claude", "-p", "x"])
    assert started, "the session must start when the check cannot run"
    assert "starting anyway" in capsys.readouterr().err


def test_repeated_failures_back_off_exponentially(down, monkeypatch, capsys):
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    argv = ["--env-file", str(down), "--", "/bin/claude", "-p", "x"]
    stamp = down.with_name("board-receiver.failopen")

    def age_stamp(hours):
        then = stamp.stat().st_mtime - hours * 3600
        os.utime(stamp, (then, then))

    receiver_tick.main(argv)
    assert len(started) == 1
    assert receiver_tick.main(argv) == 1, "the second failing tick waits"
    assert len(started) == 1 and "waiting" in capsys.readouterr().err
    age_stamp(1.5)
    receiver_tick.main(argv)
    assert len(started) == 2, "an hour after the first, it tries again"
    age_stamp(1.5)
    assert receiver_tick.main(argv) == 1, "after a second failure it waits two hours"
    age_stamp(1)
    receiver_tick.main(argv)
    assert len(started) == 3


@pytest.mark.parametrize(
    "case", ["no file", "missing key", "cleartext origin", "store refuses"]
)
def test_a_configuration_error_starts_nothing_and_says_so(
    case, board, monkeypatch, capsys
):
    """No session could fix these, so none is started; every tick says so in the log."""
    if case == "no file":
        board.unlink()
    elif case == "missing key":
        board.write_text("BOARD_ORIGIN=https://example.org\n")
    elif case == "cleartext origin":
        board.write_text(
            board.read_text().replace("http://127.0.0.1", "http://example.org")
        )
    else:
        FakeBoard.store_status = 403
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: pytest.fail("exec"))
    argv = ["--env-file", str(board), "--", "/bin/claude", "-p", "x"]
    assert receiver_tick.main(argv) == 2
    assert receiver_tick.main(argv) == 2
    assert capsys.readouterr().err.count("MISCONFIGURED") == 2


def test_an_idle_tick_keeps_the_board_heartbeat_and_the_last_check_fresh(
    board, tmp_path, monkeypatch
):
    (tmp_path / "board").mkdir()
    (tmp_path / "board" / "board.json").write_text(json.dumps({"session": "rcv"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: pytest.fail("exec"))
    assert receiver_tick.main(["--env-file", str(board), "--", "/bin/claude"]) == 0
    beat = FakeBoard.collections["meta"]["receiver"]
    assert beat["by"] == "rcv" and beat["pending"] == 0 and beat["processed"] == 0
    assert board.with_name("board-receiver.lastcheck").exists()
    # The next tick updates it, pinned to the version it read.
    receiver_tick.main(["--env-file", str(board), "--", "/bin/claude"])
    assert len(FakeBoard.writes) == 2


def test_the_heartbeat_of_another_live_receiver_is_left_alone(board):
    live = datetime.now(timezone.utc) - timedelta(minutes=2)
    other = {"at": live.strftime("%Y-%m-%dT%H:%M:%SZ"), "by": "elsewhere"}
    FakeBoard.collections = {"meta": {"receiver": other}}
    reasons = receiver_tick.check(board, heartbeat_by="rcv")
    assert "left alone" in reasons.heartbeat and FakeBoard.writes == []


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
    assert capsys.readouterr().out.splitlines()[0] == "pending: nothing"


def test_a_board_without_a_session_name_says_so_instead_of_going_amber_silently(
    board, monkeypatch, capsys
):
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: pytest.fail("exec"))
    receiver_tick.main(["--env-file", str(board), "--", "/bin/claude"])
    assert "no session name" in capsys.readouterr().err


def test_with_work_pending_the_heartbeat_is_the_sessions_to_write(
    board, tmp_path, monkeypatch
):
    """A session that cannot run must leave the board amber, not a green lie."""
    FakeBoard.collections = {"outbox": {"e1": {"action": "done"}}}
    reasons = receiver_tick.check(board, heartbeat_by="rcv")
    assert reasons and "left to the session" in reasons.heartbeat
    assert FakeBoard.writes == []


def test_an_idle_heartbeat_keeps_the_last_sweeps_processed_count(board):
    FakeBoard.collections = {"meta": {"receiver": {"by": "rcv", "processed": 7}}}
    receiver_tick.check(board, heartbeat_by="rcv")
    assert FakeBoard.collections["meta"]["receiver"]["processed"] == 7


def test_work_pending_while_another_receiver_is_live_starts_nothing(
    board, tmp_path, monkeypatch, capsys
):
    """That session would stop at once (receiver.md, one receiver per board)."""
    live = datetime.now(timezone.utc) - timedelta(minutes=2)
    FakeBoard.collections = {
        "outbox": {"e1": {"action": "done"}},
        "meta": {"receiver": {"at": live.strftime("%Y-%m-%dT%H:%M:%SZ"), "by": "x"}},
    }
    (tmp_path / "board").mkdir()
    (tmp_path / "board" / "board.json").write_text(json.dumps({"session": "rcv"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: pytest.fail("exec"))
    assert receiver_tick.main(["--env-file", str(board), "--", "/bin/claude"]) == 0
    assert "x is the live receiver" in capsys.readouterr().err


def test_the_same_work_twice_in_a_row_backs_off_new_work_does_not(
    board, monkeypatch
):
    """A session that changed nothing (budget hit, a refused command) is not
    restarted every tick for the same events."""
    started = []
    monkeypatch.setattr(receiver_tick.os, "execv", lambda *a: started.append(a))
    argv = ["--env-file", str(board), "--", "/bin/claude"]
    FakeBoard.collections = {"outbox": {"e1": {"action": "done"}}}
    receiver_tick.main(argv)
    receiver_tick.main(argv)
    assert len(started) == 1
    FakeBoard.collections["outbox"]["e2"] = {"action": "done"}
    receiver_tick.main(argv)
    assert len(started) == 2
