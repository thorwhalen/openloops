"""What you still owe your agents — re-checked against the world before it is shown.

When an agent gets blocked on something only you can do — a secret it cannot write, a
permission it does not have, a decision that is yours — it files a `manual-task` issue
in the affected repo and says so in its closing message. The closing message dies with
the session. The issue does not, and one query lists every one of them across a fleet.

That query has one failure mode, and it is the one that matters: **obligations get
discharged out of band.** Someone adds a deploy key in a web UI, pays an invoice,
answers in chat. None of that emits an event anyone is listening to, so the issue sits
open for months describing something that was done in five minutes. A stale increment
annoys; a phantom row destroys the count, and the count is the product.

So each obligation carries its own answer, in its body, as a shell command whose **exit
status is the question**::

    **Verify:** `gh secret list --repo OWNER/REPO --json name -q '.[].name' | grep -qx NAME`

:func:`owed` lists the open ones, runs each predicate, and reports **three** states —
never two:

===============  ==============================================================
``open``         no predicate at all, or the predicate ran and returned non-zero
``discharged``   the predicate ran and returned ``0``: the ask is done, the issue
                 is merely still open
``unknown``      the predicate could *not* be run, or errored in a way that is not
                 an answer. Displayed as ``?``
===============  ==============================================================

``?`` is not a rounding error, it is the whole point. A surface that says "nothing
owed" because it failed to check is worse than no surface at all, so nothing here is
ever allowed to collapse ``unknown`` into ``open`` or into ``discharged``.

**Nothing here mutates anything.** A passing predicate is evidence, not authority: it
never closes, reopens or relabels an issue, and it never will — the standing rule is
that a human obligation is not closed on a model's judgement. You are shown the
command, its exit status and what it printed, and you decide.

Trust boundary — stated here because it should be read, not discovered
---------------------------------------------------------------------

Evaluating a predicate means **executing text that came from a GitHub issue body**.
That is a real capability and it is bounded here in five ways, each of them visible:

1. **Only owners you named.** A predicate is run only when the issue's repository owner
   is in ``trusted_owners=``, which defaults to the same ``owners=`` the search was
   scoped to. A row outside that set reads ``?`` — never ``open``, because nothing
   checked it, and never ``discharged``, because nothing ran.
2. **The command is always shown next to its verdict.** Every row carries the predicate
   verbatim, so nothing executes invisibly and you can disagree with the answer.
3. **An explicit way not to execute at all.** ``owed(verify=False)`` (``ol owed
   --no-verify``) lists without running anything; every row that has a predicate then
   reads ``?``, because that is the truth about it.
4. **Every evaluation is time-bounded**, by ``predicate_timeout=``. A timeout is
   ``unknown``, never an answer. On POSIX the predicate runs in its own process group
   and the timeout kills the group, so anything it started dies with it. On Windows only
   the shell itself is killed — a predicate that backgrounds work can outlive its
   timeout there, which is a platform limit worth knowing rather than a promise broken
   quietly.
5. **The whole thing is one keyword argument away from being someone else's code.**
   ``run_predicate=`` replaces the evaluator; ``issues_source=`` replaces the reader.

One honest limit: predicates are POSIX shell. On a shell that cannot parse one, the
command exits non-zero and the row reads ``open``. That is the safe direction to be
wrong in — a stale increment annoys, a wrong decrement destroys the count — and it is
why the exit status and the command text are always on screen.

**Kill criterion** (this module ships on an argument, so it names in advance what would
retire it): if, ninety days after this ships, ``counts['with_predicate']`` is below half
of ``counts['total']`` on a normal run, or nobody has run ``ol owed`` in a fortnight,
delete it. Its entire reason to exist over a one-line ``gh search issues`` alias is the
predicate; with no predicates to run it is a slower alias that draws a table. Removal is
one command — delete this module and ``tests/test_obligations.py``, and drop ``owed``
from ``openloops.tools._dispatch_funcs`` and ``openloops.__main__._commands``. Nothing
imports it, nothing persists, and no other module changes.

**What this is not.** It is a *reader*. There is no store, no schema, no history, no
event log, no cross-repo linking, no session model and no local copy of anything: the
`manual-task` label **is** the record, and a second writable home for the same record
type is the drift this deliberately does not build. State lives in first-class GitHub
fields that a plain ``gh`` command can query, so deleting this module loses no data.

    >>> from datetime import datetime, timezone
    >>> issues = [
    ...     {'number': 7, 'title': 'Add a deploy key so CI can clone',
    ...      'url': 'https://github.com/acme/widget/issues/7',
    ...      'createdAt': '2026-08-01T00:00:00Z',
    ...      'repository': {'nameWithOwner': 'acme/widget'},
    ...      'body': '**Verify:** `[ "$(gh api repos/acme/widget/keys --jq length)" -gt 0 ]`'},
    ...     {'number': 8, 'title': 'Decide whether to publish this at all',
    ...      'url': 'https://github.com/acme/widget/issues/8',
    ...      'createdAt': '2026-08-10T00:00:00Z',
    ...      'repository': {'nameWithOwner': 'acme/widget'},
    ...      'body': '**Verify:** none possible - a judgement call.'},
    ... ]
    >>> report = owed(
    ...     issues_source=issues,               # a list of dicts: no gh, no network
    ...     run_predicate=lambda command: 0,    # canned: the ask turns out to be done
    ...     trusted_owners=('acme',),
    ...     now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    ... )
    >>> report['counts']['discharged'], report['counts']['open']
    (1, 1)
    >>> for row in report['rows']:
    ...     print(row['state'], row['age_days'], f"{row['repo']}#{row['number']}")
    open 10 acme/widget#8
    discharged 19 acme/widget#7

The discharged row is reported, not closed:

    >>> report['rows'][1]['predicate']
    '[ "$(gh api repos/acme/widget/keys --jq length)" -gt 0 ]'

An owner you did not name is never executed, and never silently believed:

    >>> quiet = owed(issues_source=issues, run_predicate=lambda command: 0,
    ...              trusted_owners=(), now=datetime(2026, 8, 20, tzinfo=timezone.utc))
    >>> [(row['number'], row['state']) for row in quiet['rows']]
    [(8, 'open'), (7, 'unknown')]
    >>> next(r['evidence'] for r in quiet['rows'] if r['number'] == 7)
    "not evaluated: owner 'acme' is not in trusted_owners"
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any

from openloops.base import OPEN

__all__ = [
    "DISCHARGED",
    "OBLIGATION_FIELDS",
    "OBLIGATION_STATES",
    "UNKNOWN",
    "GhUnavailable",
    "Obligation",
    "PredicateOutcome",
    "configured_owners",
    "gh_issues",
    "owed",
    "parse_verify",
    "shell_predicate",
]

#: The predicate ran and returned 0. The ask is done; the issue is just still open.
DISCHARGED = "discharged"
#: Nothing could be checked. Rendered ``?``. Never collapsed into either other state.
UNKNOWN = "unknown"
#: The three states, in the order a reader cares about them. ``open`` is
#: :data:`openloops.base.OPEN`: a loop that is still open is the same idea either way.
OBLIGATION_STATES = (OPEN, DISCHARGED, UNKNOWN)

#: The fleet-wide label whose meaning is "an agent cannot proceed without the human".
#: The label *is* the record — there is no second copy of it anywhere in openloops.
DFLT_LABEL = "manual-task"
#: How many rows to ask for. One more than this is actually requested, so that a result
#: set which saturates its own cap is *reported* rather than silently truncated.
DFLT_LIMIT = 50
#: Seconds allowed for the listing call.
DFLT_LIST_TIMEOUT = 30.0
#: Seconds allowed for one predicate. A predicate is a `gh` call or a `curl`; anything
#: slower than this is a hung network, and a hung network is ``unknown``, not an answer.
DFLT_PREDICATE_TIMEOUT = 20.0
#: How much of a predicate's own output is kept as evidence. Enough to see what it saw.
DFLT_EVIDENCE_CHARS = 400
#: Environment override for the owners to search, comma- or space-separated.
OWNERS_ENV_VAR = "OPENLOOPS_OWNERS"

#: The issue fields the listing asks for. ``body`` is here because the predicate lives
#: in it; everything else is what a reader needs to act on the row.
_ISSUE_FIELDS = ("createdAt", "number", "repository", "title", "url", "body")

_SECONDS_PER_DAY = 86400.0


class GhUnavailable(RuntimeError):
    """The world could not be read: no ``gh``, no credentials, no network, a timeout.

    Raised only by the listing path, and never propagated to a caller of :func:`owed` —
    it becomes ``listed: False`` plus an ``error``, which every surface must render as
    ``?``. Turning it into an empty list would be the one unrecoverable bug here.
    """


@dataclass(frozen=True)
class PredicateOutcome:
    """What evaluating one predicate produced.

    ``status`` is the shell exit status, or ``None`` for "could not be run" — the
    difference between an answer and the absence of one.

    >>> PredicateOutcome(0).status, PredicateOutcome(None, 'timed out').output
    (0, 'timed out')
    """

    status: int | None
    output: str = ""


@dataclass(frozen=True)
class Obligation:
    """One open `manual-task` issue, with the verdict its own predicate returned.

    ``verify`` is the ``**Verify:**`` field exactly as the issue wrote it and
    ``predicate`` is the runnable command extracted from it — both are carried so a
    reader can disagree with ``state`` rather than absorb it.

    >>> Obligation('acme/widget', 7, 't', 'u', '2026-01-01T00:00:00Z', 3).state
    'open'
    """

    repo: str
    number: int
    title: str
    url: str
    created: str
    age_days: int
    state: str = OPEN
    verify: str = ""
    predicate: str = ""
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return asdict(self)


#: Every key on every row, whatever the issue happened to say. A row shape that varies
#: by issue makes ``row["predicate"]`` a coin flip and makes a JSON schema a lie.
OBLIGATION_FIELDS = tuple(f.name for f in fields(Obligation))


# --------------------------------------------------------------------------------
# Reading the world: the one place openloops invokes `gh`.
# --------------------------------------------------------------------------------


def _gh(args: Sequence[str], *, timeout: float) -> str:
    """Run one ``gh`` command and return its stdout. The only shell-out in the package.

    openloops owns no GitHub client state — no token handling, no HTTP client, no cache
    of its own — and a subprocess call to a CLI the user already authenticated is what
    satisfies that. Keeping it to one function is what makes the claim checkable.

    Every way this can fail is one failure: :class:`GhUnavailable`, which upstream turns
    into ``?``.
    """
    executable = shutil.which("gh")
    if executable is None:
        raise GhUnavailable(
            "the `gh` CLI is not on PATH — install it and run `gh auth login`"
        )
    try:
        done = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise GhUnavailable(f"`gh {args[0]}` timed out after {timeout:g}s") from None
    except OSError as exc:
        raise GhUnavailable(f"could not run `gh`: {exc}") from None
    if done.returncode != 0:
        detail = _first_line(done.stderr) or f"`gh` exited {done.returncode}"
        raise GhUnavailable(detail)
    return done.stdout


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def configured_owners(*, timeout: float = DFLT_LIST_TIMEOUT) -> tuple[str, ...]:
    """Whose repositories to search, resolved once.

    Three sources, in order, first one wins: ``OPENLOOPS_OWNERS`` (comma- or
    space-separated); the owners named by the ``gh owe`` alias if one is installed,
    because a fleet is usually already written down there and disagreeing with it is
    how a count goes quietly wrong; and failing both, the login ``gh`` is authenticated
    as. The resolved list is reported back on every result, so a partial answer is a
    visible one rather than a silent one.

    >>> import os
    >>> os.environ['OPENLOOPS_OWNERS'] = 'acme, widgets co'
    >>> configured_owners()
    ('acme', 'widgets', 'co')
    >>> del os.environ['OPENLOOPS_OWNERS']
    """
    raw = os.environ.get(OWNERS_ENV_VAR, "")
    named = tuple(part for part in re.split(r"[,\s]+", raw) if part)
    if named:
        return named
    from_alias = owners_in_gh_alias(timeout=timeout)
    if from_alias:
        return from_alias
    login = _gh(["api", "user", "--jq", ".login"], timeout=timeout).strip()
    if not login:
        raise GhUnavailable(
            f"no owners to search: set {OWNERS_ENV_VAR} or run `gh auth login`"
        )
    return (login,)


#: Where a fleet's owners are already written down, if the read-path alias is installed.
DFLT_OWE_ALIAS = "owe"

#: `--owner X` as `gh` itself spells it, in either the flag or the `flag=value` form.
_ALIAS_OWNER = re.compile(r"--owner[= ]+(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)")


def owners_in_gh_alias(
    *, alias: str = DFLT_OWE_ALIAS, timeout: float = DFLT_LIST_TIMEOUT
) -> tuple[str, ...]:
    """The owners named by a `gh` alias, or ``()`` when there is no such alias.

    A fleet of several organisations is usually already written down once, in the alias
    that reads it. Deriving from that rather than from the authenticated login is what
    stops this command from quietly answering about one owner when the alias -- the
    thing the human actually types -- answers about three. A silently partial count is
    the failure this module exists to prevent, so the partial default is the wrong one.

    >>> owners_in_gh_alias(alias='no-such-alias-here')
    ()
    """
    try:
        listing = _gh(["alias", "list"], timeout=timeout)
    except GhUnavailable:
        return ()
    for line in listing.splitlines():
        name, _, expansion = line.partition("\t")
        if not expansion:
            name, _, expansion = line.partition(":")
        if name.strip() == alias:
            found = _ALIAS_OWNER.findall(expansion)
            # dict.fromkeys keeps the alias's own order, which is the order the human
            # reads them in, and drops a repeat rather than searching it twice.
            return tuple(dict.fromkeys(found))
    return ()


def gh_issues(
    *,
    owners: Sequence[str],
    label: str = DFLT_LABEL,
    state: str = "open",
    limit: int = DFLT_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
) -> list[dict[str, Any]]:
    """The default ``issues_source``: the open `manual-task` issues, from ``gh``.

    This is a *filtered* search, not an enumeration — the label is applied server-side
    and the result is capped — which is the only form of search this package is allowed
    to use. Walking a whole fleet's issues through the search API silently returns wrong
    answers past its first thousand results; that job belongs to per-repo listing.

    Returns whatever ``gh`` returned, unparsed and unjudged: a list of dicts with
    ``createdAt``, ``number``, ``repository``, ``title``, ``url`` and ``body``.
    """
    if not owners:
        raise GhUnavailable(f"no owners to search: set {OWNERS_ENV_VAR}")
    args = ["search", "issues"]
    for owner in owners:
        args += ["--owner", owner]
    args += [
        "--label",
        label,
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        ",".join(_ISSUE_FIELDS),
    ]
    payload = _gh(args, timeout=timeout)
    try:
        rows = json.loads(payload or "[]")
    except ValueError as exc:
        raise GhUnavailable(
            f"`gh search issues` returned no usable JSON: {exc}"
        ) from None
    if not isinstance(rows, list):
        raise GhUnavailable("`gh search issues` returned something other than a list")
    return rows


# --------------------------------------------------------------------------------
# Reading the predicate out of an issue body.
# --------------------------------------------------------------------------------

#: How long to wait for a killed predicate's process group to be reaped.
DFLT_REAP_TIMEOUT = 2.0

#: The capture skill's field: ``**Verify:** <text>``. The bold markers are optional so
#: that a hand-written issue is read too — the field is the contract, not its markup.
_VERIFY_FIELD = re.compile(
    r"^[ \t>]*(?:\*\*)?Verify(?:\*\*)?\s*:(?:\*\*)?[ \t]*(?P<text>.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

#: A markdown code span, with however many backticks it opened with.
_CODE_SPAN = re.compile(r"(?P<ticks>`+)(?P<code>.+?)(?P=ticks)", re.DOTALL)

#: A fenced block, ``` or ~~~, however many fence characters it opened with.
_FENCED_BLOCK = re.compile(r"^[ \t]*(?P<fence>```+|~~~+).*?^[ \t]*(?P=fence)[ \t]*$",
                           re.DOTALL | re.MULTILINE)

#: Text the capture skill's own documentation of the field is quoted in. An agent that
#: pastes the spec into its `<details>What I found</details>` must not have the spec's
#: example run instead of its own predicate — so quoted code is not a contract.
def _without_quoted_code(body: str) -> str:
    """The body with fenced and indented code blocks blanked out, lines preserved.

    Blanking rather than deleting keeps every other line where it was, so the field is
    still found at the same place in a body that happens to quote the format.

    >>> body = chr(10).join(["```", "**Verify:** `quoted`", "```", "**Verify:** `real`"])
    >>> _without_quoted_code(body).splitlines()
    ['', '', '', '**Verify:** `real`']
    """

    def blank(match: re.Match) -> str:
        return "\n" * match.group(0).count("\n")

    body = _FENCED_BLOCK.sub(blank, body)
    # An indented code block is four spaces or a tab at the start of a line. The field
    # itself is never indented that far in the documented format.
    return "\n".join(
        "" if (line.startswith("    ") or line.startswith("\t")) else line
        for line in body.split("\n")
    )


#: The documented way to say a predicate is impossible. Everything after it is prose,
#: and prose containing a code span (`gh`, `true`) must never be executed -- `gh` with no
#: arguments exits 0, which would mark a live obligation DONE. That is the phantom
#: discharge this whole module exists to prevent, so it is checked first and by prefix.
_NO_PREDICATE_PREFIXES = ("none possible", "none", "n/a", "no predicate", "not possible")


def parse_verify(body: str) -> tuple[str, str]:
    """``(predicate, verify_text)`` for an issue body. Both are ``''`` when absent.

    The predicate is the first code span in the field. Prose with no code span -- the
    documented "no predicate is possible here" answer -- yields no command, and the
    prose is kept so the row can say *why* rather than merely say nothing.

    >>> parse_verify('**Verify:** `test -f x`')
    ('test -f x', '`test -f x`')
    >>> parse_verify('no such field here')
    ('', '')

    A field that says no predicate is possible yields no command **even when its prose
    contains a code span** -- the documented wording mentions `gh` and `true` naturally,
    and both exit 0, which would report a live obligation as done:

    >>> parse_verify('**Verify:** none possible - no `gh` query observes a decision.')
    ('', 'none possible - no `gh` query observes a decision.')

    A quoted example of the format is not this issue's own predicate:

    >>> body = chr(10).join(['```', '**Verify:** `quoted`', '```', '**Verify:** `real`'])
    >>> parse_verify(body)[0]
    'real'

    An unterminated code span is not a command -- it is a malformed field, and saying so
    is the difference between a row that reads ``?`` and one that silently reads open:

    >>> parse_verify('**Verify:** `echo one &&' + chr(10) + 'echo two`')
    ('', '`echo one &&')
    """
    match = _VERIFY_FIELD.search(_without_quoted_code(body or ""))
    if match is None:
        return "", ""
    text = match.group("text").strip()
    if text.lower().lstrip("*_ ").startswith(_NO_PREDICATE_PREFIXES):
        return "", text
    span = _CODE_SPAN.search(text)
    command = span.group("code").strip() if span else ""
    return command, text


# --------------------------------------------------------------------------------
# Evaluating it.
# --------------------------------------------------------------------------------


def shell_predicate(
    command: str, *, timeout: float = DFLT_PREDICATE_TIMEOUT
) -> PredicateOutcome:
    """The default ``run_predicate``: run the command in a subshell, bounded in time.

    The exit status is the answer and nothing else is interpreted. Anything that is not
    an exit status — a timeout, a shell that would not start — comes back as
    ``status=None``, which is ``unknown``, which is ``?``.

    >>> shell_predicate('exit 0').status
    0
    >>> shell_predicate('exit 3').status
    3
    >>> shell_predicate('   ').status is None
    True
    """
    if not (command or "").strip():
        return PredicateOutcome(None, "no predicate to run")
    # A new session puts the shell and everything it spawns in one process group, so the
    # timeout can kill the group rather than the shell alone. Without it a backgrounded
    # child outlives the timeout, keeps the captured pipe open, and both leaks a process
    # and turns an answered predicate into a false `unknown`. Measured, not assumed.
    popen_kwargs: dict[str, Any] = {}
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):  # pragma: no cover - Windows
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    # Output goes to files rather than pipes on purpose. With pipes, waiting means
    # waiting for EOF, and a backgrounded child inherits the write end -- so
    # `sleep 8 & exit 0` blocks the full timeout and an ANSWERED predicate comes back
    # as `unknown`. Files let us wait on the shell itself and read whatever it left.
    # `ignore_cleanup_errors` is load-bearing on Windows: a killed child can still
    # hold the output file when the block exits, and an un-ignored cleanup raises
    # PermissionError out of what is supposed to be a bounded, total evaluation.
    with tempfile.TemporaryDirectory(
        prefix="openloops-predicate-", ignore_cleanup_errors=True
    ) as scratch:
        out_path = os.path.join(scratch, "out")
        err_path = os.path.join(scratch, "err")
        try:
            with open(out_path, "wb") as out_file, open(err_path, "wb") as err_file:
                process = subprocess.Popen(  # noqa: S602 - running it IS the job
                    command,
                    shell=True,
                    stdout=out_file,
                    stderr=err_file,
                    stdin=subprocess.DEVNULL,
                    **popen_kwargs,
                )
        except OSError as exc:
            return PredicateOutcome(None, f"the predicate could not be run: {exc}")
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            return PredicateOutcome(None, f"the predicate timed out after {timeout:g}s")
        out = _read_text(out_path)
        err = _read_text(err_path)
    return PredicateOutcome(status, _evidence(out, err))


def _read_text(path: str) -> str:
    """Whatever a predicate wrote, decoded leniently. Unreadable reads as nothing."""
    try:
        with open(path, "rb") as stream:
            return stream.read().decode("utf-8", errors="replace")
    except OSError:  # pragma: no cover - the temp dir was ours a moment ago
        return ""


def _kill_group(process: subprocess.Popen) -> None:
    """Kill the predicate and everything it started, then reap it."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:  # pragma: no cover - Windows
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):  # pragma: no cover
        process.kill()
    try:
        process.wait(timeout=DFLT_REAP_TIMEOUT)
    except Exception:  # noqa: BLE001 - pragma: no cover - best effort reap
        pass


