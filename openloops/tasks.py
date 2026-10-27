"""Everything you could act on, as one list of task records: gather, classify, merge.

:func:`openloops.owed` answers *"what do I owe, and is it still owed?"* for one label.
A task board needs a wider net and a different answer: every open item across a fleet
that asks something of the human (the `manual-task` issues, the issues titled
"Decide…", the PRs waiting on their review), each turned into a **task record** saying
what to do, where to do it, how long it takes and on which device.

Three steps, each a plain function:

1. :func:`gather` sweeps several owners with ``gh search``, one query per owner and
   kind so no owner's results crowd out another's, with no 50-row cap (the search
   API's own ceiling of 1000 per query is the limit, and a query that reaches it is
   *reported* as saturated, never truncated quietly). Exclusions are keyword arguments.
2. :func:`classify` turns each candidate into a record through a ``classifier=``. The
   default, :func:`heuristic_classify`, is deterministic: label, title and body
   patterns decide the tier, the pattern and the minutes, and the deep-link builders
   point at the exact settings page. No model is called, here or anywhere in
   openloops. The richer path is the classifier brief shipped with the
   ``openloops-phone-board`` skill: a subagent reads each item and writes records in
   the same schema, which :func:`merge_records` lays over the heuristic ones.
3. :func:`merge_records` combines record sources by URL, later sources winning, and
   normalises every record to :data:`TASK_FIELDS`.

The record schema is :class:`Task`, defined once, here. The board page, the build
step and the classifier brief all read it; a field added anywhere else is a field the
others do not know about.

**Read-only, like the rest of openloops.** Gathering runs ``gh search``; nothing here
comments, closes, labels or approves anything.

    >>> candidate = {
    ...     'url': 'https://github.com/acme/widget/issues/7', 'repo': 'acme/widget',
    ...     'number': 7, 'title': 'Add the NPM_TOKEN secret so CI can publish',
    ...     'body': '', 'labels': ['manual-task'], 'created': '2026-08-01',
    ... }
    >>> record = heuristic_classify(candidate)
    >>> record['tier'], record['pattern'], record['id']
    ('browser', 'github-settings', 'acme/widget#7')
    >>> [link['label'] for link in record['links']]
    ['GitHub: Actions secrets', 'Issue']
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, NamedTuple

# The one `gh` shell-out and the owner rule live in `obligations` (see the note in
# `blockers`); this module reuses them rather than growing a second copy.
from openloops.obligations import (
    DFLT_LABEL,
    DFLT_LIST_TIMEOUT,
    GhUnavailable,
    _gh,
    configured_owners,
)

__all__ = [
    "DFLT_SEARCHES",
    "PATTERNS",
    "STATUSES",
    "TASK_FIELDS",
    "TIERS",
    "Rule",
    "Task",
    "classify",
    "gather",
    "github_settings_url",
    "heuristic_classify",
    "load_records",
    "merge_records",
    "npm_access_url",
    "pypi_publishing_url",
]

# --------------------------------------------------------------------------------
# The record schema: the single source of truth.
# --------------------------------------------------------------------------------

#: Where the human does the thing, cheapest first. The board sorts and filters on it.
TIERS = ("tap", "browser", "session", "physical", "mac-only")
#: Whether the item still asks anything of the human.
STATUSES = ("open", "likely-done", "not-for-user", "stale")
#: The controlled vocabulary of repeated chores. A run on the board groups one pattern.
PATTERNS = (
    "npm-trusted-publisher",
    "npm-first-publish",
    "npm-scope",
    "npm-other",
    "pypi-trusted-publisher",
    "pypi-release",
    "api-key",
    "github-settings",
    "server-chore",
    "decision",
    "review-pr",
    "merge-bot-pr",
    "record",
    "device-test",
    "listen-look",
    "live-check",
    "purchase",
    "mac-only",
    "other",
)
KINDS = ("issue", "pr")


@dataclass
class Task:
    """One thing the human could act on. Every record carries every field.

    ``decision`` is ``{question, options, recommendation}`` or ``None``; ``links`` are
    ``{label, url}`` with the item itself last; ``prompt`` is a paste-ready request for
    a coding session (session tier). ``source`` says how the item was found and
    ``created`` when it was opened (``YYYY-MM-DD``).

    >>> Task.from_mapping({'id': 'a/b#1', 'tier': 'nope', 'pattern': 'x'}).tier
    'session'
    """

    id: str
    url: str | None = None
    kind: str = "issue"
    org: str | None = None
    repo: str | None = None
    title: str = ""
    ask: str = ""
    tier: str = "session"
    minutes: int | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    decision: dict[str, Any] | None = None
    prompt: str | None = None
    machine: str | None = None
    unblocks: list[str] = field(default_factory=list)
    pattern: str = "other"
    pattern_key: str | None = None
    status: str = "open"
    note: str | None = None
    source: str | None = None
    created: str | None = None

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> Task:
        """Normalise a record from any source: unknown keys dropped, bad vocabulary fixed.

        A value outside its vocabulary becomes the field's safe default (``session``
        tier, ``other`` pattern, ``open`` status) rather than an error, because one
        sloppy classifier record must not sink a board of three hundred.
        """
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in record.items() if k in known}
        if not values.get("id"):
            values["id"] = _id_of(values.get("url") or "")
        task = cls(**values)
        if task.tier not in TIERS:
            task.tier = "session"
        if task.pattern not in PATTERNS:
            task.pattern = "other"
        if task.status not in STATUSES:
            task.status = "open"
        if task.kind not in KINDS:
            task.kind = "pr" if "/pull/" in (task.url or "") else "issue"
        task.links = list(task.links or [])
        task.unblocks = list(task.unblocks or [])
        return task

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return asdict(self)


#: Every key on every record, in schema order.
TASK_FIELDS = tuple(f.name for f in fields(Task))


def _id_of(url: str) -> str:
    """``owner/repo#N`` from an issue or PR URL; the URL itself when it is not one.

    >>> _id_of('https://github.com/acme/widget/pull/12')
    'acme/widget#12'
    """
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)", url or "")
    return f"{m[1]}#{m[2]}" if m else url


# --------------------------------------------------------------------------------
# Gathering: what is out there.
# --------------------------------------------------------------------------------

#: The search API's own per-query ceiling. A query that returns this many is saturated.
DFLT_GATHER_LIMIT = 1000
#: Extra searches beyond the label, by name: (search terms, the field they match).
DFLT_SEARCHES = {
    "decide": ("Decide", "title"),
    "needs-user": ('"Needs the user"', "body"),
}
#: Environment override for repositories to leave out: owner/name globs, comma- or
#: space-separated (``acme/secret-*``, ``other-org/*``).
EXCLUDE_ENV_VAR = "OPENLOOPS_EXCLUDE_REPOS"
#: How much of an item's body a candidate keeps: enough for the heuristic patterns.
DFLT_BODY_CHARS = 4000

_ISSUE_FIELDS = (
    "number",
    "title",
    "url",
    "repository",
    "createdAt",
    "updatedAt",
    "labels",
    "body",
)


def _split(raw: str | None) -> tuple[str, ...]:
    return tuple(p for p in re.split(r"[,\s]+", raw or "") if p)


def gather(
    *,
    owners: Sequence[str] | None = None,
    exclude_owners: Sequence[str] = (),
    exclude_repos: Sequence[str] | None = None,
    label: str = DFLT_LABEL,
    searches: Sequence[str] = (),
    review_prs: bool = False,
    limit: int = DFLT_GATHER_LIMIT,
    timeout: float = DFLT_LIST_TIMEOUT,
    run_gh: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Every open item that asks something of the human, across ``owners``, deduplicated.

    One query per owner and per kind: the ``label`` (``manual-task``), each named
    search in ``searches`` (keys of :data:`DFLT_SEARCHES`), and with ``review_prs`` the
    open PRs requesting your review. ``owners`` defaults to
    :func:`openloops.obligations.configured_owners`; ``exclude_repos`` (owner/name
    globs) defaults to ``OPENLOOPS_EXCLUDE_REPOS``. ``run_gh`` replaces the ``gh``
    runner (``run_gh(args, timeout=...) -> stdout``).

    The result is an envelope: ``listed`` is ``False`` with an ``error`` when any query
    failed, because a partial sweep presented as a whole one is the failure that
    matters. ``saturated`` names the queries that hit ``limit``.

    >>> def fake(args, *, timeout):
    ...     return json.dumps([{'number': 1, 'title': 'Add a key',
    ...         'url': 'https://github.com/acme/w/issues/1',
    ...         'repository': {'nameWithOwner': 'acme/w'}, 'labels': [], 'body': ''}])
    >>> report = gather(owners=['acme'], run_gh=fake)
    >>> report['listed'], [c['id'] for c in report['candidates']]
    (True, ['acme/w#1'])
    """
    run = run_gh or _gh
    unknown = [name for name in searches if name not in DFLT_SEARCHES]
    if unknown:
        raise ValueError(f"unknown search {unknown}; known: {sorted(DFLT_SEARCHES)}")
    excluded = set(exclude_owners)
    globs = (
        tuple(exclude_repos)
        if exclude_repos is not None
        else _split(os.environ.get(EXCLUDE_ENV_VAR))
    )
    try:
        resolved = tuple(owners) if owners else configured_owners(timeout=timeout)
    except GhUnavailable as exc:
        return _envelope([], owners=(), errors=[str(exc)], saturated=[], queries=[])
    resolved = tuple(o for o in resolved if o not in excluded)

    queries: list[tuple[str, str, list[str]]] = []
    for owner in resolved:
        base = ["--owner", owner, "--state", "open", "--limit", str(limit)]
        queries.append(
            (
                owner,
                f"label:{label}",
                [
                    "search",
                    "issues",
                    *base,
                    "--label",
                    label,
                    "--json",
                    ",".join(_ISSUE_FIELDS),
                ],
            )
        )
        for name in searches:
            terms, match = DFLT_SEARCHES[name]
            queries.append(
                (
                    owner,
                    name,
                    [
                        "search",
                        "issues",
                        *base,
                        "--match",
                        match,
                        "--json",
                        ",".join(_ISSUE_FIELDS),
                        "--",
                        terms,
                    ],
                )
            )
        if review_prs:
            queries.append(
                (
                    owner,
                    "review-requested",
                    [
                        "search",
                        "prs",
                        *base,
                        "--review-requested",
                        "@me",
                        "--json",
                        ",".join(_ISSUE_FIELDS),
                    ],
                )
            )

    seen: dict[str, dict[str, Any]] = {}
    errors, saturated = [], []
    for owner, name, args in queries:
        try:
            rows = json.loads(run(args, timeout=timeout) or "[]")
        except (GhUnavailable, ValueError) as exc:
            errors.append(f"{owner} {name}: {exc}")
            continue
        if not isinstance(rows, list):
            errors.append(f"{owner} {name}: gh returned something other than a list")
            continue
        if len(rows) >= limit:
            saturated.append(f"{owner} {name}")
        for row in rows:
            candidate = _candidate(row, src=name)
            if not candidate["url"] or candidate["url"] in seen:
                continue
            if candidate["repo"].split("/")[0] in excluded or any(
                fnmatch.fnmatch(candidate["repo"], g) for g in globs
            ):
                continue
            seen[candidate["url"]] = candidate
    return _envelope(
        list(seen.values()),
        owners=resolved,
        errors=errors,
        saturated=saturated,
        queries=[f"{o} {n}" for o, n, _ in queries],
    )


