"""Rendering one session into one dated markdown digest. No model, no network.

The whole of the release's honesty rule lives in this module:

> **A digest states what the session said, dated — never what is currently true.**

So every heading here carries the timestamp of the thing under it, the loop state is
phrased as a reading of the transcript rather than a claim about the world, and the
front matter says ``verified: false`` because nothing has been checked against
anything. ADR-015's failure mode — a snapshot of local state that was already wrong on
two of four fields, published and handed to a consumer that acted on it — is what these
rules exist to prevent, and the way to prevent it is to never make the claim.

:func:`render` is a pure function of its :class:`~openloops.base.Session` and
:class:`~openloops.base.Verdict`. It stamps no generation time, which is what allows
``tests/test_sync.py`` to delete the entire store, regenerate, and compare bytes.
"""

from __future__ import annotations

from collections.abc import Mapping

from openloops._classify import CLOSING_CHARS
from openloops.base import Digest, Session, Verdict
from openloops.egress import scrub
from openloops.store import digest_key

__all__ = ["render", "make_digest", "SECTION_LIMITS"]

#: How many branches the front matter names before it stops. A third of sessions touch
#: more than one; a few touch many, and the list is metadata, not the content.
MAX_BRANCHES = 4

#: How much of each section is kept. Bounds are deterministic so regeneration is
#: byte-stable; they exist because a digest is meant to be read, not archived whole.
SECTION_LIMITS: Mapping[str, int] = {
    "last_assistant_text": 4000,
    "last_user_prompt": 1200,
    "recap": 1500,
    "compaction": 3000,
}

_PREAMBLE = (
    "> **What this is.** A dated record of what one Claude Code session *said*. "
    "Nothing here has been checked against the world, so nothing here claims to be "
    "true now — including the loop state, which reports how the session's own last "
    "turn read."
)


