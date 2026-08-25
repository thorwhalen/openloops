"""The closed-detector. Cases are paraphrases of real closing turns, never copies."""

import pytest

from openloops.base import ARCHIVE, OPEN, Session
from openloops._classify import (
    asks_the_human,
    classify,
    ends_with_a_question,
    latest_cue,
    ASK_CUES,
    CLOSE_CUES,
    DEFER_CUES,
)


def sess(text="", **kw):
    return Session(key="s", last_assistant_text=text, **kw)


@pytest.mark.parametrize(
    "text",
    [
        "I fixed the parser. Do you want me to land it?",
        "Two options here. **Which would you prefer?**",
        "It builds now. Shall I open the PR?",
        "Everything is staged — say the word and I'll push.",
        "I've done the rest, but I'm blocked on your deploy key.",
        "That is the last of them; the remaining thread is still open.",
    ],
)
def test_an_unfinished_closing_reads_as_open(text):
    assert classify(sess(text)).state == OPEN


@pytest.mark.parametrize(
    "text",
    [
        "Fixed and merged. Nothing is pending.",
        "0.2.8 is published; nothing further from me.",
        "Deployed and verified. Safe to close.",
        "The scratch dir is session-temp — nothing to clean up before exiting.",
    ],
)
def test_a_positive_close_out_reads_as_archive(text):
    assert classify(sess(text)).state == ARCHIVE


def test_open_is_the_default_and_says_that_it_is():
    """Absence of evidence that a session finished is not evidence that it did."""
    verdict = classify(sess("I refactored the parser and updated the tests."))
    assert verdict.state == OPEN
    assert verdict.confidence == "low"
    assert "does not assume" in verdict.reason


def test_finishing_words_alone_are_not_a_close_out():
    """`merged`, `published` and `done` appear in every second sentence agents write."""
    assert classify(sess("Fixed and merged. All tests pass.")).state == OPEN
    assert classify(sess("0.2.8 is on PyPI and CI is green.")).state == OPEN


def test_the_latest_cue_wins_not_a_fixed_precedence():
    """Real closing paragraphs carry both kinds of cue; order in the text decides."""
    closed = "…or say the word and I'll remove it. Nothing is blocking; safe to close."
    still_open = "You're all set to exit. The two threads waiting for you are #1 and #2."
    assert classify(sess(closed)).state == ARCHIVE
    assert classify(sess(still_open)).state == OPEN


def test_a_question_far_from_the_end_does_not_decide_it():
    text = "Do you want the long version? Here it is.\n\n" + ("detail. " * 300) + \
        "Nothing is pending."
    assert classify(sess(text)).state == ARCHIVE


def test_structural_signals_come_first():
    assert classify(sess("Nothing is pending.", ended_mid_turn=True)).state == OPEN
    assert classify(sess("Nothing is pending.", ended_with_error=True)).state == OPEN


@pytest.mark.parametrize(
    "banner",
    [
        "API Error: Unable to connect to API (ConnectionRefused)",
        "You've hit your weekly limit · resets 1am",
        "You've reached your session limit",
    ],
)
def test_a_limit_or_error_banner_is_a_cut_off_session(banner):
    verdict = classify(sess(banner))
    assert verdict.state == OPEN
    assert "cut off" in verdict.reason


def test_no_closing_text_is_open_at_low_confidence():
    verdict = classify(sess(""))
    assert (verdict.state, verdict.confidence) == (OPEN, "low")


def test_every_verdict_shows_its_grounds():
    for session in (
        sess("Do you want me to land it?"),
        sess("Blocked on your review."),
        sess("Nothing is pending."),
        sess(""),
        sess("x", ended_with_error=True),
    ):
        verdict = classify(session)
        assert verdict.reason
        assert verdict.confidence in ("high", "low")


def test_ends_with_a_question_ignores_trailing_markup():
    assert ends_with_a_question("done.\n\n**Land it?**") is True
    assert ends_with_a_question("done.\n\n(Should we? Probably.)") is False
    assert ends_with_a_question("") is False


def test_the_last_cue_bearing_sentence_decides():
    families = {"ask": ASK_CUES, "defer": DEFER_CUES, "close": CLOSE_CUES}
    assert latest_cue("Say the word. Nothing is pending.", families)[0] == "close"
    assert latest_cue("Nothing is pending. Say the word.", families)[0] == "ask"
    assert latest_cue("clean text", {"defer": DEFER_CUES}) is None


def test_within_one_sentence_an_open_cue_beats_a_close_cue():
    """A real close-out put its close cue inside a parenthetical of a handback."""
    families = {"defer": DEFER_CUES, "close": CLOSE_CUES}
    one_sentence = "Needs you (nothing blocking, all tracked): the #146 decision."
    assert latest_cue(one_sentence, families) == ("defer", "needs you")
    assert classify(sess(one_sentence)).state == OPEN


def test_asks_the_human_is_the_shared_primitive():
    """A retrospective measurement and the classifier use one definition, not two."""
    assert asks_the_human("I fixed it. Want me to open the PR?") == ("want me to",)
    assert asks_the_human("It is all merged and closed.") == ()
    assert asks_the_human("") == ()


def test_cue_lists_are_overridable_without_touching_the_rules():
    verdict = classify(sess("It is done. Sound good."), ask_cues=("sound good",))
    assert verdict.state == OPEN and verdict.cues == ("sound good",)


def test_a_close_out_followed_by_an_ask_is_still_open():
    """The regression that a real session produced, and the one that matters most.

    "Nothing further is running. The one thing that still needs you is #55" declares
    completeness and then immediately names something outstanding. The close cue is
    earlier, so latest-cue-wins is what saves it — but only if the defer vocabulary is
    wide enough to see the second half at all.
    """
    text = (
        "Everything in the close-out was independently re-derived and holds. "
        "Nothing further is running. The one thing that still needs you is #55 — "
        "chiefly the billing lapse."
    )
    verdict = classify(sess(text))
    assert verdict.state == OPEN
    assert verdict.cues == ("needs you",)


def test_the_recap_decides_only_when_the_closing_turn_is_mute():
    """Rule six: read the session's own recap, last, and only when it is fresh."""
    mute = "I refactored the parser and updated the tests."
    assert classify(sess(mute)).confidence == "low"

    decided = classify(
        sess(mute, last_turn_at="T1", recap="All merged; nothing is pending.", recap_at="T2")
    )
    assert decided.state == ARCHIVE
    assert "its own recap" in decided.reason
    assert decided.confidence == "high"


def test_a_recap_that_predates_the_closing_turn_is_ignored():
    """A stale `nothing pending` is exactly the false archive this design refuses."""
    verdict = classify(
        sess(
            "I refactored the parser.",
            last_turn_at="T3",
            recap="All merged; nothing is pending.",
            recap_at="T2",
        )
    )
    assert (verdict.state, verdict.confidence) == (OPEN, "low")


def test_the_recap_never_overrides_a_decided_closing_turn():
    verdict = classify(
        sess(
            "I've done the rest, but I'm blocked on your deploy key.",
            last_turn_at="T1",
            recap="All merged; nothing is pending.",
            recap_at="T9",
        )
    )
    assert verdict.state == OPEN
    assert "closing lines" in verdict.reason
