"""One tick of the board-receiver job: check for work without a model, then hand over.

ADR-011. A launchd ``StartInterval`` job runs this every few minutes. Starting a Claude
session on every tick would cost money while nothing is pending, so the tick first asks
the board store, with plain HTTP and no model, whether anything needs the receiver.
Only if something does (or the question cannot be answered) does it replace itself with
the real command, ``claude -p <the receiver prompt>``.

**Liveness.** Every successful check writes the board's ``meta/receiver`` heartbeat
(the receiver's own document, under the session name from ``board/board.json``), so an
idle board stays green and a dead job turns it amber after 20 minutes. It also touches a
local ``board-receiver.lastcheck`` stamp, which ``ol receiver-job-status`` reports as
"last check", separately from "last work" (the log, written only by ticks with work).

**Fail closed on configuration, open on anything else.** A configuration error (no
credentials file, a missing key, a cleartext origin, a refused sign-in, a 403 from the
store) cannot be fixed by a session, so the tick starts none and says so in the log on
every tick; the stale heartbeat turns the board amber. Any other failure (the store
down, a malformed answer, a bug here) starts the session anyway, because a check that
silently suppressed the receiver would be the failure this package exists to prevent.
Repeated failures back off exponentially: one hour, then two, four, capped at six.

This is the one module that talks to the network, to the owner's own board store (the
HTTP API of ADR-009). Nothing imports it; ``import openloops`` never loads it.

The work set is the one ``references/receiver.md`` defines: events with no receipt,
``processing`` receipts older than 15 minutes, and ``queued`` receipts and ``failed``
receipts marked transient. Those last two are retried only once they are an hour old
(:data:`RETRY_AFTER`): a receipt that waits on another machine, a busy worker or a
lasting GitHub error would otherwise start a paid session every tick, all day, to change
nothing. The sign-in is the one in ``references/receiver-http.md``.
"""

from __future__ import annotations

import http.cookiejar
import hashlib
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "DFLT_ENV_FILE",
    "STALE_CLAIM",
    "RETRY_AFTER",
    "FAIL_OPEN_BACKOFF",
    "FAIL_OPEN_CAP",
    "ConfigError",
    "Pending",
    "check",
    "pending_work",
    "read_env_file",
    "main",
]

DFLT_ENV_FILE = Path("~/.config/openloops/board-receiver.env")
#: A ``processing`` receipt older than this is a sweep that died (receiver.md, section 0).
STALE_CLAIM = timedelta(minutes=15)
#: A ``queued`` or transiently ``failed`` receipt is retried only once it is this old.
RETRY_AFTER = timedelta(hours=1)
#: A heartbeat by another receiver younger than this means that one is live (receiver.md).
LIVE_HEARTBEAT = timedelta(minutes=20)
#: The board's own settings, relative to the job's working directory.
DFLT_BOARD_JSON = Path("board") / "board.json"
#: After a failed check starts a session, the next one waits this long, doubling with
#: each further failure up to :data:`FAIL_OPEN_CAP`: a lasting fault must not start a
#: paid session every tick, all day.
FAIL_OPEN_BACKOFF = timedelta(hours=1)
FAIL_OPEN_CAP = timedelta(hours=6)
_TIMEOUT = 20
_REQUIRED = ("BOARD_ORIGIN", "BOARD_API", "BOARD_EMAIL", "BOARD_PASSWORD")
_LOOPBACK_NAMES = {"localhost"}


class ConfigError(RuntimeError):
    """The check cannot run as configured, and a session could not fix that either."""