def _evidence(*chunks: str) -> str:
    """What a predicate printed, flattened to one bounded line-ish blob."""
    text = "\n".join(chunk.strip() for chunk in chunks if (chunk or "").strip())
    text = " ".join(text.split())
    if len(text) > DFLT_EVIDENCE_CHARS:
        text = text[: DFLT_EVIDENCE_CHARS - 3] + "..."
    return text


def _as_outcome(value: Any) -> PredicateOutcome:
    """Normalise whatever a ``run_predicate`` returned.

    An injected evaluator is allowed to be as small as ``lambda command: 0``, or as
    small as ``{'cmd': 0}.get`` — a mapping's ``get`` is already a callable of the right
    shape, and an unknown command returning ``None`` already means ``unknown``.

    >>> _as_outcome(0), _as_outcome(None).status, _as_outcome((2, 'nope')).output
    (PredicateOutcome(status=0, output=''), None, 'nope')
    """
    if isinstance(value, PredicateOutcome):
        return value
    if value is None:
        return PredicateOutcome(None, "the predicate returned no exit status")
    if isinstance(value, bool):
        # `True` reads as "done" to a caller and as exit status 1 -- "not done" -- to a
        # shell. There is no safe coercion, so refuse rather than invert the product.
        raise TypeError(
            "run_predicate returned a bool; an exit status is expected, where 0 means "
            "done. Return 0 or 1 explicitly rather than True or False."
        )
    if isinstance(value, int):
        return PredicateOutcome(int(value))
    if isinstance(value, Sequence) and len(value) == 2:
        status, output = value
        return PredicateOutcome(None if status is None else int(status), str(output))
    raise TypeError(
        f"run_predicate returned {type(value).__name__}; expected an exit status, "
        "None, a (status, output) pair, or a PredicateOutcome"
    )