def _candidate(row: Mapping[str, Any], *, src: str) -> dict[str, Any]:
    """One search row, flattened to what classification needs."""
    repository = row.get("repository") or {}
    repo = (
        repository.get("nameWithOwner", "")
        if isinstance(repository, Mapping)
        else str(repository)
    )
    url = row.get("url") or ""
    labels = [
        lab.get("name", "") if isinstance(lab, Mapping) else str(lab)
        for lab in row.get("labels") or []
    ]
    return {
        "id": _id_of(url),
        "url": url,
        "kind": "pr" if "/pull/" in url else "issue",
        "repo": repo,
        "number": row.get("number"),
        "title": row.get("title") or "",
        "body": (row.get("body") or "")[:DFLT_BODY_CHARS],
        "labels": labels,
        "src": src,
        "created": (row.get("createdAt") or "")[:10] or None,
        "updated": (row.get("updatedAt") or "")[:10] or None,
    }


def _envelope(candidates, *, owners, errors, saturated, queries) -> dict[str, Any]:
    by_src: dict[str, int] = {}
    for c in candidates:
        by_src[c["src"]] = by_src.get(c["src"], 0) + 1
    return {
        "listed": not errors,
        "error": "; ".join(errors) or None,
        "owners": list(owners),
        "queries": queries,
        "saturated": saturated,
        "counts": {"total": len(candidates), **by_src},
        "candidates": candidates,
    }


