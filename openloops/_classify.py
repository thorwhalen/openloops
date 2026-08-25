"""Reading a session's own last word: did it say it was finished, or not?

This is the only judgement openloops makes. It is made from the transcript alone — no
model, no network, and emphatically **not from whether a process is running**. A folder
split by process liveness would be a session dashboard; a folder split by what the
session *said* is a record of open loops, which is a different and more durable thing.

**It is a closed-detector, not a two-way classifier, and the asymmetry is deliberate.**
``open`` is the default, and a session reaches ``archive`` only by positively saying it
finished. Measured against hand-labelled sessions, the cue rules below never produced a
false ``archive`` but caught only about half the genuinely finished ones. That is the
right direction to be wrong in: a false ``archive`` buries a loop the tool exists to
surface, while a false ``open`` only lengthens a list that is sorted by recency anyway.
Absence of evidence that a session finished is not evidence that it did.

When the closing turn says nothing either way — about a quarter of sessions — the
session's own recap gets the last word, but only when it was written *after* that turn.
Claude Code writes one per turn and most sessions have one; ignoring evidence that is
already on disk in favour of a shrug would be a strange kind of rigour.

Three things the corpus taught, each of which changed a rule:

- **Sessions really do mostly end unresolved.** Roughly four in five end with something
  put to the human. A split that came out balanced would be a split that was lying.
- **Both kinds of cue appear in the same closing paragraph** — "say the word and I'll
  remove it. Nothing is blocking; safe to close" is finished, and "you're safe to exit …
  the two threads waiting for you are" is not. Rule precedence gets one of those wrong
  whichever order you choose, so **the latest cue in the text wins** instead.
- **A dangling structured question is not a signal.** Claude Code records a tool result
  for its question tool even when the question is dismissed, so "ended waiting for an
  answer" is simply not observable that way, and no rule here pretends otherwise.

>>> from openloops.base import Session
>>> classify(Session(key='s', last_assistant_text='All merged. Nothing pending.')).state
'archive'
>>> classify(Session(key='s', last_assistant_text='Done. Want me to land it too?')).state
'open'
>>> classify(Session(key='s', last_assistant_text='I refactored the parser.')).confidence
'low'
>>> classify(Session(key='s', last_assistant_text='I refactored the parser.',
...                  recap='All merged; nothing is pending.', recap_at='T2')).state
'archive'
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from openloops.base import ARCHIVE, OPEN, Session, Verdict

__all__ = [
    "ASK_CUES",
    "CLOSE_CUES",
    "CLOSING_CHARS",
    "DEFER_CUES",
    "asks_the_human",
    "classify",
    "ends_with_a_question",
    "find_cues",
    "latest_cue",
]

#: How much of the tail of the last assistant turn counts as "the closing". Final turns
#: run to a couple of thousand characters; at four hundred, two sessions in five carry
#: no cue at all, and at twelve hundred that falls to about one in five.
CLOSING_CHARS = 1200

#: Phrases that put a decision to the human.
ASK_CUES: tuple[str, ...] = (
    "want me to",
    "do you want",
    "would you like",
    "shall i",
    "should i",
    "let me know",
    "say the word",
    "your call",
    "up to you",
    "over to you",
    "which would you",
    "tell me which",
    "if you'd prefer",
    "if you would prefer",
    "needs your input",
    "needs your review",
    "needs your decision",
    "needs your go-ahead",
    "needs your call",
)

#: Phrases that defer something — name work not done, or hand it back.
DEFER_CUES: tuple[str, ...] = (
    "still open",
    "still owed",
    "still outstanding",
    "still pending",
    "next step",
    "next session",
    "left off",
    "waiting for you",
    "waiting on",
    "blocked on",
    "blocked by",
    "handoff",
    "hand-off",
    "pick it up",
    "pick this up",
    "pick that up",
    "i left it",
    "not yet done",
    "not yet merged",
    "not yet posted",
    "open question",
    "unresolved",
    "i could not",
    "i couldn't",
    "was unable to",
    "were unable to",
    "did not finish",
    "didn't finish",
    "needs a human",
    # Bare "needs you", not just "needs you to". A real session closed with
    # "Nothing further is running. The one thing that still needs you is #55" — the
    # narrower phrasing missed it and the close cue won, which is the false `archive`
    # this whole rule set is arranged to avoid.
    "needs you",
    "still needs",
    "you'll need to",
    "you will need to",
    "requires you to",
)

#: Phrases that positively declare the session finished. These are the only ones that
#: can produce ``archive``, so they are phrases rather than words: "done" on its own
#: appears in every second sentence an agent writes.
CLOSE_CUES: tuple[str, ...] = (
    "nothing half-finished",
    "nothing pending",
    "nothing is pending",
    "nothing left",
    "nothing is blocking",
    "nothing blocking",
    "nothing to clean",
    "nothing else outstanding",
    "nothing outstanding",
    "nothing further",
    "no next action",
    "no further action",
    "no action needed",
    "safe to close",
    "safe to exit",
    "you're all set",
    "you are all set",
    "all done",
    "everything is done",
    "everything is green",
    "everything is verified",
    "not unfinished business",
    "ready to close",
)

#: Text that marks the last turn as a usage-limit or connection failure rather than the
#: assistant's own closing words. Matched against the start of the closing text.
ERROR_BANNERS: tuple[str, ...] = (
    "api error",
    "you've hit your",
    "you have hit your",
    "you've reached your",
    "you have reached your",
)

#: Trailing markup and punctuation stripped before asking whether a line ends in a
#: question mark — a closing question is often bolded or parenthesised.
_TRAILING = " \t*_`\"')]}.,;:"


def closing_of(text: str, *, chars: int = CLOSING_CHARS) -> str:
    """The tail of an assistant turn, where a closing cue would live.

    >>> closing_of('a' * 20, chars=5)
    'aaaaa'
    """
    return (text or "")[-chars:]


def ends_with_a_question(text: str) -> bool:
    """Whether the final non-empty line is a question put to the reader.

    >>> ends_with_a_question('I fixed it.\\n\\n**Want me to land it?**')
    True
    >>> ends_with_a_question('Was it broken? Yes. Fixed and merged.')
    False
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    return lines[-1].rstrip(_TRAILING).endswith("?")