#: Exit statuses a POSIX shell reserves for "I could not run that", not for an answer.
#: 126 is found-but-not-executable, 127 is not-found, and >128 is death by signal.
NOT_AN_ANSWER_STATUSES = frozenset({126, 127})

#: Stderr shapes that mean the check itself failed rather than the ask being undone.
#: A predicate that cannot authenticate has not observed the world at all, and reading
#: it as "still open" is a false positive on the one number this module publishes.
NOT_AN_ANSWER_STDERR = (
    "command not found",
    "not found",
    "bad credentials",
    "authentication failed",
    "gh auth login",
    "could not resolve host",
    "network is unreachable",
    "connection refused",
    "temporary failure in name resolution",
    "syntax error",
    "permission denied",
    "http 401",
    "http 403",
)


def not_an_answer(status: int, output: str) -> str:
    """Why ``status`` is not an answer about the world, or ``''`` when it is one.

    A predicate exits non-zero for two very different reasons: the ask is not done, or
    the check could not run. Only the first is information. Collapsing them means that
    on a machine with no ``gh``, or with an expired token, every row reads *open* and
    the tool prints a confident count it did not earn.

    >>> not_an_answer(127, '/bin/sh: nope: command not found')
    'exit 127: the predicate could not be run'
    >>> not_an_answer(1, 'HTTP 401: Bad credentials')
    'exit 1: the check itself failed, so nothing was observed'
    >>> not_an_answer(1, 'no such secret')
    ''
    >>> not_an_answer(0, 'anything')
    ''
    """
    if status == 0:
        return ""
    if status in NOT_AN_ANSWER_STATUSES or status > 128:
        return f"exit {status}: the predicate could not be run"
    lowered = (output or "").lower()
    if any(shape in lowered for shape in NOT_AN_ANSWER_STDERR):
        return f"exit {status}: the check itself failed, so nothing was observed"
    return ""


