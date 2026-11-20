"""The pile: GTD's In list, kept as GitHub issues in a private repo, and its clarify step.

A capture (an Apple Shortcut, the `gh` CLI, anything that can send a request to the issues
API) is one open issue labelled ``pile`` in the owner's pile repo. This module is the one
place that reads and changes that pile, so the agent skill (``openloops-pile``), the
``ol pile-*`` commands and a voice surface (bosun) all do the same thing:

- :func:`items` / :func:`show`: what is on the pile, read-only;
- :func:`propose`: a first proposal per item, from a model-free heuristic by default
  (``proposer=`` is the seam an agent's own reading replaces);
- :func:`plan`: the steps that carry out one decision the owner said yes to (a loop, an
  idea, an issue in another repo, work handed to a session, done, dropped), ending with
  a signed comment on the pile item saying where it went. **openloops never writes to
  GitHub** (ADR-008, ADR-014): the caller runs the steps with its own tools;
- :func:`signed`: a signed progress note, for a session working on an item;
- :func:`nudge`: keep one reminder loop pending while items wait too long. It never
  acts on an item.

**Every write is signed** (:func:`signature`): the agent's name and, on private repos, a
link to its session, so an idea's development can always be traced back to who did it.
**Public destinations get no private content**: an issue filed in a public repo carries
only the text the caller wrote for it, no dictation, no pile link and no session link.

Nothing here runs on capture and nothing acts without being called: no Action, no
webhook (the owner's rule). GitHub is only read, through ``gh`` (``run_gh=``); the one
write is :func:`nudge`'s reminder loop, through openloops' own reminder runner.

>>> parse_item({"number": 7, "title": "call about zodal", "body": "call about zodal\\n\\n— pile: inbox",
...             "labels": [{"name": "pile"}, {"name": "inbox"}], "createdAt": "2026-11-20T10:00:00Z",
...             "url": "https://github.com/o/_pile/issues/7"}).hint
'inbox'
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "PILE_LABEL",
    "KINDS",
    "DFLT_STALE_DAYS",
    "NUDGE_SOURCE",
    "PileItem",
    "pile_repo",
    "parse_item",
    "items",
    "show",
    "heuristic_propose",
    "propose",
    "signature",
    "agent_identity",
    "RESULT",
    "signed",
    "plan",
    "nudge",
]

#: The label every untriaged capture carries.
PILE_LABEL = "pile"
#: Outcome labels (created in the pile repo; see its README).
ROUTED, DROPPED, WORKING, NEEDS_OWNER = "routed", "dropped", "working", "needs-owner"
#: What :func:`apply` can do with an item.
KINDS = ("loop", "idea", "issue", "work", "done", "drop", "ask")
#: An item older than this many days makes :func:`nudge` keep a reminder pending.
DFLT_STALE_DAYS = 3.0
#: The ``source`` of the nudge loop: one per pile, found again by this.
NUDGE_SOURCE = "pile-nudge"
#: The line the capture Shortcut appends to the body: ``— pile: <hint>``.
_HINT_LINE = re.compile(r"\n*\s*[—-]+\s*pile:\s*(?P<hint>[\w.-]+)\s*$")
_DFLT_TIMEOUT = 30.0
_SAID_PREVIEW = 160


# --------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PileItem:
    """One capture. ``said`` is the dictation, with the Shortcut's hint line removed."""

    number: int
    title: str
    said: str
    hint: str | None
    labels: tuple[str, ...]
    created: str
    url: str
    state: str = "open"
    comments: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def age_days(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        made = datetime.fromisoformat(self.created.replace("Z", "+00:00"))
        return max(0.0, (now - made).total_seconds() / 86400)

    def as_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        d = asdict(self)
        d["labels"] = list(self.labels)
        d["comments"] = [dict(c) for c in self.comments]
        d["age_days"] = round(self.age_days(now), 1)
        return d


def pile_repo(
    repo: str | None = None, *, run_gh: Callable[..., str] | None = None
) -> str:
    """The pile repo: ``repo``, else ``OPENLOOPS_PILE_REPO``, else ``<gh login>/_pile``."""
    if repo:
        return repo
    if os.environ.get("OPENLOOPS_PILE_REPO"):
        return os.environ["OPENLOOPS_PILE_REPO"]
    login = _run(run_gh, ["api", "user", "-q", ".login"]).strip()
    return f"{login}/_pile"


def parse_item(raw: Mapping[str, Any]) -> PileItem:
    """A :class:`PileItem` from ``gh``'s JSON for one issue. Pure.

    The hint is the first label that is not a status label, else the body's
    ``— pile: <hint>`` line (kept by the Shortcut in case a label is dropped).

    >>> parse_item({"number": 1, "title": "t", "body": "no hint here", "labels": [],
    ...             "createdAt": "2026-11-20T10:00:00Z", "url": "u"}).hint is None
    True
    """
    labels = tuple(
        (x["name"] if isinstance(x, Mapping) else str(x))
        for x in raw.get("labels") or ()
    )
    body = raw.get("body") or ""
    found = _HINT_LINE.search(body)
    said = body[: found.start()].rstrip() if found else body.strip()
    status = {PILE_LABEL, ROUTED, DROPPED, WORKING, NEEDS_OWNER, "manual-task"}
    hint = next((x for x in labels if x not in status), None) or (
        found.group("hint") if found else None
    )
    return PileItem(
        number=int(raw["number"]),
        title=raw.get("title") or "",
        said=said,
        hint=hint,
        labels=labels,
        created=raw.get("createdAt") or raw.get("created_at") or "",
        url=raw.get("url") or raw.get("html_url") or "",
        state=str(raw.get("state") or "open").lower(),
        comments=tuple(
            {
                "author": (c.get("author") or {}).get("login"),
                "at": c.get("createdAt"),
                "body": c.get("body") or "",
            }
            for c in raw.get("comments") or ()
        ),
    )


_FIELDS = "number,title,body,labels,createdAt,url,state"


def items(
    *,
    repo: str | None = None,
    label: str = PILE_LABEL,
    limit: int = 200,
    run_gh: Callable[..., str] | None = None,
) -> list[PileItem]:
    """The open items carrying ``label`` (default: untriaged), oldest first."""
    repo = pile_repo(repo, run_gh=run_gh)
    out = _run(
        run_gh,
        ["issue", "list", "-R", repo, "--state", "open", "--label", label,
         "--limit", str(limit), "--json", _FIELDS],
    )  # fmt: skip
    found = [parse_item(r) for r in json.loads(out or "[]")]
    return sorted(found, key=lambda i: (i.created, i.number))


def show(
    number: int, *, repo: str | None = None, run_gh: Callable[..., str] | None = None
) -> PileItem:
    """One item with its comments (any state)."""
    number = int(number)
    repo = pile_repo(repo, run_gh=run_gh)
    out = _run(
        run_gh,
        ["issue", "view", str(number), "-R", repo, "--json", _FIELDS + ",comments"],
    )
    return parse_item(json.loads(out))


# --------------------------------------------------------------------------------
# Proposing (no model)
# --------------------------------------------------------------------------------

_REMIND = re.compile(r"\b(remind me|don'?t (let me )?forget|ping me)\b", re.I)
_IDEA = re.compile(r"^\s*(an? )?idea\b|\bidea:", re.I)


def heuristic_propose(item: PileItem) -> dict[str, Any]:
    """A first guess from the words alone. An agent's reading replaces it (``proposer=``).

    >>> it = parse_item({"number": 3, "title": "x", "body": "Remind me to call Ana tomorrow",
    ...                  "labels": [], "createdAt": "2026-11-20T10:00:00Z", "url": "u"})
    >>> heuristic_propose(it)["kind"]
    'loop'
    """
    text = item.said or item.title
    base = {"number": item.number, "title": item.title, "confidence": "heuristic"}
    if _REMIND.search(text):
        return {
            **base,
            "kind": "loop",
            "why": "says 'remind me'; the time is yours to read",
        }
    if _IDEA.search(text):
        return {**base, "kind": "idea", "why": "starts as an idea"}
    if item.hint and item.hint != "inbox":
        return {
            **base,
            "kind": "issue",
            "why": f"hint '{item.hint}': the pile README's routing map names the repo",
        }
    return {**base, "kind": "ask", "why": "nothing in the words places it"}


def propose(
    found: Iterable[PileItem],
    *,
    proposer: Callable[[PileItem], Mapping[str, Any]] = heuristic_propose,
) -> list[dict[str, Any]]:
    """One proposal per item. Proposals change nothing; :func:`apply` acts on a yes."""
    return [dict(proposer(item)) for item in found]


# --------------------------------------------------------------------------------
# Signing
# --------------------------------------------------------------------------------


def agent_identity(
    by: str | None = None,
    session: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, str | None]:
    """Who is writing: ``by`` (an agent or session name) and ``session`` (a URL or address).

    Defaults: ``OPENLOOPS_AGENT``; then Claude Code's own variables, the Remote Control
    session (``https://claude.ai/code/<CLAUDE_CODE_BRIDGE_SESSION_ID>``) or the local
    session id (``claude-code:<CLAUDE_CODE_SESSION_ID>``).

    >>> agent_identity(env={"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01X"})["session"]
    'https://claude.ai/code/session_01X'
    """
    env = os.environ if env is None else env
    bridge = env.get("CLAUDE_CODE_BRIDGE_SESSION_ID")
    local = env.get("CLAUDE_CODE_SESSION_ID")
    if session is None:
        if bridge:
            session = f"https://claude.ai/code/{bridge}"
        elif local:
            session = f"claude-code:{local}"
    by = (
        by
        or env.get("OPENLOOPS_AGENT")
        or (f"claude-code {local[:8]}" if local else None)
    )
    return {"by": by, "session": session}


def signature(by: str, session: str | None = None, *, public: bool = False) -> str:
    """The last lines of every comment an agent writes here.

    On a public repo only the name: a session link is private context.

    >>> print(signature("gtd-capture@mac", "https://claude.ai/code/session_01X"))
    <BLANKLINE>
    —
    Agent: gtd-capture@mac
    Claude-Session: https://claude.ai/code/session_01X
    >>> signature("gtd-capture@mac", "https://claude.ai/code/session_01X", public=True).splitlines()[-1]
    'Agent: gtd-capture@mac'
    """
    if not by:
        raise ValueError("an agent writing on the pile must name itself (by=, --by)")
    lines = ["", "—", f"Agent: {by}"]
    if session and not public:
        key = "Claude-Session" if session.startswith("http") else "Session"
        lines.append(f"{key}: {session}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------
# Planning a yes (openloops never writes to GitHub: the caller carries the plan out)
# --------------------------------------------------------------------------------

#: The placeholder a plan's later steps carry for what the first step produced (an
#: issue URL, a loop id, an idea id). The caller substitutes it.
RESULT = "{result}"


def signed(
    text: str,
    *,
    by: str | None = None,
    session: str | None = None,
    public: bool = False,
) -> dict[str, Any]:
    """``text`` with the writer's signature appended: the body of a progress note.

    The session working on an item posts this as a comment on the pile item.
    """
    who = agent_identity(by, session)
    body = (
        text.rstrip() + "\n" + signature(who["by"] or "", who["session"], public=public)
    )
    return {"body": body, **who}


def plan(
    number: int,
    kind: str,
    *,
    reading: str,
    by: str | None = None,
    session: str | None = None,
    title: str | None = None,
    when: str | None = None,
    reveal: bool = False,
    target_repo: str | None = None,
    issue_body: str | None = None,
    tags: str | None = None,
    reason: str | None = None,
    repo: str | None = None,
    run_gh: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """The steps that carry out one decision the owner said yes to, as data. Changes nothing.

    openloops never writes to GitHub (ADR-008, ADR-014): the caller runs the steps in
    order, with its own tools (``gh`` in a Claude Code session, the connector's comment
    and create tools on a voice surface), substituting :data:`RESULT` in later steps
    with what the first step produced. ``reading`` is the agent's interpretation, and
    opens the signed comment. Per ``kind``:

    - ``loop``: ``remind`` (``ol remind``; source = the item's URL), then close as routed;
    - ``idea``: ``idea`` (``ideadump add`` with the dictation verbatim), then close as routed;
    - ``issue``: ``create_issue`` in ``target_repo`` (``title`` + ``issue_body``
      required); a public repo gets that text only, no pile link and no session link;
    - ``work``: hand-off to a session; labelled ``working`` and left open; the session
      posts :func:`signed` notes and finishes with ``done``;
    - ``done``: close as routed, ``reason`` = the evidence;
    - ``drop``: close as not planned, ``reason`` required (never silent);
    - ``ask``: stays on the pile, labelled ``needs-owner``, ``reason`` = the question.

    Step ops: ``remind``, ``idea``, ``create_issue``, ``comment``, ``labels``, ``close``.
    """
    number = int(number)
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    if not reading or not reading.strip():
        raise ValueError(
            "say how you read the item (reading=): the comment starts with it"
        )
    who = agent_identity(by, session)
    if not who["by"]:
        raise ValueError("an agent writing on the pile must name itself (by=, --by)")
    repo = pile_repo(repo, run_gh=run_gh)
    item = show(number, repo=repo, run_gh=run_gh)
    if item.state != "open":
        raise ValueError(f"{repo}#{number} is {item.state}: nothing to do")

    first: dict[str, Any] | None = None
    close: str | None = "completed"
    add, remove = [ROUTED], [PILE_LABEL, NEEDS_OWNER, WORKING]
    went = f"→ {RESULT}"
    if kind == "loop":
        first = {"op": "remind", "title": title or item.title, "when": when,
                 "reveal": reveal, "source": item.url}  # fmt: skip
        went = f"→ loop {RESULT}"
    elif kind == "idea":
        first = {"op": "idea", "words": item.said or item.title, "title": title,
                 "summary": reading.strip(), "tags": tags, "source": item.url}  # fmt: skip
        went = f"→ idea {RESULT}"
    elif kind == "issue":
        if not (target_repo and title and issue_body):
            raise ValueError("kind=issue needs target_repo, title and issue_body")
        public = _visibility(target_repo, run_gh=run_gh) == "PUBLIC"
        body = (
            issue_body.rstrip()
            + "\n"
            + signature(who["by"], who["session"], public=public)
        )
        if not public:
            body += f"\nFrom the pile: {item.url}"
        first = {"op": "create_issue", "repo": target_repo, "title": title,
                 "body": body, "public": public}  # fmt: skip
        went = f"→ issue {RESULT}" + (
            " (public: technical text only)" if public else ""
        )
    elif kind in ("work", "done", "drop", "ask") and not reason:
        need = {"work": "who takes it, and how they report", "done": "the evidence",
                "drop": "why: a drop is never silent", "ask": "the question"}[kind]  # fmt: skip
        raise ValueError(f"kind={kind} needs reason=: {need}")
    if kind == "work":
        went, close, add, remove = (
            f"→ handed off: {reason}",
            None,
            [WORKING],
            [PILE_LABEL, NEEDS_OWNER],
        )
    elif kind == "done":
        went = f"→ done: {reason}"
    elif kind == "drop":
        went, close, add = f"→ dropped: {reason}", "not planned", [DROPPED]
    elif kind == "ask":
        went, close, add, remove = (
            f"→ question for the owner: {reason}",
            None,
            [NEEDS_OWNER],
            [],
        )

    note = f"{reading.strip()}\n\n{went}\n" + signature(who["by"], who["session"])
    steps: list[dict[str, Any]] = [first] if first else []
    steps.append({"op": "comment", "repo": repo, "number": number, "body": note})
    steps.append({"op": "labels", "repo": repo, "number": number, "add": add,
                  "remove": [x for x in remove if x in item.labels]})  # fmt: skip
    if close:
        steps.append({"op": "close", "repo": repo, "number": number, "reason": close})
    return {"repo": repo, "number": number, "kind": kind, "item": item.url,
            "steps": steps, **who}  # fmt: skip


# --------------------------------------------------------------------------------
# Nudging (never acting)
# --------------------------------------------------------------------------------


def nudge(
    *,
    stale_days: float = DFLT_STALE_DAYS,
    at: str = "09:00",
    repo: str | None = None,
    run_gh: Callable[..., str] | None = None,
    loops_api: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Keep exactly one pending reminder while any pile item is older than ``stale_days``.

    Idempotent; run it from a timer. When items are stale and no nudge is scheduled, it
    makes one loop (source ``pile-nudge``) for the next ``at`` in the owner's zone, saying
    only the count and the oldest age (no item text: the push crosses a public relay).
    A nudge that already fired is closed when the next one is made; when nothing is
    stale, a scheduled one is withdrawn. It never touches a pile item.
    """
    from openloops import tools as _tools  # imported on use: tools imports this module

    api = loops_api or _tools
    now = now or datetime.now(timezone.utc)
    found = items(repo=repo, run_gh=run_gh)
    stale = [i for i in found if i.age_days(now) >= stale_days]
    mine = [
        lp
        for lp in api.loops(state="open")["loops"]
        if (lp.get("source") or {}).get("ref") == NUDGE_SOURCE
    ]
    pending = [lp for lp in mine if lp.get("state") == "submitted"]
    fired = [lp for lp in mine if lp.get("state") != "submitted"]
    report: dict[str, Any] = {
        "count": len(found),
        "stale": len(stale),
        "oldest_days": round(max((i.age_days(now) for i in found), default=0.0), 1),
        "made": None,
        "closed": [],
    }
    if not stale:
        for lp in pending:
            api.done(lp["id"], note="pile no longer stale", only_source=NUDGE_SOURCE)
            report["closed"].append(lp["id"])
        return report
    if pending:
        return report
    for lp in fired:
        api.done(
            lp["id"], note="superseded by the next nudge", only_source=NUDGE_SOURCE
        )
        report["closed"].append(lp["id"])
    title = f"Pile: {len(found)} waiting, oldest {report['oldest_days']:.0f}d"
    made = api.remind(title, when=at, reveal=True, source=NUDGE_SOURCE, daily_cap=1)
    report["made"] = made.get("id")
    report["echo"] = made.get("echo")
    return report


# --------------------------------------------------------------------------------
# The outside world, each behind one seam
# --------------------------------------------------------------------------------


def _run(run_gh: Callable[..., str] | None, args: Sequence[str]) -> str:
    if run_gh is None:
        from openloops.obligations import _gh as run_gh  # the package's one gh runner
    return run_gh(list(args), timeout=_DFLT_TIMEOUT)


def _visibility(repo: str, *, run_gh: Callable[..., str] | None = None) -> str:
    out = _run(
        run_gh, ["repo", "view", repo, "--json", "visibility", "-q", ".visibility"]
    )
    return out.strip().upper()
