"""The default ``transcript_source``: a direct reader of Claude Code's on-disk state.

Claude Code persists one JSONL transcript per session under
``~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl``. :class:`ClaudeCodeTranscripts`
is a ``Mapping`` from session id to :class:`~openloops.base.Session`, so a caller who
wants a different reader — a test fixture, a copy synced from another machine, an
in-house parser — passes any mapping of the same shape and nothing downstream changes.

Two things this reader deliberately does not do.

It never reverses a project directory name back into a working directory. The encoding
is lossy (``/``, ``_`` and ``.`` all become ``-``), so ``cwd`` is read from the records
themselves or left empty.

It never looks at whether a process is running. A session's transcript is a document;
what openloops reports is what the document says. Liveness is a different tool's job,
and mixing the two is how a digest store becomes a session dashboard.

>>> src = ClaudeCodeTranscripts(root='/nonexistent-dir-for-doctest')
>>> len(src)
0
>>> src.revision()
'0'
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from openloops.base import Locator, Session

__all__ = [
    "ClaudeCodeTranscripts",
    "Revisioned",
    "claude_projects_dir",
    "parse_session",
]

#: XML-ish wrappers the CLI logs around non-prose user lines. Stripped from a user
#: prompt so the digest carries what the human typed rather than tooling noise.
_WRAPPER_TAGS = (
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "local-command-caveat",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "system-reminder",
    "user-prompt-submit-hook",
    # Machine-injected turns. Without these a digest renders raw XML — task ids, an
    # output-file path, an agent's result blob — under the heading "What was asked of
    # it, last", which is openloops asserting a human said something they did not.
    "task-notification",
    "system-notification",
    "function_results",
    "attachment",
)
_WRAPPER_PAIR_RE = re.compile(
    r"<(" + "|".join(_WRAPPER_TAGS) + r")\b[^>]*>.*?</\1>", re.DOTALL
)
_WRAPPER_TAG_RE = re.compile(r"</?(?:" + "|".join(_WRAPPER_TAGS) + r")\b[^>]*>")

#: The preamble Claude Code puts in front of a context-compaction summary. Dropping it
#: leaves the summary itself, which is the part worth keeping.
_COMPACT_PREAMBLE_RE = re.compile(
    r"^.*?ran out of context.*?Summary:\s*", re.DOTALL | re.IGNORECASE
)

#: Claude Code appends a UI hint to its recaps. It is advice about the CLI, not about
#: the session, and it does not belong in a record of what the session said.
_RECAP_TRAILER_RE = re.compile(r"\s*\(disable recaps in [^)]*\)\s*$", re.IGNORECASE)

#: Claude Code writes its own one-to-three-sentence end-of-turn recap into the
#: transcript as a ``system`` record with this subtype. It calls them recaps itself.
#: Reading them is retention rather than duplication — they were generated once,
#: already billed, and they vanish with the transcript that holds them.
RECAP_SUBTYPE = "away_summary"

#: ``stop_reason`` on a turn whose text is Claude Code's own usage-limit or API-error
#: banner rather than the assistant's words. Verified: essentially every occurrence in
#: a real corpus is such a banner, not a genuine stop sequence.
ERROR_STOP_REASON = "stop_sequence"

#: A placeholder Claude Code writes in place of a model name on some records. Reporting
#: it as "the model" would be reporting a implementation detail as a fact.
SYNTHETIC_MODEL = "<synthetic>"

#: How many distinct pull-request links a digest carries. Sessions run for days and
#: touch dozens; the digest is a summary, not an index.
MAX_LOCATORS = 12


def claude_projects_dir(root: str | Path | None = None) -> Path:
    """Where Claude Code keeps per-session transcripts.

    Resolution order: the *root* argument, then ``CLAUDE_PROJECTS_DIR``, then
    ``~/.claude/projects``.

    >>> claude_projects_dir('/tmp/x')
    PosixPath('/tmp/x')
    """
    if root is not None:
        return Path(root).expanduser()
    env = os.environ.get("CLAUDE_PROJECTS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude" / "projects"


def _clean_prompt(text: str) -> str:
    """Strip CLI wrapper tags and their content, leaving the human's prose."""
    text = _WRAPPER_PAIR_RE.sub(" ", text)
    text = _WRAPPER_TAG_RE.sub(" ", text)
    return " ".join(text.split()).strip()