# --------------------------------------------------------------------------------
# Deep links: the exact page where the action happens.
# --------------------------------------------------------------------------------


def npm_access_url(package: str) -> str:
    """npm package settings: trusted publisher, publishing access, 2FA requirement.

    >>> npm_access_url('@acme/widget')
    'https://www.npmjs.com/package/@acme/widget/access'
    """
    return f"https://www.npmjs.com/package/{package}/access"


def pypi_publishing_url(project: str | None = None) -> str:
    """PyPI trusted publishers: a project's page, or the pending-publisher page.

    >>> pypi_publishing_url()
    'https://pypi.org/manage/account/publishing/'
    """
    if project:
        return f"https://pypi.org/manage/project/{project}/settings/publishing/"
    return "https://pypi.org/manage/account/publishing/"


#: GitHub repository settings pages, by what the ask mentions.
GITHUB_SETTINGS = {
    "secrets": ("secrets/actions", "GitHub: Actions secrets"),
    "variables": ("variables/actions", "GitHub: Actions variables"),
    "environments": ("environments", "GitHub: environments"),
    "pages": ("pages", "GitHub: Pages settings"),
    "actions": ("actions", "GitHub: Actions settings"),
    "keys": ("keys", "GitHub: deploy keys"),
}


def github_settings_url(repo: str, section: str) -> str:
    """A repository settings page (a key of :data:`GITHUB_SETTINGS`).

    >>> github_settings_url('acme/widget', 'pages')
    'https://github.com/acme/widget/settings/pages'
    """
    return f"https://github.com/{repo}/settings/{GITHUB_SETTINGS[section][0]}"


