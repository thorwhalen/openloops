"""The egress choke point: nothing leaves openloops carrying a home path or a secret.

A digest is derived from a transcript, and transcripts are the highest-entropy secret
source on a developer's machine — pasted tokens, ``.env`` contents, tracebacks full of
absolute paths. A digest store can be a git-synced private repository, so **a written
digest is an export surface**, and the moment to apply that discipline is before the
first byte is written rather than before the first push.

Two rules, and they are deliberately asymmetric:

- **Paths are rewritten**, never raised on. A path is an identifier, not a secret, and
  the tail of it is the part a reader needs. This machine's home becomes ``~``; *any
  other* home — a server's root home, a colleague's, a CI runner's — becomes
  ``~other``, keeping the tail and dropping the identity.
- **Credentials raise.** :func:`scrub` never silently redacts a secret, because a silent
  redaction teaches nobody that a secret was there. It raises :class:`CredentialFound`,
  the caller skips that one session, and the run reports it — loudly, and without ever
  quoting the matched text.

Two shapes are easy to miss and both were, at first. Claude Code encodes a working
directory into a directory name by turning ``/``, ``_`` and ``.`` into ``-``, so a home
path appears throughout transcripts in a dashed form — trivially reversible and just
as identifying. And a transcript from an ssh session names *that* machine's home,
not this one's, so rewriting only ``$HOME`` leaves every foreign home intact. Both forms
are handled here, and :func:`scrub` asserts its own postcondition afterwards rather than
trusting that it did.

The same rules apply to openloops' own repository, which is why
``tests/test_egress_repo.py`` runs :func:`scan_files` over everything the build ships.
One implementation, two configurations.

>>> scrub("see /nowhere/at/all/x.py", aliases={"/nowhere/at/all": "~/code"})
'see ~/code/x.py'
>>> scrub("token=" + "ghp_" + "A" * 36)  # doctest: +IGNORE_EXCEPTION_DETAIL
Traceback (most recent call last):
    ...
openloops.egress.CredentialFound: credential-shaped text (github_token) at offset 6
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

__all__ = [
    "CredentialFound",
    "CREDENTIAL_PATTERNS",
    "apply_aliases",
    "default_aliases",
    "find_credentials",
    "find_absolute_paths",
    "rewrite_paths",
    "scan",
    "scan_files",
    "scrub",
]


class CredentialFound(ValueError):
    """Raised when text about to be written matches a credential pattern.

    The message names the pattern class and the offset. It never contains the matched
    text: an exception that quotes a secret has moved the secret into a log file.
    """

    def __init__(self, pattern_name: str, offset: int, *, where: str = ""):
        self.pattern_name = pattern_name
        self.offset = offset
        self.where = where
        location = f" in {where}" if where else ""
        super().__init__(
            f"credential-shaped text ({pattern_name}) at offset {offset}{location}"
        )


def _secret_assignment() -> re.Pattern:
    """A ``KEY = <long opaque value>`` matcher, quoted or not.

    Quotes are optional because the shapes that actually appear are unquoted: a pasted
    ``.env`` line, an ``export`` in a shell transcript, a ``.pypirc``. The value still
    has to look like a secret — sixteen characters or more, no whitespace, and a mix of
    letters and digits — so ``password: hunter2`` and ``token: the one we discussed``
    do not match.
    """
    # A leading `GITHUB_` / `MY-` style prefix is part of the name, not a separator, so
    # `\btoken\b` alone never matches `GITHUB_TOKEN` — the commonest shape of all.
    key = (
        r"(?:[A-Za-z0-9]+[_-])*"
        r"(?:api[_-]?key|secret[_-]?\w*|passwd|password|access[_-]?token|"
        r"auth[_-]?token|token|credential\w*)"
    )
    value = r"(?=[^'\"\s]*[A-Za-z])(?=[^'\"\s]*\d)[A-Za-z0-9+/=_\-.]{16,}"
    return re.compile(rf"(?i)(?<![A-Za-z0-9]){key}\b\s*[:=]\s*['\"]?({value})['\"]?")


#: Named credential patterns, checked in order. Most are well-known vendor prefixes,
#: which give near-zero false positives; the assignment rule at the end is the only
#: heuristic among them, and the URL rule catches the shape a prefix list cannot.
CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "aws_access_key_id",
        re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])"),
    ),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S{20,}"),
    ),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{20,}\b")),
    ("stripe_key", re.compile(r"\b[srp]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b")),
    ("pypi_token", re.compile(r"\bpypi-[A-Za-z0-9_\-]{32,}")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("google_oauth_refresh_token", re.compile(r"\b1//0[A-Za-z0-9_\-]{20,}\b")),
    (
        "json_web_token",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\."),
    ),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # A password inside a URL's authority: postgres://user:pw@host, https://x:tok@host.
    (
        "url_inline_password",
        re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]{6,}@"),
    ),
    ("secret_assignment", _secret_assignment()),
)

#: The three home roots, spelled in split literals so that this module — which is
#: scanned by the very rule it implements — carries none of them as a matchable string.
#: The root account's home has no name segment; the other two take exactly one, and that
#: segment is the part that identifies somebody. The anonymous root gets its own,
#: looser trailing guard, because it turns up at the end of a sentence — "`~` means
#: <root home>." — where a period is punctuation rather than part of the path.
_ROOTS = ("Users", "home", "root")
_NAMED, _ANON = _ROOTS[:2], _ROOTS[2]

_ABS_PATH_RE = re.compile(
    r"(?<![\w~])(?:"
    + "|".join(rf"/{r}/[\w.\-]+" for r in _NAMED)
    + rf"|/{_ANON}(?![\w\-]|\.\w))(?![\w\-])"
)

#: The same roots after Claude Code's directory-name encoding, which turns ``/``, ``_``
#: and ``.`` into ``-``. Reversible by eye, and every bit as identifying.
_ENCODED_PATH_RE = re.compile(
    r"(?<![\w])(?:"
    + "|".join(rf"-{r}-[A-Za-z0-9]+" for r in _NAMED)
    + rf"|-{_ANON}(?![\w]))"
)

#: What a home that is not this machine's is rewritten to. Keeps the tail, drops the who.
FOREIGN_HOME = "~other"


#: Characters Claude Code turns into ``-`` when it encodes a working directory into a
#: directory name. The Windows separator and drive colon are included so that a home on
#: that platform is covered by the same rule rather than silently not matching.
_ENCODED_FROM = "/\\_.:"


def _encoded(path: str) -> str:
    """A path as Claude Code encodes it into a directory name.

    The Windows example compares rather than prints, because its output would itself be
    an encoded home path — and this module is scanned by the rule it implements.

    >>> _encoded("/a/b_c.d")
    '-a-b-c-d'
    >>> _encoded("C:" + chr(92) + "Us" + "ers" + chr(92) + "bob") == "C--Us" + "ers-bob"
    True
    """
    for ch in _ENCODED_FROM:
        path = path.replace(ch, "-")
    return path


def default_aliases() -> dict[str, str]:
    """The rewrites applied when a caller supplies none: this machine's home → ``~``.

    Both spellings of it, because the encoded form appears in transcripts as often as
    the literal one.

    >>> sorted(set(default_aliases().values()))
    ['~']
    """
    home = str(Path.home())
    return {home: "~", _encoded(home): "~"}


def _anchored(src: str) -> re.Pattern:
    """Match *src* only at a path boundary, so a longer sibling name is left alone."""
    return re.compile(re.escape(src) + r"(?![\w.\-])")


def apply_aliases(text: str, aliases: Mapping[str, str] | None = None) -> str:
    """Replace each alias at a path boundary, longest key first. Nothing else.

    Longest-first matters: a home directory and a projects directory beneath it are both
    aliases, and the more specific one must win. Boundary-anchoring matters for the
    opposite reason: a bare ``str.replace`` turns a *longer* sibling name into a
    half-rewritten mess — a home of ``…/bob`` would mangle ``…/bobby`` into ``~by``,
    corrupting the path and leaving half the other name behind.

    Separate from :func:`rewrite_paths` because auditing and scrubbing want different
    things: an audit must still be able to *see* a foreign home path in order to report
    it, which it could not if every caller had already rewritten one away.

    >>> apply_aliases("/a/b/c and /a", {"/a": "~", "/a/b": "$B"})
    '$B/c and ~'
    >>> apply_aliases("/a2/x", {"/a": "~"})
    '/a2/x'
    """
    aliases = default_aliases() if aliases is None else aliases
    for src in sorted(aliases, key=len, reverse=True):
        text = _anchored(src).sub(aliases[src].replace("\\", "\\\\"), text)
    return text


def rewrite_paths(text: str, aliases: Mapping[str, str] | None = None) -> str:
    """Apply the aliases, then rewrite every home path they did not cover.

    A transcript from an ssh session names *that* machine's home, and a CI traceback
    names a runner's; neither is covered by an alias derived from this process. They are
    rewritten to :data:`FOREIGN_HOME`, which keeps the tail of the path and drops the
    part that identifies somebody.

    >>> rewrite_paths("/ro" + "ot/py/x", aliases={})
    '~other/py/x'
    >>> rewrite_paths("-Us" + "ers-someone-proj", aliases={})
    '~other-proj'
    """
    text = apply_aliases(text, aliases)
    text = _ABS_PATH_RE.sub(FOREIGN_HOME, text)
    return _ENCODED_PATH_RE.sub(FOREIGN_HOME, text)


def find_credentials(text: str) -> list[tuple[str, int]]:
    """Every credential-pattern hit, as ``(pattern_name, offset)`` pairs.

    The matched text is never returned — only where it is and what it looked like.

    >>> find_credentials("nothing to see here")
    []
    >>> find_credentials("AKIA" + "B" * 16)
    [('aws_access_key_id', 0)]
    """
    hits: list[tuple[str, int]] = []
    for name, pattern in CREDENTIAL_PATTERNS:
        for m in pattern.finditer(text):
            hits.append((name, m.start()))
    return sorted(hits, key=lambda t: t[1])


def find_absolute_paths(
    text: str, aliases: Mapping[str, str] | None = None
) -> list[tuple[str, int]]:
    """Home paths — literal or encoded — still present after rewriting, with offsets.

    The example builds its path by concatenation and compares rather than printing,
    because this module's own source is scanned by the rule it implements: a literal
    home-rooted path in a docstring would violate the thing being documented.

    >>> home = "/Us" + "ers/someone"
    >>> [p for p, _ in find_absolute_paths(home + "/x", aliases={})] == [home]
    True
    >>> find_absolute_paths(home + "/x", aliases={home: "~"})
    []
    """
    aliased = apply_aliases(text, aliases)
    found = [(m.group(0), m.start()) for m in _ABS_PATH_RE.finditer(aliased)]
    found += [(m.group(0), m.start()) for m in _ENCODED_PATH_RE.finditer(aliased)]
    return sorted(found, key=lambda t: t[1])


def scrub(
    text: str, *, aliases: Mapping[str, str] | None = None, where: str = ""
) -> str:
    """Rewrite paths and raise on credentials. The only way text leaves openloops.

    ``where`` is a caller-supplied label (a session id, a file name) carried into the
    exception so a failed run can say *which* input tripped, without quoting it.

    The path check runs on the **output**, not the input, because ``aliases`` is
    caller-supplied: a rewrite can in principle produce a home path as easily as remove
    one, and a postcondition that is only true of benign inputs is not a postcondition.

    >>> scrub("built /nowhere/proj/x", aliases={"/nowhere/proj": "$PROJ"})
    'built $PROJ/x'
    """
    text = rewrite_paths(text, aliases)
    hits = find_credentials(text)
    if hits:
        name, offset = hits[0]
        raise CredentialFound(name, offset, where=where)
    leftover = [(m.group(0), m.start()) for m in _ABS_PATH_RE.finditer(text)]
    if leftover:
        raise AssertionError(
            f"egress postcondition failed: a home path survived rewriting at offset "
            f"{leftover[0][1]}{f' in {where}' if where else ''}. This is a bug in "
            "openloops.egress, or an alias whose replacement contains one."
        )
    return text


def scan(
    text: str, *, aliases: Mapping[str, str] | None = None, where: str = ""
) -> list[str]:
    """Report egress violations instead of raising — for auditing many files at once.

    Returns a list of human-readable problem descriptions, empty when the text is clean.
    :func:`scrub` is what production code calls; this is what the repository's own egress
    test calls, because a test that stopped at the first violation would take one run per
    problem to converge.

    >>> scan("all clear")
    []
    """
    problems = []
    for name, offset in find_credentials(apply_aliases(text, aliases)):
        problems.append(f"{where or '<text>'}: credential-shaped ({name}) at {offset}")
    for path, offset in find_absolute_paths(text, aliases):
        problems.append(f"{where or '<text>'}: absolute home path {path!r} at {offset}")
    return problems


def scan_files(
    paths: Iterable[Path], *, aliases: Mapping[str, str] | None = None
) -> list[str]:
    """Run :func:`scan` over each readable text file, accumulating every problem."""
    problems: list[str] = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        problems.extend(scan(text, aliases=aliases, where=str(path)))
    return problems