def _blocks(record: Mapping) -> list[dict]:
    """The content blocks of a record's message, normalised to a list of dicts."""
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _text_of(record: Mapping) -> str:
    """The natural-language text of a record, thinking and tool blocks excluded."""
    parts = [
        b["text"]
        for b in _blocks(record)
        if b.get("type") == "text"
        and isinstance(b.get("text"), str)
        and b["text"].strip()
    ]
    return "\n\n".join(p.strip() for p in parts).strip()


def _is_tool_result(record: Mapping) -> bool:
    return any(b.get("type") == "tool_result" for b in _blocks(record))


def _is_main_thread(record: Mapping) -> bool:
    """A record on the session's own thread, not inside a sub-agent's sidechain."""
    return not record.get("isSidechain")


def _is_human_prompt(record: Mapping) -> bool:
    """A ``user`` record that is a real prompt: not a tool result, not injected.

    The last clause is the load-bearing one, and an allowlist of wrapper tags is not
    enough on its own: a record whose entire content disappears once the wrappers are
    stripped was never a human speaking, whatever the wrapper happened to be called.
    """
    if record.get("type") != "user" or record.get("isMeta"):
        return False
    if record.get("isCompactSummary") or _is_tool_result(record):
        return False
    return bool(_clean_prompt(_text_of(record)))


def _load_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL transcript, tolerating blank and malformed lines.

    A file that cannot be *read* is a different thing from a file that is empty, and
    the difference matters: swallowing the error would hand back an empty session, whose
    digest is a content-free stub that then overwrites a perfectly good one. So the
    ``OSError`` propagates, and :func:`~openloops._sync.sync` records it and leaves the
    existing digest alone.
    """
    out: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _stamp(record: Mapping) -> str:
    """A record's timestamp as a sortable string, empty when it has none."""
    return str(record.get("timestamp") or "")


def _distinct(values: Iterable[str]) -> tuple[str, ...]:
    """Non-empty values in first-seen order, deduplicated.

    >>> _distinct(['a', '', 'b', 'a'])
    ('a', 'b')
    """
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return tuple(out)


def _titles(records: Iterable[Mapping]) -> tuple[str, str]:
    """The session's ``(label, description)`` titles, last occurrence of each winning.

    Two different strings, not two spellings of one. ``custom-title`` is a short slug
    the user chose and can change mid-session; ``ai-title`` is a generated sentence
    describing the work. Both are re-written on almost every turn, so only the last
    occurrence means anything, and a digest wants the sentence for its heading and the
    slug for identity.
    """
    custom = ai = ""
    for r in records:
        t = r.get("type")
        if t == "custom-title" and r.get("customTitle"):
            custom = str(r["customTitle"])
        elif t == "ai-title" and r.get("aiTitle"):
            ai = str(r["aiTitle"])
    return custom.strip(), ai.strip()


def _ends_with_error(last_text_record: Mapping | None) -> bool:
    """The session's last words are a limit or connection notice, not its own.

    A dangling structured question would be the tidier signal, but Claude Code records
    a tool result for its question tool even when the question is dismissed, so that
    state is not observable from a transcript and no detector here pretends it is.
    """
    if last_text_record is None:
        return False
    stop = (last_text_record.get("message") or {}).get("stop_reason")
    return stop == ERROR_STOP_REASON


