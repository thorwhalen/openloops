"""One tick of the board-receiver job: check for work without a model, then hand over.

ADR-011. A launchd ``StartInterval`` job runs this every few minutes. Starting a Claude
session on every tick would cost money while nothing is pending, so the tick first asks
the board store, with plain HTTP and no model, whether anything needs the receiver.
Only if something does (or the question cannot be answered) does it replace itself with
the real command, ``claude -p <the receiver prompt>``.

**Fail open.** A check that errors starts the session anyway, with the reason on stderr.
A broken check that silently suppressed the receiver would be the failure this package
exists to prevent: taps stored safely and never reaching GitHub, with nothing saying so.

This is the one module that talks to the network, to the owner's own board store (the
HTTP API of ADR-009). Nothing imports it; ``import openloops`` never loads it.

The work set is the one ``references/receiver.md`` defines: events with no receipt,
``processing`` receipts older than 15 minutes, ``queued`` receipts, and ``failed``
receipts marked transient. The sign-in is the one in ``references/receiver-http.md``.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "DFLT_ENV_FILE",
    "STALE_CLAIM",
    "Pending",
    "pending_work",
    "read_env_file",
    "main",
]

DFLT_ENV_FILE = Path("~/.config/openloops/board-receiver.env")
#: A ``processing`` receipt older than this is a sweep that died (receiver.md, section 0).
STALE_CLAIM = timedelta(minutes=15)
_TIMEOUT = 20
_REQUIRED = ("BOARD_ORIGIN", "BOARD_API", "BOARD_EMAIL", "BOARD_PASSWORD")


class Pending(list):
    """The reasons the receiver is needed; empty means nothing to do."""


def read_env_file(path: str | Path) -> dict[str, str]:
    """``KEY=VALUE`` / ``export KEY=VALUE`` lines of an env file, parsed, never executed.

    >>> import tempfile, pathlib
    >>> f = pathlib.Path(tempfile.mkdtemp()) / 'e'
    >>> _ = f.write_text("# c\\nexport A='x y'\\nB=2\\n\\nbad line\\n")
    >>> read_env_file(f)
    {'A': 'x y', 'B': '2'}
    """
    out: dict[str, str] = {}
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, eq, value = line.partition("=")
        key = key.strip()
        if not eq or not key.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _when(stamp: object) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def pending_work(
    outbox: Mapping[str, Any],
    receipts: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> Pending:
    """What needs the receiver, from the store's two collections (``id -> data``).

    >>> pending_work({'e1': {}}, {})
    ['1 event(s) without a receipt']
    >>> pending_work({'e1': {}}, {'e1': {'status': 'posted'}})
    []
    """
    now = now or datetime.now(timezone.utc)
    reasons = Pending()

    unreceived = [e for e in outbox if e not in receipts]
    if unreceived:
        reasons.append(f"{len(unreceived)} event(s) without a receipt")

    stale = queued = transient = 0
    for rid, rec in receipts.items():
        status = rec.get("status")
        result = rec.get("result") or {}
        if status == "processing":
            claimed = _when(rec.get("claimedAt"))
            stale += claimed is None or now - claimed > STALE_CLAIM
        elif status == "queued":
            queued += 1
        elif status == "failed" and result.get("transient"):
            transient += 1
    for count, what in (
        (stale, "stale claim(s)"),
        (queued, "queued receipt(s)"),
        (transient, "transient failure(s) to retry"),
    ):
        if count:
            reasons.append(f"{count} {what}")

    return reasons


class _Store:
    """The board store API over HTTP, signed in as the receiver's own account."""

    def __init__(self, env: Mapping[str, str], jar_path: Path):
        self.origin = env["BOARD_ORIGIN"].rstrip("/")
        self.api = "/" + env["BOARD_API"].strip("/")
        self.env = env
        self.jar = http.cookiejar.MozillaCookieJar(str(jar_path))
        if jar_path.exists():
            try:
                self.jar.load(ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError):
                pass
        #: With no saved session, sign in before the first listing rather than waiting
        #: for a 401: a host may answer an anonymous request with a 403 instead.
        self.has_session = len(self.jar) > 0
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _open(self, req: urllib.request.Request) -> bytes:
        with self.opener.open(req, timeout=_TIMEOUT) as resp:
            return resp.read()

    def sign_in(self) -> None:
        raw = self._open(urllib.request.Request(f"{self.origin}/auth/csrf"))
        csrf = json.loads(raw)["csrf"]
        body = json.dumps(
            {"email": self.env["BOARD_EMAIL"], "password": self.env["BOARD_PASSWORD"]}
        ).encode()
        req = urllib.request.Request(
            f"{self.origin}/auth/login",
            data=body,
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )
        self._open(req)
        try:
            self.jar.save(ignore_discard=True, ignore_expires=True)
            os.chmod(self.jar.filename, 0o600)
        except OSError:
            pass

    def collection(self, name: str) -> dict[str, Any]:
        url = f"{self.origin}{self.api}/{name}"
        if not self.has_session:
            self.sign_in()
            self.has_session = True
        for attempt in (0, 1):
            try:
                docs = json.loads(self._open(urllib.request.Request(url)))["docs"]
                return {d["id"]: d["data"] for d in docs}
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403) and attempt == 0:
                    self.sign_in()
                    continue
                raise
        raise RuntimeError("unreachable")