def _clip(text: str, limit: int, *, keep_tail: int = 0) -> str:
    """Bound a section deterministically, saying so when it bites.

    ``keep_tail`` keeps that many characters from the end as well as the head. The
    classifier reads the *end* of a turn while the digest prints the *beginning*, so for
    a long enough turn the two windows are disjoint and the digest would print the cue
    that decided the verdict while clipping away the sentence it came from — leaving the
    reader unable to check a claim the package exists to make checkable.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    marker = f"\n\n*… clipped at {limit} characters"
    if keep_tail and limit > keep_tail:
        head = text[: limit - keep_tail].rstrip()
        tail = text[-keep_tail:].lstrip()
        return (
            f"{head}{marker}; its closing lines follow, because that is what the "
            f"loop state was read from.*\n\n{tail}"
        )
    return text[:limit].rstrip() + marker + ".*"


def _front_matter(session: Session, verdict: Verdict, source: str) -> str:
    fields = [
        ("session", session.key),
        ("source", source),
        ("state", verdict.state),
        ("title", session.title),
        ("ai_title", session.ai_title),
        ("project", session.project),
        ("branches", ", ".join(session.git_branches[:MAX_BRANCHES])),
        ("started", session.started_at),
        ("ended", session.ended_at),
        ("last_turn", session.last_turn_at),
        ("turns", str(session.turn_count)),
        ("model", session.model),
        ("confidence", verdict.confidence),
        ("verified", "false"),
    ]
    lines = ["---"]
    lines += [f"{k}: {_one_line(v)}" for k, v in fields if v]
    lines.append("---")
    return "\n".join(lines)


def _one_line(value: str) -> str:
    """Flatten a front-matter value onto one line.

    Titles, project names and models all come out of a transcript, and a session title
    is user-settable. A newline in one would open a second front-matter line — and since
    the last key wins on read, a title of ``fix\nstate: archive`` would file an open
    session as closed. A field read from a document must never be able to change the
    document's own metadata.

    >>> _one_line("fix" + chr(10) + "state: archive")
    'fix state: archive'
    """
    return " ".join(str(value).split())


def _heading(session: Session) -> str:
    """The digest's H1: the session's generated description, else its label."""
    return session.heading


def _loop_state_section(session: Session, verdict: Verdict) -> list[str]:
    # The verdict says when the text it read was written. That is not always the closing
    # turn — the recap rule reads text written after it — and dating the one heading ADR
    # 005 calls load-bearing to the wrong moment would defeat the point of dating it.
    when = (
        verdict.at or session.last_turn_at or session.started_at or "an unrecorded time"
    )
    out = [
        f"## Loop state, as read from the turn of {when}",
        "",
        f"**{verdict.state}** — {verdict.reason}",
    ]
    if verdict.cues:
        cues = ", ".join(f"`{c}`" for c in verdict.cues)
        out += ["", f"Cues that decided it: {cues}"]
    if verdict.confidence != "high":
        out += [
            "",
            "*Nothing in the transcript decided this — it is the default. openloops "
            "files a session as open unless it said it was finished.*",
        ]
    out += [
        "",
        "*No verify predicate has been evaluated for this session, so this is a "
        "reading of the transcript and not a statement about what remains to be done.*",
    ]
    return out


def _pointers_section(session: Session) -> list[str]:
    out = ["## Pointers"]
    for loc in session.locators:
        when = f" (recorded {loc.at})" if loc.at else ""
        target = loc.url or loc.text
        out.append(f"- {loc.type}: {target}{when}")
    out.append(
        f"- Resume: `claude --resume {session.key}` — works only while the transcript "
        "survives; Claude Code garbage-collects transcripts, and this digest is what "
        "outlives them."
    )
    return out


def render(session: Session, verdict: Verdict, *, source: str) -> str:
    """The markdown for one digest. Pure, dated, and bounded.

    >>> from openloops.base import Session, Verdict
    >>> s = Session(key='s1', project='proj', started_at='T0', last_turn_at='T1',
    ...             last_assistant_text='Shipped it.', turn_count=3)
    >>> verdict = Verdict('archive', 'its closing lines declare it finished')
    >>> text = render(s, verdict, source='demo')
    >>> text.splitlines()[0]
    '---'
    >>> 'state: archive' in text
    True
    >>> render(s, verdict, source='demo') == text     # pure: same in, same out
    True
    """
    parts: list[str] = [
        _front_matter(session, verdict, source),
        "",
        f"# {_heading(session)}",
        "",
        _PREAMBLE,
        "",
        *_loop_state_section(session, verdict),
    ]

    if session.recap:
        stale = (
            " — written *before* the closing turn below, and they may disagree"
            if session.last_turn_at and session.recap_at < session.last_turn_at
            else ""
        )
        parts += [
            "",
            f"## Its own recap ({session.recap_at or 'undated'}){stale}",
            "",
            _clip(session.recap, SECTION_LIMITS["recap"]),
        ]

    if session.last_assistant_text:
        parts += [
            "",
            f"## The session's last word ({session.last_turn_at or 'undated'})",
            "",
            _clip(
                session.last_assistant_text,
                SECTION_LIMITS["last_assistant_text"],
                keep_tail=CLOSING_CHARS,
            ),
        ]
    if session.last_user_prompt:
        parts += [
            "",
            f"## What was asked of it, last ({session.last_prompt_at or 'undated'})",
            "",
            _clip(session.last_user_prompt, SECTION_LIMITS["last_user_prompt"]),
        ]
    if session.compaction:
        parts += [
            "",
            f"## Context-compaction summary ({session.compaction_at or 'undated'})",
            "",
            "*Written when the session ran out of context, so it covers the session "
            "only up to that point — work after it is not in here.*",
            "",
            _clip(session.compaction, SECTION_LIMITS["compaction"]),
        ]

    parts += ["", *_pointers_section(session), ""]
    return "\n".join(parts)


def make_digest(
    session: Session, verdict: Verdict, *, source: str, aliases=None
) -> Digest:
    """Render, scrub, and key one digest.

    Raises :class:`~openloops.egress.CredentialFound` when the rendered text matches a
    credential pattern — deliberately, so the caller skips that session loudly rather
    than writing a secret into a store that may be synced.

    >>> from openloops.base import Session, Verdict
    >>> d = make_digest(Session(key='s1'), Verdict('open', 'why'), source='demo')
    >>> d.key
    'demo/open/s1.md'
    """
    text = render(session, verdict, source=source)
    text = scrub(text, aliases=aliases, where=f"session {session.key}")
    return Digest(
        key=digest_key(source, verdict.state, session.key),
        text=text,
        session_key=session.key,
        source=source,
        state=verdict.state,
        verdict=verdict,
    )
