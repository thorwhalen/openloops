"""What was asked and what came back: each prompt a session received, paired with the reply
its turn ended with, and the questions a person's prompt holds.

A person asks a question in the middle of three requests, the session answers all four,
and a day later the answer is somewhere in a transcript nobody will scroll. This module
reads that back out, as facts about the document: :func:`exchanges` pairs every prompt
with the last thing the session said before the next prompt arrived, and
:func:`question_sentences` finds the sentences of a prompt that ask something.

Both are pure and heuristic, and both err toward listing. Deciding what a doubtful
sentence means, writing a gist, or finding an answer that arrived in another session is a
consumer's job, with a model if it wants one; nothing here calls one.

A prompt has an **origin**: ``human`` when a person typed it, ``peer`` when another
session sent it (Claude Code's cross-session messages arrive as user records). Only a
human prompt is searched for questions, but a peer's message still starts a turn, so the
reply to a relayed answer is a later exchange of the same session, where a consumer can
pair it with the question that waited for it.

>>> from openloops.exchanges import question_sentences
>>> question_sentences("Fix the tests. Why does CI take ten minutes? Then merge it.")
('Why does CI take ten minutes?',)
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from openloops.transcripts import (
    _WRAPPER_PAIR_RE,
    _WRAPPER_TAG_RE,
    _is_main_thread,
    _is_tool_result,
    _load_jsonl,
    _stamp,
    _text_of,
)

__all__ = [
    "HUMAN",
    "MAX_QUESTIONS",
    "PEER",
    "SYSTEM",
    "Exchange",
    "exchanges",
    "load_records",
    "question_sentences",
]

#: A prompt a person typed.
HUMAN = "human"
#: A prompt another session sent (a cross-session message).
PEER = "peer"
#: A turn the tooling started (a task notification, a scheduled wake-up): nobody asked
#: anything, but it ends the turn before it, and what the session said in it may answer
#: a question asked earlier.
SYSTEM = "system"

#: How many questions one prompt yields at most. A prompt with more is usually a pasted
#: document, and its sentences are someone else's questions.
MAX_QUESTIONS = 8

#: The fewest words a question needs: "right?" and "ok?" are tags, not questions.
MIN_WORDS = 3

_PEER_RE = re.compile(r"<cross-session-message\b[^>]*>", re.IGNORECASE)
_PEER_NAME_RE = re.compile(r'from-name="([^"]*)"')
_PEER_TAG_RE = re.compile(r"</?cross-session-message\b[^>]*>", re.IGNORECASE)
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_SENTENCE_END_RE = re.compile(r"(?<=[?!.])\s+(?=[\"'(\[]?[A-Z0-9])")

#: How a sentence that asks without a question mark begins (dictated prompts often lack
#: one). Narrower than every interrogative: "when you're done, merge it" and "where to
#: look first" open with one and ask nothing.
_ASKS_RE = re.compile(
    r"^(?:why|how come|is there|are there|is it|isn't it|do you know|any idea|"
    r"i wonder|i'm wondering|i was wondering|what (?:is|are|was|were|does|do|did|"
    r"happened|happens)|what's|how (?:do|does|did|can|could|should|would|is|are|much|"
    r"many|long)|where (?:is|are|do|does|did|can)|which (?:one|is|are|of)|"
    r"should (?:i|we)|do (?:we|i)|does (?:it|this|that)|"
    r"tell me (?:what|why|how|whether|if|where|which|who|when))\b",
    re.IGNORECASE,
)

#: A heading or a lead-in, never a question: mostly capitals, or ending with a colon.
_HEADING_RE = re.compile(r":\s*$")

#: A request phrased as a question: "can you fix it?" asks for work, not an answer. Its
#: exceptions ask for information ("can you tell me why ...").
_REQUEST_RE = re.compile(
    r"^(?:(?:can|could|would|will) you|please|let's|lets)\b(?!\s+(?:please\s+)?"
    r"(?:tell|explain|remind|clarify|confirm|say|check (?:whether|if)|let me know|"
    r"describe|summari[sz]e why))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Exchange:
    """One prompt a session received and the reply its turn ended with.

    ``uuid`` is the prompt record's own id, stable for the life of the transcript.
    ``origin`` is :data:`HUMAN`, :data:`PEER` (``sender`` names the session) or
    :data:`SYSTEM` (a notification, a headless ``-p`` run, or nothing typed).
    ``reply`` is the last assistant text before the next prompt, ``''`` while the turn
    is still running or ended without words. ``questions`` is filled for a human
    prompt only.
    """

    session: str
    uuid: str
    origin: str
    asked_at: str
    prompt: str
    reply: str = ""
    replied_at: str = ""
    sender: str = ""
    questions: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        """JSON-ready form."""
        return {**asdict(self), "questions": list(self.questions)}


def load_records(path: str | Path) -> list[dict]:
    """A transcript's records, tolerating blank and malformed lines (``OSError`` propagates)."""
    return _load_jsonl(Path(path))