def check(env_file: str | Path = DFLT_ENV_FILE) -> Pending:
    """Ask the store whether anything needs the receiver. Raises if it cannot ask."""
    env = read_env_file(Path(env_file).expanduser())
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise RuntimeError(f"{env_file} lacks {', '.join(missing)}")
    jar = Path(env_file).expanduser().with_name("board-receiver.cookies")
    store = _Store(env, jar)
    return pending_work(
        store.collection("outbox"),
        store.collection("receipts"),
    )


#: After a failed check starts a session, wait this long before starting another one
#: for the same reason: a lasting misconfiguration must not start a paid session every
#: tick, all day.
FAIL_OPEN_BACKOFF = timedelta(hours=1)

_USAGE = (
    "usage: python -m openloops.receiver_tick [--check-only] [--env-file FILE] "
    "[-- COMMAND ...]\n"
    "Asks the board store, with no model, whether the receiver has work; if so "
    "(or if the question cannot be answered, at most once an hour) replaces itself "
    "with COMMAND."
)


def main(argv: list[str] | None = None) -> int:
    """``python -m openloops.receiver_tick [--check-only] [--env-file F] [-- CMD ...]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in args:
        i = args.index("--")
        args, command = args[:i], args[i + 1 :]
    if "--help" in args or "-h" in args:
        print(_USAGE)
        return 0
    check_only = "--check-only" in args
    env_file = DFLT_ENV_FILE
    if "--env-file" in args:
        at = args.index("--env-file") + 1
        if at >= len(args):
            print("--env-file needs a path", file=sys.stderr)
            return 2
        env_file = Path(args[at])
    stamp = Path(env_file).expanduser().with_name("board-receiver.failopen")

    try:
        reasons = check(env_file)
        failure = None
    except Exception as exc:  # fail open: see the module docstring
        reasons, failure = Pending(), f"{type(exc).__name__}: {exc}"

    if check_only or not command:
        if failure:
            print(f"check failed ({failure}); a tick would start the receiver anyway")
            return 1
        print("pending: " + ("; ".join(reasons) if reasons else "nothing"))
        return 0
    if failure:
        now = datetime.now(timezone.utc).timestamp()
        try:
            recent = now - stamp.stat().st_mtime < FAIL_OPEN_BACKOFF.total_seconds()
        except OSError:
            recent = False
        if recent:
            print(
                f"receiver check still failing ({failure}); a session was started "
                "within the last hour, waiting",
                file=sys.stderr,
            )
            return 1
        print(f"receiver check failed, starting anyway: {failure}", file=sys.stderr)
        try:
            stamp.touch()
        except OSError:
            pass
    else:
        try:
            stamp.unlink()
        except OSError:
            pass
        if not reasons:
            return 0  # idle: say nothing, so the log is touched only by ticks with work
        print("pending: " + "; ".join(reasons), file=sys.stderr)
    try:
        os.execv(command[0], command)
    except OSError as exc:
        print(f"cannot start {command[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 127
    return 0  # pragma: no cover - execv does not return


if __name__ == "__main__":
    raise SystemExit(main())
