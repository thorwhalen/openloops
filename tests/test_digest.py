"""The honesty rules, as tests. Each one names the ADR failure it prevents."""

import re

import pytest

from openloops.base import Locator, Session, Verdict
from openloops.digest import SECTION_LIMITS, make_digest, render
from openloops.egress import CredentialFound


def full_session(**kw):
    base = dict(
        key="s1",
        title="demo",
        ai_title="Fix the widget",
        project="widget",
        git_branches=("main", "feat/x"),
        started_at="2026-01-01T09:00:00Z",
        ended_at="2026-01-01T12:00:00Z",
        last_turn_at="2026-01-01T11:00:00Z",
        last_user_prompt="fix the widget",
        last_assistant_text="Fixed and merged. Nothing is pending.",
        recap="Fixed the widget; nothing pending.",
        recap_at="2026-01-01T11:05:00Z",
        turn_count=3,
        model="test-model",
        locators=(Locator("pr", url="https://example.invalid/o/r/pull/1", at="T"),),
    )
    base.update(kw)
    return Session(**base)


def test_render_is_pure_so_regeneration_can_compare_bytes():
    session, verdict = full_session(), Verdict("archive", "because")
    assert render(session, verdict, source="m") == render(session, verdict, source="m")


def test_no_generation_timestamp_leaks_into_the_text():
    """A generation stamp would make every regeneration a diff, hiding real changes."""
    from datetime import datetime

    text = render(full_session(), Verdict("archive", "x"), source="m")
    assert str(datetime.now().year) not in text.replace("2026", "")


def test_every_section_heading_carries_a_date():
    text = render(full_session(), Verdict("open", "x"), source="m")
    for line in text.splitlines():
        if line.startswith("## ") and "Pointers" not in line:
            assert re.search(r"\d{4}-\d{2}-\d{2}|undated|unrecorded", line), line


def test_it_never_says_anything_is_currently_true():
    text = render(full_session(), Verdict("open", "x"), source="m").lower()
    for forbidden in ("still open", "still needs", "is waiting for you", "remains open"):
        assert forbidden not in text


def test_front_matter_declares_it_unverified():
    text = render(full_session(), Verdict("open", "x"), source="m")
    assert "verified: false" in text


def test_a_default_verdict_says_so_in_the_body():
    """ADR-015's rule: a low-confidence reading must display as one."""
    low = render(full_session(), Verdict("open", "x", confidence="low"), source="m")
    high = render(full_session(), Verdict("open", "x"), source="m")
    assert "it is the default" in low
    assert "it is the default" not in high
    assert "confidence: low" in low


def test_the_verdicts_cues_are_shown_so_a_reader_can_disagree():
    text = render(full_session(), Verdict("archive", "why", ("safe to close",)), source="m")
    assert "`safe to close`" in text


def test_a_stale_recap_is_labelled_as_predating_the_last_turn():
    stale = full_session(recap_at="2026-01-01T10:00:00Z")
    fresh = full_session(recap_at="2026-01-01T11:30:00Z")
    assert "before* the closing turn" in render(stale, Verdict("open", "x"), source="m")
    assert "before* the closing turn" not in render(fresh, Verdict("open", "x"), source="m")


def test_sections_are_clipped_deterministically():
    long_text = "x" * (SECTION_LIMITS["last_assistant_text"] + 500)
    text = render(full_session(last_assistant_text=long_text), Verdict("open", "x"), source="m")
    assert "clipped at" in text
    assert len(text) < len(long_text) + 4000


def test_the_resume_pointer_warns_that_it_expires():
    text = render(full_session(), Verdict("open", "x"), source="m")
    assert "claude --resume s1" in text
    assert "only while the transcript survives" in text


def test_absent_fields_produce_no_empty_sections():
    text = render(Session(key="s1"), Verdict("open", "x"), source="m")
    assert "## Its own recap" not in text
    assert "## Context-compaction summary" not in text
    assert "session s1" in text


def test_make_digest_keys_by_source_state_and_session():
    digest = make_digest(full_session(), Verdict("archive", "x"), source="mac")
    assert digest.key == "mac/archive/s1.md"
    assert digest.state == "archive"


def test_make_digest_rewrites_paths_and_raises_on_credentials():
    from pathlib import Path

    home_text = f"I edited {Path.home()}/proj/x.py"
    digest = make_digest(full_session(last_assistant_text=home_text),
                         Verdict("open", "x"), source="m")
    assert "~/proj/x.py" in digest.text
    assert str(Path.home()) not in digest.text

    leaked = "the token is " + "gh" + "p_" + "A" * 36
    with pytest.raises(CredentialFound):
        make_digest(full_session(last_assistant_text=leaked), Verdict("open", "x"), source="m")


def test_a_long_closing_turn_keeps_the_lines_the_verdict_was_read_from():
    """The classifier reads the end; the digest printed only the beginning."""
    from openloops._classify import CLOSING_CHARS, classify

    long_turn = ("filler. " * 900) + "The one thing that still needs you is the review."
    session = full_session(last_assistant_text=long_turn, recap="")
    verdict = classify(session)
    assert verdict.cues == ("needs you",)

    text = render(session, verdict, source="m")
    assert "still needs you is the review" in text, "the deciding cue must be visible"
    assert "clipped at" in text
    assert len(text) < len(long_turn)
    assert CLOSING_CHARS > 0


def test_the_heading_is_dated_to_the_text_the_verdict_read():
    """A recap-decided verdict must not be dated to the closing turn it overrode."""
    session = full_session(
        last_assistant_text="I refactored the parser.",
        last_turn_at="2026-01-01T11:00:00Z",
        recap="All merged; nothing is pending.",
        recap_at="2026-01-01T11:30:00Z",
    )
    from openloops._classify import classify

    verdict = classify(session)
    assert verdict.state == "archive" and verdict.at == "2026-01-01T11:30:00Z"
    assert "Loop state, as read from the turn of 2026-01-01T11:30:00Z" in render(
        session, verdict, source="m"
    )
