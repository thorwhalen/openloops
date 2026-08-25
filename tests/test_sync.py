"""The sync loop, and the design tests ADR-018 requires of it."""

import sys

import pytest

from fixtures import (
    asking_session,
    assistant,
    closed_session,
    interrupted_session,
    stamp,
    user,
    write_transcripts,
)

from openloops.base import Session
from openloops.store import digests_store, load_sync_state
from openloops._sync import retained, sync, sync_report_lines
from openloops.transcripts import ClaudeCodeTranscripts


def three_sessions(projects_dir):
    write_transcripts(
        projects_dir,
        {
            "s1": closed_session("s1"),
            "s2": asking_session("s2"),
            "s3": interrupted_session("s3"),
        },
    )
    return ClaudeCodeTranscripts()


def test_a_first_sync_writes_one_digest_per_session(projects_dir):
    store = {}
    result = sync(transcript_source=three_sessions(projects_dir),
                  digests_store=store, source="m")
    assert result["written"] == 3
    assert sorted(store) == ["m/archive/s1.md", "m/open/s2.md", "m/open/s3.md"]


def test_a_second_sync_reads_nothing_and_writes_nothing(projects_dir):
    source, store = three_sessions(projects_dir), {}
    sync(transcript_source=source, digests_store=store, source="m")
    again = sync(transcript_source=source, digests_store=store, source="m")
    assert (again["written"], again["unchanged"]) == (0, 3)


def test_regenerating_from_scratch_changes_no_answer(projects_dir, isolated_dirs):
    """ADR-018's design test: a digest is a derived view, never a store.

    Delete the digests *and* the cache, sync again, and every digest whose transcript
    still exists comes back byte-for-byte. If this ever fails, something has started
    living only in the digest folder.
    """
    source = three_sessions(projects_dir)
    store = digests_store()
    sync(transcript_source=source, digests_store=store, source="m")
    before = {key: store[key] for key in store}
    assert before

    for key in list(store):
        del store[key]
    (isolated_dirs / "state" / "sync-state.json").unlink()

    sync(transcript_source=source, digests_store=digests_store(), source="m")
    after = {key: store[key] for key in digests_store()}
    assert after == before


def test_force_produces_the_identical_store(projects_dir):
    source, store = three_sessions(projects_dir), {}
    sync(transcript_source=source, digests_store=store, source="m")
    before = dict(store)
    sync(transcript_source=source, digests_store=store, source="m", force=True)
    assert store == before


def test_a_reclassified_session_moves_rather_than_duplicating():
    open_session = Session(key="s1", last_assistant_text="Blocked on your review.")
    store = {}
    sync(transcript_source={"s1": open_session}, digests_store=store, source="m")
    assert sorted(store) == ["m/open/s1.md"]

    closed = Session(key="s1", last_assistant_text="Merged. Nothing is pending.")
    result = sync(transcript_source={"s1": closed}, digests_store=store, source="m",
                  force=True)
    assert sorted(store) == ["m/archive/s1.md"]
    assert result["moved"] == 1


def test_a_deleted_digest_is_rebuilt_even_when_the_cache_says_otherwise(projects_dir):
    source, store = three_sessions(projects_dir), {}
    sync(transcript_source=source, digests_store=store, source="m")
    del store["m/open/s2.md"]
    result = sync(transcript_source=source, digests_store=store, source="m")
    assert "m/open/s2.md" in store
    assert result["written"] == 1


def test_a_credential_skips_one_session_loudly_and_writes_nothing_for_it():
    leaked = Session(key="bad", last_assistant_text="token " + "gh" + "p_" + "A" * 36)
    fine = Session(key="ok", last_assistant_text="Merged. Nothing is pending.")
    store = {}
    result = sync(transcript_source={"bad": leaked, "ok": fine},
                  digests_store=store, source="m")
    assert sorted(store) == ["m/archive/ok.md"]
    assert [e["session"] for e in result["errors"]] == ["bad"]
    assert "bad" not in load_sync_state()

    lines = "\n".join(sync_report_lines(result))
    assert "SKIPPED" in lines and "nothing was redacted" in lines
    assert "gh" + "p_" + "A" * 36 not in lines


def test_a_skipped_session_is_retried_on_the_next_run():
    leaked = Session(key="bad", last_assistant_text="token " + "gh" + "p_" + "A" * 36)
    store = {}
    for _ in range(2):
        result = sync(transcript_source={"bad": leaked}, digests_store=store, source="m")
        assert len(result["errors"]) == 1


def test_digests_outlive_their_transcripts_and_are_counted_separately(projects_dir):
    source, store = three_sessions(projects_dir), {}
    sync(transcript_source=source, digests_store=store, source="m")

    source.path_of("s2").unlink()
    survivors = ClaudeCodeTranscripts()
    result = sync(transcript_source=survivors, digests_store=store, source="m")

    assert "m/open/s2.md" in store, "a digest must survive its transcript"
    assert result["scanned"] == 2
    assert retained(store, survivors, source="m") == ["m/open/s2.md"]


def test_the_report_names_every_number_it_claims():
    line = sync_report_lines(
        {"source": "m", "scanned": 3, "written": 1, "unchanged": 2, "moved": 0,
         "digests": 9, "errors": []}
    )[0]
    for fragment in ("m:", "3 sessions", "1 digest written", "2 unchanged", "9 digests"):
        assert fragment in line


def test_sync_works_with_no_claude_directory_at_all(isolated_dirs):
    """The suite has to pass on a machine that has never run Claude Code."""
    result = sync(digests_store={}, source="m")
    assert result["scanned"] == 0 and result["errors"] == []


def test_an_emptied_transcript_never_destroys_the_digest_it_already_produced(projects_dir):
    """A retention device losing the only surviving record is its worst failure mode.

    Truncation is the easy trigger and involves no error at all: the file reads as zero
    records, the session parses as empty, and its content-free digest would overwrite a
    good one — permanently, because the mtime has moved so nothing revisits it.
    """
    write_transcripts(projects_dir, {"s1": closed_session("s1")})
    source, store = ClaudeCodeTranscripts(), {}
    sync(transcript_source=source, digests_store=store, source="m")
    good = store["m/archive/s1.md"]
    assert "Fixed and merged" in good

    source.path_of("s1").write_text("")
    result = sync(transcript_source=ClaudeCodeTranscripts(), digests_store=store,
                  source="m", force=True)

    assert store.get("m/archive/s1.md") == good, "the good digest must stand"
    assert [e["session"] for e in result["errors"]] == ["s1"]
    assert result["written"] == 0


@pytest.mark.skipif(
    sys.platform == "win32", reason="chmod does not make a file unreadable on Windows"
)
def test_an_unreadable_transcript_is_reported_not_swallowed(projects_dir):
    write_transcripts(projects_dir, {"s1": closed_session("s1")})
    source = ClaudeCodeTranscripts()
    path = source.path_of("s1")
    path.chmod(0o000)
    try:
        result = sync(transcript_source=ClaudeCodeTranscripts(), digests_store={},
                      source="m", force=True)
    finally:
        path.chmod(0o644)
    assert [e["session"] for e in result["errors"]] == ["s1"]
    assert "unreadable" in result["errors"][0]["problem"]