def _ended_mid_turn(records: list[dict]) -> bool:
    """The transcript stops before the assistant got the last word.

    True when the final conversational record is an unanswered human prompt, a tool
    result nothing followed, or an assistant message whose last block is a tool call.
    """
    conversational = [
        r
        for r in records
        if r.get("type") in ("user", "assistant") and not r.get("isMeta")
    ]
    if not conversational:
        return False
    last = conversational[-1]
    if last.get("type") == "user":
        return not last.get("isCompactSummary")
    blocks = _blocks(last)
    return bool(blocks) and blocks[-1].get("type") == "tool_use"


def _recap(records: list[dict]) -> tuple[str, str]:
    """The session's own last end-of-turn recap, and when it wrote it.

    One is written per turn, so the latest is the one that describes where the session
    got to. It can still predate the final assistant turn, which is why the digest dates
    it and shows both rather than choosing between them.
    """
    recaps = [
        r
        for r in records
        if r.get("type") == "system" and r.get("subtype") == RECAP_SUBTYPE
    ]
    if not recaps:
        return "", ""
    latest = max(recaps, key=_stamp)
    content = latest.get("content")
    text = content if isinstance(content, str) else _text_of(latest)
    return _RECAP_TRAILER_RE.sub("", (text or "").strip()).strip(), _stamp(latest)


def _compaction(records: list[dict]) -> tuple[str, str]:
    """The last context-compaction summary and its timestamp, or two empty strings."""
    for r in reversed(records):
        if r.get("isCompactSummary"):
            text = _COMPACT_PREAMBLE_RE.sub("", _text_of(r)).strip()
            return text, _stamp(r)
    return "", ""


def _locators(
    records: Iterable[Mapping], *, limit: int = MAX_LOCATORS
) -> tuple[Locator, ...]:
    """Typed pointers the transcript recorded for itself — today, pull-request links.

    A session re-records the same link on nearly every turn (a median of thirty-odd
    records for a handful of distinct pull requests), so the first sighting of each URL
    is kept and the rest dropped. Long-running sessions touch dozens of pull requests,
    hence the bound: a digest is meant to be read.
    """
    out: list[Locator] = []
    seen: set[str] = set()
    for r in records:
        if r.get("type") == "pr-link" and r.get("prUrl"):
            url = str(r["prUrl"])
            if url in seen:
                continue
            seen.add(url)
            out.append(Locator("pr", url=url, at=str(r.get("timestamp") or "")))
            if len(out) >= limit:
                break
    return tuple(out)