def _verdict(
    *,
    command: str,
    verify_text: str,
    owner: str,
    trusted_owners: frozenset[str],
    verify: bool,
    run_predicate: Callable[[str], Any],
) -> tuple[str, str]:
    """``(state, evidence)`` for one obligation. The whole three-state rule lives here.

    Read it as a sequence of refusals: with no predicate there is nothing to check and
    the issue stands as filed; with a predicate we did not run, we say so rather than
    guessing; only an exit status decides between ``open`` and ``discharged``.
    """
    if not command:
        if "`" in (verify_text or ""):
            # A field with a backtick but no complete code span is a malformed
            # predicate, not the documented "none possible" prose. Saying so is the
            # difference between a `?` and a row that reads open for a typo.
            return UNKNOWN, _evidence("malformed verify field", verify_text)
        return OPEN, verify_text or "no verify predicate"
    if not verify:
        return UNKNOWN, "not evaluated (verify=False)"
    if owner not in trusted_owners:
        return UNKNOWN, f"not evaluated: owner {owner!r} is not in trusted_owners"
    try:
        outcome = _as_outcome(run_predicate(command))
    except Exception as exc:  # noqa: BLE001 - an evaluator that blew up is not an answer
        return UNKNOWN, _evidence(f"the predicate could not be evaluated: {exc}")
    if outcome.status is None:
        return UNKNOWN, outcome.output or "the predicate could not be run"
    if outcome.status == 0:
        return DISCHARGED, _evidence("exit 0", outcome.output)
    unusable = not_an_answer(outcome.status, outcome.output)
    if unusable:
        return UNKNOWN, _evidence(unusable, outcome.output)
    return OPEN, _evidence(f"exit {outcome.status}", outcome.output)