def find_cues(text: str, cues: Sequence[str]) -> tuple[str, ...]:
    """Which of *cues* appear in *text*, case-insensitively, in cue order.

    >>> find_cues('Shall I land it?', ASK_CUES)
    ('shall i',)
    >>> find_cues('nothing here', ASK_CUES)
    ()
    """
    low = (text or "").lower()
    return tuple(c for c in cues if c in low)


#: Sentence boundaries, roughly: terminal punctuation followed by space, or a line break.
#: Markdown makes this approximate, and approximate is enough — the unit only has to be
#: small enough that two clauses of the same thought stay together.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _cues_in(text: str, families: dict[str, Sequence[str]]) -> dict[str, str]:
    """The first cue each family contributes to *text*, keyed by family."""
    low = (text or "").lower()
    found = {}
    for family, cues in families.items():
        for cue in cues:
            if cue in low:
                found[family] = cue
                break
    return found


def latest_cue(text: str, families: dict[str, Sequence[str]]) -> tuple[str, str] | None:
    """The decisive cue, resolved at sentence granularity, and its family.

    Two corrections the corpus forced, in order.

    A closing paragraph routinely contains both an offer and a declaration of
    completeness, and which came **last** is what the writer meant — no fixed precedence
    between the families gets both real examples right. So the last sentence carrying any
    cue is the one that decides.

    But *within* that sentence, position means nothing, and a raw character offset gets
    it backwards: a real session closed with "**Needs you** (nothing blocking, all
    tracked): …", where the close cue sits inside a parenthetical of the very sentence
    that hands work back. So inside the deciding sentence, **any open cue beats a close
    cue**, which is the same asymmetry the rest of the module argues for.

    >>> latest_cue('say the word. Nothing is blocking; safe to close.',
    ...            {'ask': ASK_CUES, 'close': CLOSE_CUES})
    ('close', 'nothing is blocking')
    >>> latest_cue("you're all set — but the threads waiting for you are these",
    ...            {'defer': DEFER_CUES, 'close': CLOSE_CUES})
    ('defer', 'waiting for you')
    >>> latest_cue('Needs you (nothing blocking, all tracked): the #146 decision.',
    ...            {'defer': DEFER_CUES, 'close': CLOSE_CUES})
    ('defer', 'needs you')
    >>> latest_cue('nothing matches', {'ask': ASK_CUES}) is None
    True
    """
    for sentence in reversed(_SENTENCE_SPLIT.split(text or "")):
        found = _cues_in(sentence, families)
        if not found:
            continue
        for family in ("defer", "ask", "close"):
            if family in found:
                return family, found[family]
        family = next(iter(found))
        return family, found[family]
    return None


def asks_the_human(
    text: str, *, ask_cues: Sequence[str] = ASK_CUES, chars: int = CLOSING_CHARS
) -> tuple[str, ...]:
    """The ask cues in the closing lines, if those lines put a question to the reader.

    The primitive a retrospective measurement uses to ask "did this session end with a
    question directed at the human" — defined once, here, rather than twice.

    >>> asks_the_human('I fixed it. Want me to open the PR?')
    ('want me to',)
    >>> asks_the_human('Was it broken? Yes, and I fixed it.')
    ()
    >>> asks_the_human('All done.')
    ()
    """
    tail = closing_of(text, chars=chars)
    if not ends_with_a_question(tail) and "?" not in tail:
        return ()
    return find_cues(tail, ask_cues)