def parse_session(records: list[dict], *, key: str = "") -> Session:
    """Read one transcript's records into a :class:`~openloops.base.Session`.

    Pure: same records in, same session out. Everything it reports is a fact about the
    document — no inference, no judgement, and nothing about running processes.

    Three details are corpus-driven rather than obvious, and getting them wrong
    mislabels a large fraction of real sessions:

    - **Start and end come from ``min``/``max`` over every timestamp**, not from the
      first and last line. Transcript lines are not written in timestamp order; on real
      data the first line holds the earliest timestamp only about four times in five.
    - **The project comes from the *first* record's ``cwd``.** Four sessions in five
      visit more than one working directory (scratchpads, sibling repos, task dirs), and
      the last or most-frequent one names a different repository about half the time.
    - **Branches are a tuple.** A third of sessions touch more than one.

    >>> recs = [
    ...     {"type": "user", "sessionId": "s1", "cwd": "/w/proj", "timestamp": "T1",
    ...      "gitBranch": "main",
    ...      "message": {"role": "user", "content": [{"type": "text", "text": "do it"}]}},
    ...     {"type": "assistant", "sessionId": "s1", "timestamp": "T2",
    ...      "message": {"role": "assistant", "model": "m",
    ...                  "content": [{"type": "text", "text": "done"}]}},
    ... ]
    >>> s = parse_session(recs)
    >>> s.key, s.project, s.turn_count, s.last_assistant_text
    ('s1', 'proj', 1, 'done')
    >>> s.started_at, s.ended_at, s.git_branch, s.ended_mid_turn
    ('T1', 'T2', 'main', False)
    """
    main = [r for r in records if _is_main_thread(r)]
    cwd = str(next((r.get("cwd") for r in main if r.get("cwd")), "") or "")
    session_key = key or str(
        next((r.get("sessionId") for r in main if r.get("sessionId")), "") or ""
    )

    prompts = [r for r in main if _is_human_prompt(r)]
    assistants = [r for r in main if r.get("type") == "assistant"]
    with_text = [r for r in assistants if _text_of(r)]
    last_text_record = max(with_text, key=_stamp) if with_text else None
    last_prompt = max(prompts, key=_stamp) if prompts else None

    stamps = sorted(str(r["timestamp"]) for r in main if r.get("timestamp"))
    branches = _distinct(str(r.get("gitBranch") or "") for r in main)
    model = ""
    for r in reversed(assistants):
        candidate = str((r.get("message") or {}).get("model") or "")
        if candidate and candidate != SYNTHETIC_MODEL:
            model = candidate
            break

    custom_title, ai_title = _titles(records)
    recap, recap_at = _recap(records)
    compaction, compaction_at = _compaction(main)
    return Session(
        key=session_key,
        title=custom_title,
        ai_title=ai_title,
        cwd=cwd,
        project=Path(cwd).name if cwd else "",
        git_branches=branches,
        started_at=stamps[0] if stamps else "",
        ended_at=stamps[-1] if stamps else "",
        last_turn_at=_stamp(last_text_record) if last_text_record else "",
        last_user_prompt=_clean_prompt(_text_of(last_prompt)) if last_prompt else "",
        last_prompt_at=_stamp(last_prompt) if last_prompt else "",
        last_assistant_text=_text_of(last_text_record) if last_text_record else "",
        recap=recap,
        recap_at=recap_at,
        compaction=compaction,
        compaction_at=compaction_at,
        turn_count=len(prompts),
        model=model,
        ended_mid_turn=_ended_mid_turn(main),
        ended_with_error=_ends_with_error(last_text_record),
        locators=_locators(records),
    )