# --------------------------------------------------------------------------------
# The operation.
# --------------------------------------------------------------------------------


def _repo_of(issue: Mapping[str, Any]) -> str:
    repository = issue.get("repository") or {}
    if isinstance(repository, Mapping):
        return str(repository.get("nameWithOwner") or repository.get("name") or "")
    return str(repository)


def _age_days(created: str, now: datetime) -> int:
    """Whole days between an ISO-8601 stamp and ``now``. Unparseable reads as 0."""
    try:
        stamp = datetime.fromisoformat((created or "").replace("Z", "+00:00"))
    except ValueError:
        return 0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0, int((now - stamp).total_seconds() // _SECONDS_PER_DAY))


#: What each state is worth in the ordering: what is owed first, what was never checked
#: next, what is already done last.
_STATE_RANK = {OPEN: 0, UNKNOWN: 1, DISCHARGED: 2}


def _sort_key(row: Obligation) -> tuple:
    # A row with no predicate sinks below one with a checked verdict, rather than being
    # hidden: it is still owed, it is just the one nobody can confirm.
    return (
        _STATE_RANK.get(row.state, 9),
        0 if row.predicate else 1,
        -row.age_days,
        row.repo,
        row.number,
    )


def _issues(
    issues_source: Any,
    **query: Any,
) -> list[dict[str, Any]]:
    """Call the source if it is callable; otherwise take it as the rows themselves."""
    if issues_source is None:
        return gh_issues(**query)
    if callable(issues_source):
        return list(issues_source(**query))
    return [dict(row) for row in issues_source]


def owed(
    *,
    verify: bool = True,
    owners: Iterable[str] | None = None,
    trusted_owners: Iterable[str] | None = None,
    label: str = DFLT_LABEL,
    limit: int = DFLT_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
    predicate_timeout: float = DFLT_PREDICATE_TIMEOUT,
    now: datetime | None = None,
    issues_source: Any = None,
    run_predicate: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """The open `manual-task` obligations, each re-checked against the world.

    ``verify=False`` lists without executing anything; every row that carries a
    predicate then reads ``unknown``, because that is what is true about it.

    ``owners=`` scopes the search (default: :func:`configured_owners`).
    ``trusted_owners=`` scopes what may *execute* and defaults to ``owners``, so
    widening the search never quietly widens what runs — pass it explicitly to search
    wider than you trust.

    Two seams, each one keyword argument, each defaulting to a real implementation:
    ``issues_source=`` (defaults to :func:`gh_issues`; a list of dicts substitutes) and
    ``run_predicate=`` (defaults to :func:`shell_predicate`; any callable from command
    to exit status substitutes). With both injected this reaches no network and needs no
    ``gh``.

    Returns one envelope, never a bare list, because a reader has to be able to tell
    "nothing is owed" from "I could not find out":

    ``listed``
        ``False`` when the *listing itself* failed. Every surface must render that as
        ``?``. The counts are zeros and they mean nothing.
    ``checked``
        whether predicates were evaluated at all.
    ``truncated``
        the result set saturated its own cap, so the count is a floor.
    ``counts``
        ``open`` / ``discharged`` / ``unknown`` / ``with_predicate`` / ``total``.
    ``rows``
        one dict per obligation, with every key in :data:`OBLIGATION_FIELDS`.

    >>> report = owed(issues_source=[], run_predicate=lambda command: 0)
    >>> report['listed'], report['counts']['total'], report['rows']
    (True, 0, [])

    A listing that could not run is not "nothing owed":

    >>> def broken(**query):
    ...     raise GhUnavailable('gh: not logged in')
    >>> report = owed(issues_source=broken)
    >>> report['listed'], report['error'], report['counts']['total']
    (False, 'gh: not logged in', 0)
    """
    run_predicate = (
        (lambda command: shell_predicate(command, timeout=predicate_timeout))
        if run_predicate is None
        else run_predicate
    )
    now = datetime.now(timezone.utc) if now is None else now
    counts = {OPEN: 0, DISCHARGED: 0, UNKNOWN: 0, "with_predicate": 0, "total": 0}

    def envelope(**overrides: Any) -> dict[str, Any]:
        base = {
            "listed": True,
            "checked": verify,
            "error": "",
            "truncated": False,
            "label": label,
            "owners": [],
            "trusted_owners": [],
            "counts": dict(counts),
            "rows": [],
        }
        return {**base, **overrides}

    try:
        # Resolving owners can itself need `gh`. It is skipped entirely when the caller
        # supplied the rows, so an injected source stays offline.
        if owners is not None:
            resolved = tuple(owners)
        elif issues_source is None:
            resolved = configured_owners(timeout=timeout)
        else:
            resolved = ()
        trusted = frozenset(resolved if trusted_owners is None else trusted_owners)
        raw = _issues(
            issues_source,
            owners=resolved,
            label=label,
            limit=limit + 1,  # one more than we report: saturation must be visible
            timeout=timeout,
        )
    except GhUnavailable as exc:
        return envelope(listed=False, error=str(exc), owners=list(owners or ()))

    truncated = len(raw) > limit
    rows = []
    for issue in raw[:limit]:
        repo = _repo_of(issue)
        owner = repo.partition("/")[0]
        command, verify_text = parse_verify(issue.get("body") or "")
        state, evidence = _verdict(
            command=command,
            verify_text=verify_text,
            owner=owner,
            trusted_owners=trusted,
            verify=verify,
            run_predicate=run_predicate,
        )
        rows.append(
            Obligation(
                repo=repo,
                number=int(issue.get("number") or 0),
                title=str(issue.get("title") or ""),
                url=str(issue.get("url") or ""),
                created=str(issue.get("createdAt") or ""),
                age_days=_age_days(str(issue.get("createdAt") or ""), now),
                state=state,
                verify=verify_text,
                predicate=command,
                evidence=evidence,
            )
        )

    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1
        counts["with_predicate"] += 1 if row.predicate else 0
    counts["total"] = len(rows)

    return envelope(
        owners=list(resolved),
        trusted_owners=sorted(trusted),
        truncated=truncated,
        counts=dict(counts),
        rows=[row.as_dict() for row in sorted(rows, key=_sort_key)],
    )