def _is_error_banner(text: str) -> bool:
    """The closing text is Claude Code's own limit or connection-failure notice."""
    head = (text or "").strip()[:200].lower()
    return any(head.startswith(b) for b in ERROR_BANNERS)


def _recap_cue(
    session: Session, families: dict[str, Sequence[str]]
) -> tuple[str, str] | None:
    """A cue from the session's own recap — read only when the closing turn is mute.

    Claude Code writes a one-to-three-sentence recap after each turn, and about seven
    sessions in ten carry one. Reading it costs nothing and is retention rather than
    duplication: it was generated and billed once already, and it disappears with the
    transcript. It is worth reading precisely where the rules above did no work, which
    on real sessions is roughly a quarter of them.

    Two guards make it safe. It is consulted **last**, so it can never override a verdict
    the closing turn actually supported. And it is ignored when it predates that turn: a
    recap goes stale relative to work done after it, and a stale "nothing pending" is
    exactly the false ``archive`` this rule set is arranged to avoid.

    >>> from openloops.base import Session
    >>> fresh = Session(key='s', last_turn_at='T1', recap='All done.', recap_at='T2')
    >>> _recap_cue(fresh, {'close': CLOSE_CUES})
    ('close', 'all done')
    >>> stale = Session(key='s', last_turn_at='T3', recap='All done.', recap_at='T2')
    >>> _recap_cue(stale, {'close': CLOSE_CUES}) is None
    True
    """
    if not session.recap:
        return None
    if (
        session.last_turn_at
        and session.recap_at
        and session.recap_at < session.last_turn_at
    ):
        return None
    return latest_cue(session.recap, families)


def _verdict_from(
    hit: tuple[str, str], where: str, *, at: str = "", plural: bool = True
) -> Verdict:
    """Turn a cue hit into a verdict naming where the cue was found, and when.

    ``plural`` only picks the verb form: "its closing lines declare" against "its own
    recap declares". A reason a reader has to squint at is a reason they will not read.
    """
    family, cue = hit
    s = "" if plural else "s"
    if family == "close":
        return Verdict(ARCHIVE, f"{where} declare{s} it finished", (cue,), at=at)
    if family == "ask":
        return Verdict(OPEN, f"{where} put{s} something to you", (cue,), at=at)
    return Verdict(OPEN, f"{where} defer{s} something", (cue,), at=at)


def classify(
    session: Session,
    *,
    ask_cues: Sequence[str] = ASK_CUES,
    defer_cues: Sequence[str] = DEFER_CUES,
    close_cues: Sequence[str] = CLOSE_CUES,
    chars: int = CLOSING_CHARS,
) -> Verdict:
    """Read a session's loop state from its own last turn.

    >>> from openloops.base import Session
    >>> classify(Session(key='s', ended_with_error=True)).state
    'open'
    >>> v = classify(Session(key='s', last_assistant_text='Blocked on your deploy key.'))
    >>> v.state, v.cues, v.confidence
    ('open', ('blocked on',), 'high')
    """
    if session.ended_with_error:
        return Verdict(
            OPEN,
            "its last turn is a usage-limit or API-error notice, so the session was cut "
            "off rather than finished",
            at=session.last_turn_at,
        )
    if session.ended_mid_turn:
        return Verdict(
            OPEN,
            "the transcript's last record is a turn nobody has answered — the session "
            "is either still going or it stopped there",
            at=session.ended_at or session.last_turn_at,
        )

    text = session.last_assistant_text
    if not text:
        return Verdict(
            OPEN,
            "the transcript records no closing text, so there is nothing saying it "
            "finished",
            at=session.ended_at,
            confidence="low",
        )
    if _is_error_banner(text):
        return Verdict(
            OPEN,
            "its last turn is a usage-limit or API-error notice, so the session was cut "
            "off rather than finished",
            at=session.last_turn_at,
        )

    families = {"ask": ask_cues, "defer": defer_cues, "close": close_cues}
    tail = closing_of(text, chars=chars)
    if ends_with_a_question(tail):
        return Verdict(OPEN, "its closing line is a question put to you")

    hit = latest_cue(tail, families)
    if hit is not None:
        return _verdict_from(hit, "its closing lines", at=session.last_turn_at)

    recap_hit = _recap_cue(session, families)
    if recap_hit is not None:
        return _verdict_from(
            recap_hit,
            "its own recap, written after the closing turn,",
            at=session.recap_at,
            plural=False,
        )

    return Verdict(
        OPEN,
        "nothing in its closing lines says it finished, and openloops does not "
        "assume it did",
        at=session.last_turn_at,
        confidence="low",
    )