class Pending(list):
    """The reasons the receiver is needed; empty means nothing to do.

    ``total`` counts the items behind those reasons (the heartbeat's ``pending``);
    ``heartbeat`` says what :func:`check` did with the heartbeat.
    """

    total: int = 0
    heartbeat: str = ""
    #: The ids behind the reasons, so a start that would see the same set again backs off.
    keys: frozenset = frozenset()
    #: Another receiver whose heartbeat is live: a session started now would stop at once.
    other_live: str | None = None


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
    retry_after: timedelta = RETRY_AFTER,
) -> Pending:
    """What needs the receiver, from the store's two collections (``id -> data``).

    ``queued`` and transiently ``failed`` receipts count only once their ``at`` (or,
    lacking one, ``claimedAt``) is older than *retry_after*; one with neither counts.

    >>> pending_work({'e1': {}}, {})
    ['1 event(s) without a receipt']
    >>> pending_work({'e1': {}}, {'e1': {'status': 'posted'}})
    []
    """
    now = now or datetime.now(timezone.utc)

    def due(rec: Mapping[str, Any]) -> bool:
        when = _when(rec.get("at") or rec.get("claimedAt"))
        return when is None or now - when >= retry_after

    reasons = Pending()
    unreceived = [e for e in outbox if e not in receipts]
    if unreceived:
        reasons.append(f"{len(unreceived)} event(s) without a receipt")

    stale = queued = transient = 0
    due_ids: list[str] = []
    for key, rec in receipts.items():
        status = rec.get("status")
        result = rec.get("result") or {}
        hit = False
        if status == "processing":
            claimed = _when(rec.get("claimedAt"))
            hit = claimed is None or now - claimed > STALE_CLAIM
            stale += hit
        elif status == "queued":
            hit = due(rec)
            queued += hit
        elif status == "failed" and result.get("transient"):
            hit = due(rec)
            transient += hit
        if hit:
            due_ids.append(key)
    for count, what in (
        (stale, "stale claim(s)"),
        (queued, "queued receipt(s) due a retry"),
        (transient, "transient failure(s) to retry"),
    ):
        if count:
            reasons.append(f"{count} {what}")
    reasons.total = len(unreceived) + stale + queued + transient
    reasons.keys = frozenset(unreceived) | frozenset(due_ids)
    return reasons


def _checked_origin(origin: str) -> str:
    """The origin, refused if it would send the password in clear to another host.

    >>> _checked_origin('https://example.org/')
    'https://example.org'
    >>> _checked_origin('http://127.0.0.1:8000')
    'http://127.0.0.1:8000'
    >>> _checked_origin('http://example.org')  # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    openloops.receiver_tick.ConfigError: BOARD_ORIGIN http://example.org is not https...
    """
    origin = origin.rstrip("/")
    parts = urllib.parse.urlsplit(origin)
    if parts.scheme == "https":
        return origin
    host = parts.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host in _LOOPBACK_NAMES
    if parts.scheme == "http" and loopback:
        return origin
    raise ConfigError(
        f"BOARD_ORIGIN {origin} is not https: the password would travel in clear"
    )