# --------------------------------------------------------------------------------
# Classifying: the deterministic default.
# --------------------------------------------------------------------------------


class Rule(NamedTuple):
    """A heuristic: when ``regex`` matches title + body, the item is this pattern."""

    pattern: str
    tier: str
    minutes: int
    regex: str


#: Checked in order, first match wins: the specific chores before the general words.
DFLT_RULES = (
    Rule(
        "mac-only",
        "mac-only",
        10,
        r"\b(macos|mac app|keychain|xcode|launchd|on the mac)\b",
    ),
    Rule(
        "npm-first-publish",
        "session",
        10,
        r"npm.*(first publish|not (yet )?on npm|does not exist)|first publish.*npm",
    ),
    Rule(
        "npm-trusted-publisher",
        "browser",
        3,
        r"npm.*trusted publish|trusted publish.*npm",
    ),
    Rule("npm-scope", "browser", 3, r"npm (org|scope)|claim .*scope"),
    Rule(
        "pypi-trusted-publisher",
        "browser",
        3,
        r"pypi.*(trusted|pending) publish|(trusted|pending) publish.*pypi",
    ),
    Rule(
        "pypi-release", "session", 5, r"pypi.*(release|upload)|(release|upload).*pypi"
    ),
    # `\A` anchors to the start of the title: a title phrased as a question or a call to
    # decide is a decision whatever chore words its body goes on to mention.
    Rule(
        "decision",
        "tap",
        2,
        r"\A\s*(decision|decide|confirm|should|reopen|choose|pick)\b|\A[^\n]*\?|\A[^\n]*\bdecide\b",
    ),
    Rule(
        "github-settings",
        "browser",
        3,
        r"\b(secret|deploy key|github pages|environment|actions settings|repo(sitory)? settings)\b",
    ),
    Rule(
        "api-key",
        "browser",
        5,
        r"\b(api key|api token|access token|create (an )?account|sign up)\b",
    ),
    Rule(
        "purchase",
        "browser",
        5,
        r"\b(purchase|buy|paid plan|subscription|invoice|billing)\b",
    ),
    Rule(
        "record",
        "physical",
        15,
        r"\brecord (yourself|a|an|audio|video|your)\b|\bvoice sample\b",
    ),
    Rule(
        "device-test",
        "physical",
        10,
        r"\b(on (a|your) (phone|device)|test on (ios|android|a device))\b",
    ),
    Rule("listen-look", "physical", 10, r"\b(listen to|look at|judge|eyeball)\b"),
    Rule("live-check", "session", 5, r"\blive (check|test|run)\b|\breal (api )?key\b"),
    Rule(
        "server-chore",
        "session",
        5,
        r"\b(deploy|install|ssh|sudo|server|cron|systemd)\b",
    ),
    Rule(
        "decision",
        "tap",
        2,
        r"\b(go-ahead|which option|options?:|recommend(ation|ed)?:?\*\*)",
    ),
)
#: When no rule matches: a manual task does ask something, so it is not "nothing".
DFLT_FALLBACK = Rule("other", "browser", 5, "")

