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

**Not in this release, and deliberately:** anything that tracks what you owe or are
owed. That is the project's headline claim and it is withheld pending a measurement —
see the README.
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
    "OPEN",
    "STATES",
    "ClaudeCodeTranscripts",
    "CredentialFound",
    "Digest",
    "Locator",
    "Session",
    "Verdict",
    "asks_the_human",
    "classify",
    "data_dir",
    "default_source",
    "digest_key",
    "digests_store",
    "ls",
    "make_digest",
    "parse_session",
    "render",
    "retained",
    "scrub",
    "show",
    "state_dir",
    "status",
    "sync",
]
