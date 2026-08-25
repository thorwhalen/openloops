"""Data structures shared across openloops: what a session is, and what a digest is.

Nothing here does I/O and nothing here makes a judgement. :mod:`openloops.transcripts`
reads sessions, :mod:`openloops._classify` judges them, :mod:`openloops.digest` renders
them, and all three speak in the types defined here.

The types are deliberately flat and JSON-shaped. A session read from Claude Code's
on-disk state and a session supplied by some other reader are the same object to the
rest of the package — that is what makes ``transcript_source=`` a one-argument swap.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

#: Loop state: the session's own last word left something for the human.
OPEN = "open"
#: Loop state: the session's own last word closed out.
ARCHIVE = "archive"
#: The two loop states, in the order they are shown.
STATES = (OPEN, ARCHIVE)


@dataclass(frozen=True)
class Locator:
    """A typed, human-readable pointer to something outside the digest.

    The exportable half of ADR-015's evidence split: a short typed reference that
    another tool (or a person) can resolve, never a content hash and never a byte
    offset into a file that is garbage-collected after thirty days.

    >>> Locator("pr", url="https://github.com/o/r/pull/1").as_dict()["type"]
    'pr'
    """

    type: str
    url: str = ""
    text: str = ""
    at: str = ""

    def as_dict(self) -> dict[str, str]:
        """JSON-ready form."""
        return asdict(self)


@dataclass(frozen=True)
class Session:
    """What one Claude Code session's persisted state says, parsed but not judged.

    Every field is a *fact read from the transcript*, never an inference about the
    world. ``last_assistant_text`` is what the session said last; it is not a claim
    that the thing it describes is still true.

    ``key`` is the session id. It is the only identifier openloops uses, and per
    ADR-014 nothing in the model hangs off it: a digest is a view keyed by session,
    not a record owned by one.
    """

    key: str
    title: str = ""
    ai_title: str = ""
    cwd: str = ""
    project: str = ""
    git_branches: tuple[str, ...] = ()
    started_at: str = ""
    ended_at: str = ""
    last_turn_at: str = ""
    last_user_prompt: str = ""
    last_prompt_at: str = ""
    last_assistant_text: str = ""
    #: Claude Code's own end-of-turn recap (its ``away_summary`` record) — one to three
    #: sentences it wrote itself, usually naming what it thought came next. Reading it
    #: is retention, not duplication: it was generated and billed once already, and it
    #: disappears with the transcript.
    recap: str = ""
    recap_at: str = ""
    #: The context-compaction summary, a different and much longer thing than the recap,
    #: covering only the part of the session that preceded it.
    compaction: str = ""
    compaction_at: str = ""
    turn_count: int = 0
    model: str = ""
    #: The transcript's final conversational record is an unanswered human prompt, or an
    #: assistant tool call whose result never arrived — i.e. the session stopped mid-turn.
    ended_mid_turn: bool = False
    #: The last thing the session said is a usage-limit or API-error banner rather than
    #: the assistant's own words: it was cut off, not finished.
    ended_with_error: bool = False
    locators: tuple[Locator, ...] = ()

    @property
    def git_branch(self) -> str:
        """The branch the session opened on — the one that names it, when several ran.

        A third of sessions touch more than one branch, so a single value is a summary
        rather than a fact; :attr:`git_branches` is what carries the truth.
        """
        return self.git_branches[0] if self.git_branches else ""

    @property
    def heading(self) -> str:
        """What to call this session in prose: its description, else its label."""
        return self.ai_title or self.title or self.project or f"session {self.key[:8]}"

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form (``asdict`` already flattens the nested locators)."""
        return asdict(self)


@dataclass(frozen=True)
class Verdict:
    """A loop-state judgement, with the rule that produced it and the cues it saw.

    ``reason`` and ``cues`` exist so a reader can disagree. A classification whose
    grounds are not shown is an assertion, and openloops does not make assertions
    about sessions — it reports what they said and why it read them that way.
    """

    state: str
    reason: str
    cues: tuple[str, ...] = ()
    #: When the text this verdict was read from was written. Usually the closing turn,
    #: but the recap rule reads text written later, and a heading dated to the wrong
    #: moment is exactly the thing ADR-005 forbids.
    at: str = ""
    #: ``"high"`` when a rule actually fired, ``"low"`` when the state is the default
    #: and nothing in the transcript supported it. A classifier that hides which of the
    #: two it did is claiming knowledge it does not have.
    confidence: str = "high"

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "state": self.state,
            "reason": self.reason,
            "cues": list(self.cues),
            "at": self.at,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class Digest:
    """One rendered digest: its store key and its markdown text.

    ``text`` is a pure function of the :class:`Session` it was built from. It carries
    no generation timestamp, which is what lets the regeneration test in
    ``tests/test_sync.py`` compare bytes rather than fields.
    """

    key: str
    text: str
    session_key: str
    source: str
    state: str
    verdict: Verdict = field(default_factory=lambda: Verdict(ARCHIVE, ""))

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form (without the markdown body)."""
        return {
            "key": self.key,
            "session_key": self.session_key,
            "source": self.source,
            "state": self.state,
            "verdict": self.verdict.as_dict(),
        }