class _Store:
    """The board store API over HTTP, signed in as the receiver's own account."""

    def __init__(self, env: Mapping[str, str], jar_path: Path):
        self.origin = _checked_origin(env["BOARD_ORIGIN"])
        self.api = "/" + env["BOARD_API"].strip("/")
        self.env = env
        self.jar = http.cookiejar.MozillaCookieJar(str(jar_path))
        if jar_path.exists():
            try:
                self.jar.load(ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError):
                pass
        #: With no saved session, sign in before the first call rather than waiting
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
        try:
            self._open(req)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ConfigError(
                    f"sign-in refused ({exc.code}): check the credentials"
                )
            raise
        self.has_session = True
        old = os.umask(0o077)  # the jar holds a session: never readable by others
        try:
            self.jar.save(ignore_discard=True, ignore_expires=True)
            os.chmod(self.jar.filename, 0o600)
        except OSError:
            pass
        finally:
            os.umask(old)

    def _request(self, make: Callable[[], urllib.request.Request]) -> bytes:
        """Open ``make()``, signing in again once on a 401. A 403 after a fresh sign-in
        means the account lacks the ``receiver`` role: a configuration error."""
        if not self.has_session:
            self.sign_in()
        for attempt in (0, 1):
            try:
                return self._open(make())
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403) and attempt == 0:
                    self.sign_in()
                    continue
                if exc.code == 403:
                    raise ConfigError("the board store refused this account (403)")
                raise
        raise RuntimeError("unreachable")

    def _url(self, *parts: str) -> str:
        return "/".join([f"{self.origin}{self.api}", *parts])

    def collection(self, name: str) -> dict[str, Any]:
        url = self._url(name)
        docs = json.loads(self._request(lambda: urllib.request.Request(url)))["docs"]
        return {d["id"]: d["data"] for d in docs}

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        """One document (``{id, data, version}``), or ``None`` if there is none."""
        url = self._url(collection, doc_id)
        try:
            return json.loads(self._request(lambda: urllib.request.Request(url)))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def put(
        self, collection: str, doc_id: str, data: Mapping, *, version: str | None
    ) -> bool:
        """Write pinned to *version* (``None``: create-if-absent). ``False`` on a 412."""
        url = self._url(collection, doc_id)
        pin = {"If-Match": version} if version else {"If-None-Match": "*"}
        headers = {"Content-Type": "application/json", **pin}
        body = json.dumps(data).encode()
        try:
            self._request(
                lambda: urllib.request.Request(
                    url, data=body, method="PUT", headers=headers
                )
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                return False
            raise
        return True


def _session_name(board_json: Path) -> str | None:
    try:
        return json.loads(board_json.read_text(encoding="utf-8")).get("session")
    except (OSError, ValueError, AttributeError):
        return None


def _heartbeat(store: _Store, by: str, reasons: Pending, *, now: datetime) -> str:
    """Write ``meta/receiver`` when nothing is pending, unless another live receiver
    owns it (then ``reasons.other_live`` names it). Says what it did.

    With work pending it never writes: the session does, so a session that cannot run
    (an expired login, a refused tool) leaves the board amber instead of a green lie.
    """
    current = store.get("meta", "receiver") or {}
    data = current.get("data") or {}
    stamp = _when(data.get("at"))
    owner = data.get("by")
    # An unreadable stamp from another receiver is treated as live: never overwrite it.
    if owner not in (None, by) and (stamp is None or now - stamp < LIVE_HEARTBEAT):
        reasons.other_live = str(owner)
        return f"heartbeat left alone: {owner} is live"
    if reasons:
        return "heartbeat left to the session: work is pending"
    beat = {
        "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by": by,
        "processed": data.get("processed", 0),  # the last sweep's count, kept
        "pending": reasons.total,
    }
    written = store.put("meta", "receiver", beat, version=current.get("version"))
    return "heartbeat written" if written else "heartbeat skipped: a sweep wrote it"


def check(
    env_file: str | Path = DFLT_ENV_FILE,
    *,
    heartbeat_by: str | None = None,
    now: datetime | None = None,
) -> Pending:
    """Ask the store whether anything needs the receiver. Raises if it cannot ask:
    :class:`ConfigError` when no session could fix it, anything else otherwise.

    With *heartbeat_by* (the board's session name) it also writes the ``meta/receiver``
    heartbeat, and says what happened in the result's ``heartbeat``. A failed heartbeat
    never fails the check: the board turning amber is how that shows.
    """
    path = Path(env_file).expanduser()
    if not path.is_file():
        raise ConfigError(f"{env_file} does not exist")
    env = read_env_file(path)
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ConfigError(f"{env_file} lacks {', '.join(missing)}")
    now = now or datetime.now(timezone.utc)
    store = _Store(env, path.with_name("board-receiver.cookies"))
    reasons = pending_work(
        store.collection("outbox"), store.collection("receipts"), now=now
    )
    reasons.heartbeat = "heartbeat skipped: no session name in board/board.json"
    if heartbeat_by:
        try:
            reasons.heartbeat = _heartbeat(store, heartbeat_by, reasons, now=now)
        except Exception as exc:  # the check answered; the heartbeat is secondary
            reasons.heartbeat = f"heartbeat failed: {type(exc).__name__}: {exc}"
    return reasons


def _backoff_wait(failures: int) -> timedelta:
    """How long after the last fail-open start the next one may come.

    >>> [_backoff_wait(n).total_seconds() / 3600 for n in (1, 2, 3, 4, 9)]
    [1.0, 2.0, 4.0, 6.0, 6.0]
    """
    return min(FAIL_OPEN_BACKOFF * 2 ** max(failures - 1, 0), FAIL_OPEN_CAP)


def _read_failures(stamp: Path) -> int:
    """Sessions started for the current run of failures (0: none, or no stamp)."""
    try:
        return int(json.loads(stamp.read_text(encoding="utf-8"))["failures"])
    except (OSError, ValueError, KeyError, TypeError):
        return 1 if stamp.exists() else 0


def _same_work_too_soon(
    stamp: Path, keys: frozenset, *, now: float | None = None
) -> bool:
    """Back off when a session would start for exactly the work the last one left.

    A session that ran but changed nothing (it hit its budget, a command was refused)
    would otherwise be restarted every tick for the same events. Different work starts
    at once; the same work waits 1h, 2h, 4h, then every 6h. Records this start.

    >>> import tempfile, pathlib
    >>> s = pathlib.Path(tempfile.mkdtemp()) / 'w'
    >>> _same_work_too_soon(s, frozenset({'e1'}), now=0)
    False
    >>> _same_work_too_soon(s, frozenset({'e1'}), now=60)
    True
    >>> _same_work_too_soon(s, frozenset({'e2'}), now=120)
    False
    """
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    sig = hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest()[:16]
    try:
        last = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    starts = int(last.get("starts", 0)) if last.get("sig") == sig else 0
    if (
        starts
        and now - float(last.get("at", 0)) < _backoff_wait(starts).total_seconds()
    ):
        print(
            f"same pending work as the last {starts} session(s); next try after "
            f"{_backoff_wait(starts).total_seconds() / 3600:g}h",
            file=sys.stderr,
        )
        return True
    try:
        stamp.write_text(
            json.dumps({"sig": sig, "at": now, "starts": starts + 1}), encoding="utf-8"
        )
    except OSError:
        pass
    return False


_USAGE = (
    "usage: python -m openloops.receiver_tick [--check-only] [--env-file FILE] "
    "[--board-json FILE] [-- COMMAND ...]\n"
    "Asks the board store, with no model, whether the receiver has work, and writes "
    "the board's heartbeat. If there is work, or the check failed for a reason a "
    "session might get past (with an exponential back-off), replaces itself with "
    "COMMAND. A configuration error starts nothing."
)


def _option(args: list[str], name: str, default: Path) -> Path | None:
    if name not in args:
        return default
    at = args.index(name) + 1
    return Path(args[at]) if at < len(args) else None


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
    check_only = "--check-only" in args or not command
    env_file = _option(args, "--env-file", DFLT_ENV_FILE)
    board_json = _option(args, "--board-json", DFLT_BOARD_JSON)
    if env_file is None or board_json is None:
        print("--env-file and --board-json need a path", file=sys.stderr)
        return 2
    here = env_file.expanduser()
    stamp = here.with_name("board-receiver.failopen")
    same_work = here.with_name("board-receiver.lastwork")
    last_check = here.with_name("board-receiver.lastcheck")

    failure = None
    try:
        reasons = check(env_file, heartbeat_by=_session_name(board_json))
    except ConfigError as exc:
        print(
            f"receiver check MISCONFIGURED, no session started: {exc}",
            file=sys.stdout if check_only else sys.stderr,
        )
        return 2
    except Exception as exc:  # fail open: see the module docstring
        reasons, failure = Pending(), f"{type(exc).__name__}: {exc}"

    if check_only:
        if failure:
            print(f"check failed ({failure}); a tick would start the receiver anyway")
            return 1
        print("pending: " + ("; ".join(reasons) if reasons else "nothing"))
        print(reasons.heartbeat)
        return 0
    if failure:
        failures = _read_failures(stamp)
        try:
            since = datetime.now(timezone.utc).timestamp() - stamp.stat().st_mtime
        except OSError:
            since = None
        wait = _backoff_wait(failures)
        if failures and since is not None and since < wait.total_seconds():
            print(
                f"receiver check still failing ({failure}); {failures} session(s) "
                f"started for it already, the next after "
                f"{wait.total_seconds() / 3600:g}h, waiting",
                file=sys.stderr,
            )
            return 1
        print(f"receiver check failed, starting anyway: {failure}", file=sys.stderr)
        try:
            stamp.write_text(json.dumps({"failures": failures + 1}), encoding="utf-8")
        except OSError:
            pass
    else:
        try:
            stamp.unlink()
        except OSError:
            pass
        try:
            last_check.touch()
        except OSError:
            pass
        if reasons.heartbeat.startswith("heartbeat skipped: no session"):
            print(
                f"receiver: {reasons.heartbeat}; the board will show amber",
                file=sys.stderr,
            )
        if not reasons:
            return 0  # idle: say nothing, so the log is touched only by ticks with work
        if reasons.other_live:
            print(
                f"pending, but {reasons.other_live} is the live receiver; not starting",
                file=sys.stderr,
            )
            return 0
        if _same_work_too_soon(same_work, reasons.keys):
            return 0
        print("pending: " + "; ".join(reasons), file=sys.stderr)
    try:
        os.execv(command[0], command)
    except OSError as exc:
        print(f"cannot start {command[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 127
    return 0  # pragma: no cover - execv does not return


if __name__ == "__main__":
    raise SystemExit(main())
