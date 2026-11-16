"""Is a ``manual-task`` verify predicate a pure read?

``ol owed`` *executes* the shell command an issue carries, to see whether the ask has
been done since. A question ("what do I owe?") must not have a write effect, but a
predicate is free text from an issue body: one ran ``gh workflow run`` and every
``ol owed`` started a deploy (openloops#43).

This module is the guard. :func:`write_effect` names the first write verb it finds in a
command, or returns ``""`` for a command that looks like a read. It is a **denylist
over text, not a sandbox**: it catches the verbs people actually write (``gh`` mutations,
``curl -X POST``, ``git push``, ``rm``, a redirect into a file) and nothing cleverer, so
a predicate that hides a write behind a script still runs. It exists so the honest
mistake is refused, and so ``owed`` can say *why* a row went unverified. The patterns
are data (:data:`WRITE_PATTERNS`); pass ``patterns=`` to extend or replace them.

    >>> write_effect('gh workflow run deploy.yml --repo o/r')
    'gh workflow run'
    >>> write_effect('gh pr view 3 --json state -q .state | grep -q MERGED')
    ''
    >>> write_effect('curl -s -X POST https://example.com/x')
    'curl with a write method or body'
    >>> write_effect('test -f ~/.config/x && echo ok > /dev/null')
    ''
"""

from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = ["WRITE_PATTERNS", "write_effect"]

_GH = r"\bgh\s+"

#: ``(label, regex)``; the label is what a reader is shown. Case-insensitive.
WRITE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("gh workflow run", _GH + r"workflow\s+(run|enable|disable)\b"),
    (
        "gh pr/issue mutation",
        _GH
        + r"(pr|issue)\s+(merge|close|reopen|create|edit|comment|delete|review|ready|lock|unlock|transfer|develop)\b",
    ),
    (
        "gh release/repo/run/secret mutation",
        _GH
        + r"(release\s+(create|delete|edit|upload)|repo\s+(create|delete|edit|fork|rename|archive|sync)"
        + r"|run\s+(rerun|cancel|delete)|secret\s+(set|delete|remove)|variable\s+(set|delete)"
        + r"|label\s+(create|delete|edit|clone)|gist\s+(create|edit|delete))\b",
    ),
    (
        "gh api with a write method or fields",
        _GH
        + r"api\b(?=[^|;&\n]*(?:(?:-X|--method)[ =]*['\"]?(?:POST|PUT|PATCH|DELETE)\b"
        + r"|\s(?:-f|-F|--field|--raw-field|--input)\b))(?![^|;&\n]*(?:-X|--method)[ =]*['\"]?GET\b)",
    ),
    (
        "curl with a write method or body",
        r"\bcurl\b[^|;&\n]*?(?:-X\s*['\"]?(?:POST|PUT|PATCH|DELETE)\b"
        + r"|--request[ =]['\"]?(?:POST|PUT|PATCH|DELETE)\b|\s-d\b|--data\S*|\s-F\b|--form\b"
        + r"|\s-T\b|--upload-file\b|--json\b)",
    ),
    (
        "git write",
        r"\bgit\s+(push|commit|merge|reset|rebase|clean|pull|tag|stash|cherry-pick|am|apply)\b",
    ),
    (
        "file or process mutation",
        r"(?:^|[|;&(]\s*)(?:sudo\s+)?(rm|mv|rmdir|kill|pkill|killall|tee|chmod|chown|truncate)\b",
    ),
    ("sed -i", r"\bsed\s+(?:-\w*\s+)*-i\b"),
    ("redirect into a file", r"(?<![0-9&>])>{1,2}\s*(?!/dev/null|&)[^\s]"),
)

_COMPILED = tuple(
    (label, re.compile(pattern, re.IGNORECASE)) for label, pattern in WRITE_PATTERNS
)


def write_effect(
    command: str, *, patterns: Iterable[tuple[str, re.Pattern]] | None = None
) -> str:
    """The label of the first write verb in *command*, or ``""`` if it looks read-only."""
    for label, pattern in _COMPILED if patterns is None else patterns:
        if pattern.search(command or ""):
            return label
    return ""
