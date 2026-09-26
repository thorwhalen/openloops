"""Exchanges: each prompt paired with its turn's reply, and the questions a person asked.

Synthetic transcripts only (see ``fixtures``)."""

from __future__ import annotations

import pytest

from openloops.exchanges import (
    HUMAN,
    MAX_QUESTIONS,
    PEER,
    SYSTEM,
    exchanges,
    load_records,
    question_sentences,
)
from fixtures import assistant, compact_summary, stamp, tool_result, tool_use, user


def test_each_prompt_is_paired_with_the_last_words_of_its_turn():
    recs = [
        user("Fix the build. Why is CI slow?", at=stamp(1, 1), uuid="u1"),
        assistant("Looking.", at=stamp(1, 2), blocks=[tool_use("Bash", "t1")]),
        tool_result("t1", at=stamp(1, 3)),
        assistant("Fixed. CI is slow because the cache was cold.", at=stamp(1, 4)),
        user("Thanks, merge it.", at=stamp(1, 5), uuid="u2"),
    ]
    first, second = exchanges(recs)
    assert (first.uuid, first.origin) == ("u1", HUMAN)
    assert first.questions == ("Why is CI slow?",)
    assert first.reply == "Fixed. CI is slow because the cache was cold."
    assert first.replied_at == stamp(1, 4)
    assert (second.uuid, second.reply, second.questions) == ("u2", "", ())


def test_records_out_of_order_are_read_in_time_order():
    recs = [
        assistant("the answer", at=stamp(1, 2)),
        user("What is the answer?", at=stamp(1, 1), uuid="u1"),
    ]
    assert exchanges(recs)[0].reply == "the answer"


def test_a_notification_ends_the_turn_and_asks_nothing():
    recs = [
        user("Is the deploy done?", at=stamp(1, 1), uuid="u1"),
        assistant("Not yet; watching it.", at=stamp(1, 2)),
        user(
            "<task-notification>done</task-notification>",
            at=stamp(1, 3),
            uuid="u2",
            origin={"kind": "task-notification"},
        ),
        assistant("The deploy finished.", at=stamp(1, 4)),
    ]
    asked, woke = exchanges(recs)
    assert asked.reply == "Not yet; watching it."
    assert (woke.origin, woke.questions, woke.reply) == (SYSTEM, (), "The deploy finished.")


def test_a_headless_run_is_not_a_person_asking():
    recs = [user("What is 2+2?", at=stamp(1, 1), promptSource="sdk")]
    assert exchanges(recs)[0].origin == SYSTEM
    assert exchanges(recs)[0].questions == ()


def test_a_peer_message_is_named_and_never_mined_for_questions():
    text = '<cross-session-message from-name="cn">Is the page live?</cross-session-message>'
    (got,) = exchanges([user(text, at=stamp(1, 1))])
    assert (got.origin, got.sender, got.prompt, got.questions) == (
        PEER,
        "cn",
        "Is the page live?",
        (),
    )


def test_sidechains_meta_and_compaction_do_not_start_turns():
    recs = [
        user("Why is it red?", at=stamp(1, 1), uuid="u1"),
        user("sub-agent brief", at=stamp(1, 2), isSidechain=True),
        user("injected skill text", at=stamp(1, 3), isMeta=True),
        compact_summary("earlier", at=stamp(1, 4)),
        assistant("Because the test is flaky.", at=stamp(1, 5)),
    ]
    (only,) = exchanges(recs)
    assert only.reply == "Because the test is flaky."


def test_records_load_from_a_file(tmp_path):
    import json

    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps(user("Why?? no, why is it slow?", at=stamp(1, 1))) + "\nnot json\n\n"
    )
    assert len(load_records(path)) == 1


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Why does CI take ten minutes? Then merge it.", ("Why does CI take ten minutes?",)),
        ("why does the page load twice", ("why does the page load twice",)),
        ("Can you add a test?", ()),  # a request phrased as a question
        ("Could you explain why it failed?", ("Could you explain why it failed?",)),
        ("ok? right?", ()),  # tags
        ("> Why is it slow?", ()),  # quoted
        ("```\nwhy is it slow?\n```", ()),  # code
        ("WHERE TO LOOK FIRST", ()),  # a heading
        ("Where to look, in order:", ()),  # a lead-in
        ("When you're done, upload them.", ()),  # a clause, not a question
        ("- Is the cache warm?\n- Is the queue empty?", ("Is the cache warm?", "Is the queue empty?")),
    ],
)
def test_question_sentences(text, found):
    assert question_sentences(text) == found


def test_a_prompt_yields_at_most_a_handful_of_questions():
    text = " ".join(f"Is item {i} done?" for i in range(20))
    assert len(question_sentences(text)) == MAX_QUESTIONS