class ClaudeCodeTranscripts(Mapping):
    """Claude Code's persisted sessions, as a ``Mapping[str, Session]``.

    ``since_days`` bounds the scan by file modification time (``None`` scans
    everything); ``projects`` keeps only project directories whose name contains one of
    the given substrings; ``skip_scratchpads`` drops the throwaway directories the CLI
    creates under a temp root, which hold agent scratch sessions rather than work.

    ADR-010's revision shape lives here: :meth:`revision` returns an opaque token —
    a file's modification time for one session, a hash over all of them for the
    collection — and :meth:`changed_since` compares against it. mtime is a coarse
    signal that both misses content-preserving rewrites and fires on touches; that
    trade is accepted rather than reprocessing several thousand transcripts a tick.

    >>> src = ClaudeCodeTranscripts(root='/nonexistent-dir-for-doctest')
    >>> list(src), src.changed_since('0')
    ([], False)
    """

    #: Project-directory names starting with this are scratchpads, not work.
    scratchpad_marker = "-private-tmp"

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        since_days: float | None = None,
        projects: Iterable[str] | str | None = None,
        skip_scratchpads: bool = True,
    ):
        self.root = claude_projects_dir(root)
        self.since_days = since_days
        self.projects = (
            [projects] if isinstance(projects, str) else list(projects or ())
        )
        self.skip_scratchpads = skip_scratchpads

    def _index(self) -> dict[str, Path]:
        """Session id → transcript path, newest file winning any collision."""
        if not self.root.is_dir():
            return {}
        cutoff = time.time() - self.since_days * 86400 if self.since_days else None
        found: dict[str, tuple[float, Path]] = {}
        for proj_dir in sorted(self.root.iterdir()):
            if not proj_dir.is_dir():
                continue
            if self.skip_scratchpads and proj_dir.name.startswith(
                self.scratchpad_marker
            ):
                continue
            if self.projects and not any(p in proj_dir.name for p in self.projects):
                continue
            for path in sorted(proj_dir.glob("*.jsonl")):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if cutoff is not None and mtime < cutoff:
                    continue
                prev = found.get(path.stem)
                if prev is None or mtime > prev[0]:
                    found[path.stem] = (mtime, path)
        return {k: v[1] for k, v in found.items()}

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._index()))

    def __len__(self) -> int:
        return len(self._index())

    def __contains__(self, key: object) -> bool:
        return key in self._index()

    def __getitem__(self, key: str) -> Session:
        path = self._index().get(key)
        if path is None:
            raise KeyError(key)
        try:
            records = _load_jsonl(path)
        except OSError as exc:
            raise KeyError(f"{key}: transcript unreadable ({exc.strerror})") from exc
        return parse_session(records, key=key)

    def path_of(self, key: str) -> Path:
        """The transcript file backing *key*."""
        path = self._index().get(key)
        if path is None:
            raise KeyError(key)
        return path

    def revision(self, key: str | None = None) -> str:
        """An opaque change token: for one session, or for the whole collection.

        For a single key it is the transcript's modification time in nanoseconds. For
        the collection it is a hash over every ``(key, mtime)`` pair, so a token can
        be compared without holding the whole index.
        """
        index = self._index()
        if key is not None:
            path = index.get(key)
            if path is None:
                raise KeyError(key)
            return str(path.stat().st_mtime_ns)
        if not index:
            return "0"
        h = hashlib.sha256()
        for k in sorted(index):
            try:
                h.update(f"{k}:{index[k].stat().st_mtime_ns}\n".encode())
            except OSError:
                continue
        return h.hexdigest()[:16]

    def changed_since(self, token: Any, key: str | None = None) -> bool:
        """Whether the current :meth:`revision` differs from *token*."""
        try:
            return self.revision(key) != token
        except KeyError:
            return True


class Revisioned(Mapping):
    """Give any mapping of sessions a total ``revision`` / ``changed_since`` pair.

    ADR-010's rule is that no caller may branch on whether a backend happens to
    implement change detection — capability probing is backend leakage by another name.
    So the probe happens exactly once, here, at the boundary: a wrapped source that
    supplies its own cheap revision token keeps it, and one that does not gets a total
    default (a hash of the value). :func:`~openloops._sync.sync` therefore always has
    the methods and never asks.

    The default is honest rather than fast: hashing requires loading the session, so a
    source with no cheap token gains correctness and no speed. That is the right way
    round — a plain ``dict`` of sessions in a test costs nothing to hash, and the
    on-disk reader supplies mtime.

    >>> from openloops.base import Session
    >>> src = Revisioned({'a': Session(key='a')})
    >>> src.revision('a') == Revisioned({'a': Session(key='a')}).revision('a')
    True
    >>> src.changed_since(src.revision('a'), 'a')
    False
    """

    def __init__(self, source: Mapping[str, Session]):
        self.source = source
        self._own = getattr(source, "revision", None)

    def __iter__(self) -> Iterator[str]:
        return iter(self.source)

    def __len__(self) -> int:
        return len(self.source)

    def __getitem__(self, key: str) -> Session:
        return self.source[key]

    def revision(self, key: str | None = None) -> str:
        """An opaque token that changes when the underlying session changes."""
        if callable(self._own):
            return str(self._own(key))
        if key is None:
            h = hashlib.sha256()
            for k in sorted(self.source):
                h.update(f"{k}:{self.revision(k)}\n".encode())
            return h.hexdigest()[:16]
        payload = repr(self.source[key]).encode("utf-8", errors="replace")
        return hashlib.sha256(payload).hexdigest()[:16]

    def changed_since(self, token: Any, key: str | None = None) -> bool:
        """Whether the current :meth:`revision` differs from *token*."""
        try:
            return self.revision(key) != token
        except KeyError:
            return True
