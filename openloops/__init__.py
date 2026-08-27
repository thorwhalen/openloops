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
    "CLOSE_CUES",
    "DEFER_CUES",
    "DISCHARGED",
    "OBLIGATION_FIELDS",
    "OBLIGATION_STATES",
    "OPEN",
    "STATES",
    "UNKNOWN",
    "ClaudeCodeTranscripts",
    "CredentialFound",
    "Digest",
    "GhUnavailable",
    "Locator",
    "Obligation",
    "PredicateOutcome",
    "Session",
    "Verdict",
    "asks_the_human",
    "classify",
    "data_dir",
    "default_source",
    "digest_key",
    "digests_store",
    "gh_issues",
    "ls",
    "make_digest",
    "owed",
    "parse_session",
    "parse_verify",
    "render",
    "retained",
    "scrub",
    "shell_predicate",
    "show",
    "state_dir",
    "status",
    "sync",
]