def _prompt_text(record: Mapping) -> str:
    """A prompt's text with the CLI's wrappers removed, its line breaks kept."""
    text = _WRAPPER_PAIR_RE.sub(" ", _text_of(record))
    text = _WRAPPER_TAG_RE.sub(" ", text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line).strip()


def _starts_turn(record: Mapping) -> bool:
    """A ``user`` record that begins a turn: not a tool's result, not text the tooling
    injected into a running turn, not a compaction summary."""
    return (
        record.get("type") == "user"
        and not record.get("isMeta")
        and not record.get("isCompactSummary")
        and not _is_tool_result(record)
    )


def _origin(record: Mapping, text: str) -> tuple[str, str]:
    kind = (
        (record.get("origin") or {}).get("kind")
        if isinstance(record.get("origin"), Mapping)
        else None
    )
    if not text or (kind and kind != HUMAN) or record.get("promptSource") == "sdk":
        return SYSTEM, ""
    found = _PEER_RE.search(text)
    if not found:
        return HUMAN, ""
    name = _PEER_NAME_RE.search(found.group(0))
    return PEER, name.group(1) if name else ""


def exchanges(records: Iterable[Mapping], *, key: str = "") -> tuple[Exchange, ...]:
    """Every prompt of a transcript's main thread, in order, each with its turn's reply.

    Records are ordered by timestamp (a transcript's lines are not always written in
    order), ties kept in file order. Sub-agent sidechains are left out: their "prompts"
    were written by the session, not to it.

    >>> recs = [
    ...     {"type": "user", "sessionId": "s", "uuid": "u1", "timestamp": "T1",
    ...      "message": {"content": "Ship it. Is the cache still warm?"}},
    ...     {"type": "assistant", "timestamp": "T2", "message": {"content": [
    ...         {"type": "text", "text": "Shipped. Yes, warm for an hour."}]}},
    ... ]
    >>> [(e.uuid, e.questions, e.reply) for e in exchanges(recs)]
    [('u1', ('Is the cache still warm?',), 'Shipped. Yes, warm for an hour.')]
    """
    main = [r for r in records if _is_main_thread(r)]
    ordered = [
        r for _, r in sorted(enumerate(main), key=lambda p: (_stamp(p[1]), p[0]))
    ]
    session = key or str(
        next((r.get("sessionId") for r in main if r.get("sessionId")), "") or ""
    )
    out: list[Exchange] = []
    current: dict | None = None

    def close() -> None:
        if current is not None:
            out.append(Exchange(**current))

    for record in ordered:
        if _starts_turn(record):
            close()
            text = _prompt_text(record)
            origin, sender = _origin(record, text)
            if origin == PEER:
                text = _PEER_TAG_RE.sub(" ", text).strip()
            current = {
                "session": session,
                "uuid": str(record.get("uuid") or ""),
                "origin": origin,
                "asked_at": _stamp(record),
                "prompt": text,
                "sender": sender,
                "questions": question_sentences(text) if origin == HUMAN else (),
            }
        elif current is not None and record.get("type") == "assistant":
            said = _text_of(record)
            if said:
                current["reply"] = said
                current["replied_at"] = _stamp(record)
    close()
    return tuple(out)


def _sentences(text: str) -> list[str]:
    body = _FENCE_RE.sub(" ", text)
    found = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith((">", "|", "    ")):
            continue  # quoted, tabular or indented: someone else's words
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
        found.extend(part.strip() for part in _SENTENCE_END_RE.split(line))
    return [s for s in found if s]


def _shouts(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.6


def _asks(sentence: str) -> bool:
    bare = sentence.rstrip(" \"')]*_")
    if len(bare.split()) < MIN_WORDS or _REQUEST_RE.match(bare) or _shouts(bare):
        return False
    if bare.endswith("?"):
        return True
    # Without a question mark only a clear opening counts, and never a lead-in.
    return bool(_ASKS_RE.match(bare)) and ":" not in bare


def question_sentences(text: str) -> tuple[str, ...]:
    """The sentences of a person's prompt that ask something, in order, at most
    :data:`MAX_QUESTIONS`.

    A sentence asks when it ends with ``?`` or opens the way a question does ("why",
    "is there", "I wonder"), and is not a request phrased as one ("can you fix it?").
    Code blocks, quoted lines and table rows are skipped.

    >>> question_sentences("Can you add a test? Could you explain why it failed?")
    ('Could you explain why it failed?',)
    >>> question_sentences("> Why is it slow?\\nok?\\nwhy does the page load twice")
    ('why does the page load twice',)
    """
    seen: list[str] = []
    for sentence in _sentences(text):
        if _asks(sentence) and sentence not in seen:
            seen.append(sentence)
    return tuple(seen[:MAX_QUESTIONS])