_NPM_PACKAGE = re.compile(r"npmjs\.com/package/(@[\w.-]+/[\w.-]+|[\w.-]+)")
_PYPI_PROJECT = re.compile(r"pypi\.org/(?:project|manage/project)/([\w.-]+)")
_RECOMMEND = re.compile(r"\*\*Recommend(?:ation|ed)?:?\*\*:?\s*(.+)", re.IGNORECASE)
_BOT_PR = re.compile(
    r"^(build\(deps|chore\(deps|bump )|\[bot\]|dependabot|renovate", re.IGNORECASE
)


def heuristic_classify(
    candidate: Mapping[str, Any],
    *,
    rules: Sequence[Rule] = DFLT_RULES,
    machines: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """A task record from a gathered candidate, by patterns alone. No model, no network.

    ``rules`` are tried in order against the title and body; ``machines`` maps an owner
    to the machine its session-tier prompts name. Status is always ``open``: whether an
    ask was already done is a judgement only a reader of the thread can make (the
    classifier brief's job).

    >>> pr = {'url': 'https://github.com/acme/w/pull/3', 'repo': 'acme/w',
    ...       'title': 'Bump lodash from 4.17.20 to 4.17.21', 'body': ''}
    >>> heuristic_classify(pr)['pattern'], heuristic_classify(pr)['links'][0]['url']
    ('merge-bot-pr', 'https://github.com/acme/w/pull/3/files')
    """
    url = candidate.get("url") or ""
    repo = candidate.get("repo") or ""
    org, _, name = repo.partition("/")
    title = candidate.get("title") or ""
    body = candidate.get("body") or ""
    kind = "pr" if "/pull/" in url else "issue"
    text = f"{title}\n{body}"

    if kind == "pr":
        rule = (
            Rule("merge-bot-pr", "tap", 2, "")
            if _BOT_PR.search(title)
            else Rule("review-pr", "tap", 5, "")
        )
    else:
        rule = next(
            (
                r
                for r in rules
                if re.search(r.regex, text, re.IGNORECASE | re.MULTILINE)
            ),
            DFLT_FALLBACK,
        )

    npm = _NPM_PACKAGE.search(text)
    pypi = _PYPI_PROJECT.search(text)
    links: list[dict[str, str]] = []
    if rule.pattern.startswith("npm-") and npm:
        links.append(
            {"label": f"npm: {npm[1]} settings", "url": npm_access_url(npm[1])}
        )
    elif rule.pattern == "pypi-trusted-publisher":
        links.append(
            {
                "label": "PyPI: trusted publishers",
                "url": pypi_publishing_url(pypi[1] if pypi else None),
            }
        )
    elif rule.pattern == "github-settings" and repo:
        section = next(
            (
                s
                for s, words in _SETTINGS_WORDS
                if re.search(words, text, re.IGNORECASE)
            ),
            "secrets",
        )
        links.append(
            {
                "label": GITHUB_SETTINGS[section][1],
                "url": github_settings_url(repo, section),
            }
        )
    elif kind == "pr":
        links.append({"label": "PR: files changed", "url": url.rstrip("/") + "/files"})
    links.append({"label": "PR" if kind == "pr" else "Issue", "url": url})

    decision = None
    if rule.pattern == "decision":
        recommended = _RECOMMEND.search(body)
        decision = {
            "question": title,
            "options": [],
            "recommendation": recommended[1].strip() if recommended else None,
        }

    session = rule.tier == "session"
    return Task.from_mapping(
        {
            "id": candidate.get("id") or _id_of(url),
            "url": url or None,
            "kind": kind,
            "org": org or None,
            "repo": name or None,
            "title": title,
            "ask": title if len(title) <= 120 else title[:117] + "...",
            "tier": rule.tier,
            "minutes": rule.minutes,
            "links": links,
            "decision": decision,
            "prompt": f"Do what {url} asks, run its Verify line if it has one, and comment the result on it."
            if session
            else None,
            "machine": (machines or {}).get(org) if session else None,
            "pattern": rule.pattern,
            "pattern_key": (
                npm[1]
                if npm and rule.pattern.startswith("npm-")
                else pypi[1]
                if pypi and rule.pattern.startswith("pypi-")
                else name or None
            ),
            "status": "open",
            "source": candidate.get("src"),
            "created": candidate.get("created"),
        }
    ).as_dict()


_SETTINGS_WORDS = (
    ("keys", r"deploy key"),
    ("pages", r"github pages|\bpages\b"),
    ("environments", r"environment"),
    ("variables", r"\bvariable"),
    ("secrets", r"secret"),
    ("actions", r"actions settings"),
)


def classify(
    candidates: Iterable[Mapping[str, Any]],
    *,
    classifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] = heuristic_classify,
) -> list[dict[str, Any]]:
    """One normalised record per candidate, through ``classifier``.

    >>> classify([{'url': 'https://github.com/a/b/issues/1', 'title': 'Decide the name'}])[0]['tier']
    'tap'
    """
    return [Task.from_mapping(classifier(c)).as_dict() for c in candidates]


