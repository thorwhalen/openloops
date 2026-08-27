"""What your Claude Code sessions were doing — kept after the transcripts are gone.

Claude Code writes a JSONL transcript for every session and deletes it after about a
month. openloops reads those transcripts, writes one short dated markdown digest per
session, and keeps the digests. Nothing here calls a model, reaches the network, or
needs an account: it reads files you already have and writes files you already own.

    >>> import openloops
    >>> report = openloops.sync()                       # doctest: +SKIP
    >>> for row in openloops.ls(state='open'):          # doctest: +SKIP
    ...     print(row['session'], row['ai_title'] or row['title'])

The whole design rests on one sentence, and everything else follows from it:

> **A digest says what a session said, dated. It never says what is true now.**

So a digest is filed under ``open/`` or ``archive/`` by what the session's own last
turn *read* like — not by whether a process is running, which would make this a session
dashboard rather than a record of open loops. Nothing is asserted to be still
outstanding, because openloops has checked nothing against the world.

The two modules whose primary export shares their name — the sync engine and the
classifier — are private (``openloops._sync``, ``openloops._classify``), because a
module and a function cannot both answer to ``openloops.sync``. Everything they export
is re-exported here, including the classifier's cue tables.

Two seams, both one keyword argument, both defaulting to something that works out of
the box: ``transcript_source=`` (a reader of Claude Code's on-disk layout) and
``digests_store=`` (a directory of markdown files under ``~/.local/share/openloops/``).
Swap either for a test fixture, a git-synced directory, or blob storage without
touching anything else.

There is a second thing here, added later and kept deliberately small:
``openloops.owed()`` lists the open ``manual-task`` issues your agents filed when they
got blocked on you, and — this is its whole reason to exist — re-runs the shell
predicate each issue carries before showing it, so an obligation discharged out of band
reads *discharged* rather than sitting open for months. It reads and reports; it never
closes, relabels or writes anything, and it keeps no copy of anything: the label is the
record. Its trust boundary (evaluating a predicate executes text from an issue body)
and its kill criterion are both written out in :mod:`openloops.obligations`.

    >>> report = openloops.owed()                       # doctest: +SKIP
    >>> report['counts']                                # doctest: +SKIP
    {'open': 6, 'discharged': 1, 'unknown': 2, 'with_predicate': 7, 'total': 9}

And a third thing, which is the same thing pointed at a repository instead of at a
person: ``openloops.blocked()``. When an agent working in repo X finds the real fix
belongs in repo Y, it files in Y and moves on — and X is never told when Y is fixed, so
the workaround in X quietly becomes architecture. GitHub's issue dependencies already
record that edge across repositories; what nothing does is notice when the blocker
closes, because the edge is queryable rather than eventful. ``blocked()`` resolves every
edge and reports ``unblocked`` (every blocker resolved: the work is free and nobody has
been told), ``blocked`` (naming the foreign repository) and ``unknown``. It reads and
reports; it writes nothing. What its discovery step is measured to over-report, what
bounds its one-call-per-issue resolution, and its kill criterion are all in
:mod:`openloops.blockers`.

    >>> report = openloops.blocked()                    # doctest: +SKIP
    >>> [r['repo'] + '#' + str(r['number'])             # doctest: +SKIP
    ...  for r in report['rows'] if r['state'] == 'unblocked']
    ['acme/widget#109']

All three of those are plumbing, and the surface most people actually want is an agent
that knows how to use the plumbing and tells them what matters. So the package also
ships that agent, as files: a ``openloops`` skill that answers "what is being done, and
what needs my attention?", a ``openloops-needs-human`` skill that files the
``manual-task`` issues ``owed()`` later reads back, and an ``openloops-sweep`` subagent
that runs the whole sweep in a fresh context. ``install_skills()`` links them into an
agent host; see :mod:`openloops.skills` for why it links rather than copies and why it
never overwrites.

    >>> plan = openloops.install_skills(dry_run=True)    # doctest: +SKIP
    >>> [row['name'] for row in plan['actions']]         # doctest: +SKIP
    ['openloops', 'openloops-needs-human', 'openloops-sweep']

And a page to look at instead of reading three command outputs:
``openloops.render_dashboard()`` turns those same three answers into one self-contained
HTML document — no stylesheet, no script, no font, nothing fetched from anywhere.
Because it fetches nothing it also *checks* nothing, so it is a **snapshot**: it stamps
the moment it was made and says so in its largest type, and any figure it could not
establish reads ``?`` rather than ``0``. ``ol dashboard`` writes one.

    >>> page = openloops.render_dashboard(                # doctest: +SKIP
    ...     openloops.owed(), openloops.blocked(), openloops.ls(limit=0))

**Still not here, and deliberately:** a ledger. No store, no schema, no history, no
event log, no cross-repo links, no session model, and no write path of any kind.
"""

from openloops.base import (
    ARCHIVE,
    OPEN,
    STATES,
    Digest,
    Locator,
    Session,
    Verdict,
)
from openloops._classify import (
    ASK_CUES,
    CLOSE_CUES,
    DEFER_CUES,
    asks_the_human,
    classify,
)
from openloops.blockers import (
    BLOCKED,
    BLOCKED_FIELDS,
    BLOCKER_STATES,
    UNBLOCKED,
    BlockedIssue,
    Blocker,
    blocked,
    gh_blocked_by,
    gh_blocked_candidates,
)
from openloops.dashboard import headline_counts, render_dashboard
from openloops.digest import make_digest, render
from openloops.egress import CredentialFound, scrub
from openloops.obligations import (
    DISCHARGED,
    OBLIGATION_FIELDS,
    OBLIGATION_STATES,
    UNKNOWN,
    GhUnavailable,
    Obligation,
    PredicateOutcome,
    gh_issues,
    owed,
    parse_verify,
    shell_predicate,
)
from openloops.skills import agents_dir, install_skills, skills_dir
from openloops.store import (
    data_dir,
    default_source,
    digest_key,
    digests_store,
    state_dir,
)
from openloops._sync import retained, sync
from openloops.tools import ls, show, status
from openloops.transcripts import ClaudeCodeTranscripts, parse_session

__all__ = [
    "ARCHIVE",
    "ASK_CUES",
    "BLOCKED",
    "BLOCKED_FIELDS",
    "BLOCKER_STATES",
    "CLOSE_CUES",
    "DEFER_CUES",
    "DISCHARGED",
    "OBLIGATION_FIELDS",
    "OBLIGATION_STATES",
    "OPEN",
    "STATES",
    "UNBLOCKED",
    "UNKNOWN",
    "BlockedIssue",
    "Blocker",
    "ClaudeCodeTranscripts",
    "CredentialFound",
    "Digest",
    "GhUnavailable",
    "Locator",
    "Obligation",
    "PredicateOutcome",
    "Session",
    "Verdict",
    "agents_dir",
    "asks_the_human",
    "blocked",
    "classify",
    "data_dir",
    "default_source",
    "digest_key",
    "digests_store",
    "gh_blocked_by",
    "gh_blocked_candidates",
    "gh_issues",
    "headline_counts",
    "install_skills",
    "ls",
    "make_digest",
    "owed",
    "parse_session",
    "parse_verify",
    "render",
    "render_dashboard",
    "retained",
    "scrub",
    "shell_predicate",
    "show",
    "skills_dir",
    "state_dir",
    "status",
    "sync",
]