# --------------------------------------------------------------------------------
# Merging record sources.
# --------------------------------------------------------------------------------


def merge_records(*sources: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Records from several sources, one per item, later sources winning.

    Keyed by URL (by ``id`` for an item without one). A later record replaces the
    earlier one whole, except that an empty ``created`` is filled from it: the
    classifier brief reads threads, the gatherer knows dates.

    >>> heuristic = [{'id': 'a/b#1', 'url': 'u1', 'tier': 'browser', 'created': '2026-01-02'}]
    >>> enriched = [{'id': 'a/b#1', 'url': 'u1', 'tier': 'tap', 'ask': 'Say yes'}]
    >>> [(r['tier'], r['ask'], r['created']) for r in merge_records(heuristic, enriched)]
    [('tap', 'Say yes', '2026-01-02')]
    """
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for record in source:
            task = Task.from_mapping(record).as_dict()
            key = task["url"] or task["id"]
            earlier = merged.get(key)
            if earlier and not task["created"]:
                task["created"] = earlier["created"]
            merged[key] = task
    return list(merged.values())


def load_records(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """The records in JSON files (each a list, or an envelope with ``candidates``).

    Globs are expanded, in sorted order, so ``out_*.json`` reads a batch directory.
    """
    found: list[dict[str, Any]] = []
    for raw in paths:
        raw = str(raw)
        for path in sorted(glob.glob(raw)) if glob.has_magic(raw) else [raw]:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, Mapping):
                data = data.get("candidates") or data.get("records") or []
            found.extend(data)
    return found
