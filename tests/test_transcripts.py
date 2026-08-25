import json

from fixtures import (
    ai_title,
    assistant,
    closed_session,
    compact_summary,
    custom_title,
    error_banner,
    pr_link,
    recap,
    stamp,
    tool_use,
    user,
    write_transcripts,
)

from openloops.transcripts import (
    ClaudeCodeTranscripts,
    Revisioned,
    parse_session,
)


def test_parses_the_facts_and_judges_nothing():
    s = parse_session(closed_session())
    assert s.key == "s1"
    assert s.title == "demo"
    assert s.ai_title == "Fix the widget and ship it"
    assert s.project == "demo"
    assert s.git_branches == ("main",)
    assert s.turn_count == 1
    assert s.last_assistant_text == "Fixed and merged. Nothing is pending."
    assert s.last_user_prompt == "fix the widget"
    assert s.ended_mid_turn is False
    assert s.ended_with_error is False


def test_start_and_end_come_from_min_and_max_not_line_order():
    """Transcript lines are not written in timestamp order on real data."""
    records = [
        user("later", at=stamp(1, 12)),
        assistant("reply", at=stamp(1, 13)),
        user("earlier", at=stamp(1, 8)),
    ]
    s = parse_session(records)
    assert s.started_at == stamp(1, 8)
    assert s.ended_at == stamp(1, 13)


def test_last_word_is_the_latest_assistant_text_not_the_last_line():
    records = [
        assistant("the real last word", at=stamp(1, 20)),
        assistant("an earlier one", at=stamp(1, 9)),
    ]
    assert parse_session(records).last_assistant_text == "the real last word"


def test_project_comes_from_the_first_cwd_not_the_last():
    """Four sessions in five wander into scratchpads; the first cwd names the work."""
    records = [
        user("go", at=stamp(1, 9), cwd="/w/realproject"),
        assistant("ok", at=stamp(1, 10), cwd="/tmp/scratchpad"),
    ]
    assert parse_session(records).project == "realproject"


def test_branches_are_a_tuple_and_git_branch_is_the_first():
    records = [
        user("go", at=stamp(1, 9), branch="main"),
        assistant("ok", at=stamp(1, 10), branch="feat/x"),
        assistant("more", at=stamp(1, 11), branch="main"),
    ]
    s = parse_session(records)
    assert s.git_branches == ("main", "feat/x")
    assert s.git_branch == "main"


def test_synthetic_model_is_not_reported_as_the_model():
    records = [
        assistant("a", at=stamp(1, 9), model="real-model"),
        assistant("b", at=stamp(1, 10), model="<synthetic>"),
    ]
    assert parse_session(records).model == "real-model"


def test_the_recap_is_claude_codes_own_and_the_latest_one_wins():
    records = [
        user("go", at=stamp(1, 9)),
        recap("Did the first half.", at=stamp(1, 10)),
        recap("Did the rest. Next: your review. (disable recaps in /config)",
              at=stamp(1, 12)),
        assistant("carrying on", at=stamp(1, 11)),
    ]
    s = parse_session(records)
    assert s.recap == "Did the rest. Next: your review."
    assert s.recap_at == stamp(1, 12)


def test_compaction_summary_is_separate_from_the_recap():
    records = [
        user("go", at=stamp(1, 9)),
        compact_summary("1. What happened", at=stamp(1, 10)),
        assistant("carrying on", at=stamp(1, 11)),
    ]
    s = parse_session(records)
    assert s.compaction == "1. What happened"
    assert s.compaction_at == stamp(1, 10)
    assert s.recap == ""


def test_a_limit_or_error_banner_ending_is_detected_structurally():
    records = [
        user("go", at=stamp(1, 9)),
        error_banner("You've hit your weekly limit", at=stamp(1, 10)),
    ]
    assert parse_session(records).ended_with_error is True
    assert parse_session(closed_session()).ended_with_error is False


def test_ended_mid_turn_covers_an_unanswered_prompt_and_a_dangling_tool_call():
    unanswered = [user("go", at=stamp(1, 9))]
    assert parse_session(unanswered).ended_mid_turn is True

    dangling = [
        user("go", at=stamp(1, 9)),
        assistant(at=stamp(1, 10), blocks=[tool_use("Bash", "t1")]),
    ]
    assert parse_session(dangling).ended_mid_turn is True

    finished = closed_session()
    assert parse_session(finished).ended_mid_turn is False


def test_titles_take_the_last_occurrence():
    records = [
        custom_title("first"),
        custom_title("second"),
        ai_title("a sentence"),
        assistant("done", at=stamp(1, 10)),
    ]
    s = parse_session(records)
    assert (s.title, s.ai_title) == ("second", "a sentence")


def test_locators_deduplicate_and_are_bounded():
    records = [
        *[pr_link(1, "o/r", at=stamp(1, 9)) for _ in range(40)],
        pr_link(2, "o/r", at=stamp(1, 10)),
        assistant("done", at=stamp(1, 11)),
    ]
    locators = parse_session(records).locators
    assert [loc.url for loc in locators] == [
        "https://example.invalid/o/r/pull/1",
        "https://example.invalid/o/r/pull/2",
    ]


def test_wrapper_tags_are_stripped_from_the_human_prompt():
    records = [
        user("<command-name>/effort</command-name> please do X", at=stamp(1, 9)),
        assistant("ok", at=stamp(1, 10)),
    ]
    assert parse_session(records).last_user_prompt == "please do X"


def test_malformed_lines_do_not_break_a_read(projects_dir):
    write_transcripts(projects_dir, {"s1": closed_session()})
    path = projects_dir / "-w-demo" / "s1.jsonl"
    path.write_text(path.read_text() + "not json\n\n")
    src = ClaudeCodeTranscripts()
    assert src["s1"].last_assistant_text.startswith("Fixed")


def test_only_top_level_session_files_are_sessions(projects_dir):
    """Sub-agent transcripts live under a session's own directory and are not sessions."""
    write_transcripts(projects_dir, {"s1": closed_session()})
    nested = projects_dir / "-w-demo" / "s1" / "subagents"
    nested.mkdir(parents=True)
    (nested / "agent-deadbeef.jsonl").write_text(
        json.dumps(assistant("sub-agent output", at=stamp(1, 10))) + "\n"
    )
    assert list(ClaudeCodeTranscripts()) == ["s1"]


def test_scratchpad_project_dirs_are_skipped_by_default(projects_dir):
    write_transcripts(projects_dir, {"s1": closed_session()})
    write_transcripts(projects_dir, {"s9": closed_session("s9")}, project="-private-tmp-x")
    assert list(ClaudeCodeTranscripts()) == ["s1"]
    assert list(ClaudeCodeTranscripts(skip_scratchpads=False)) == ["s1", "s9"]


def test_revision_tracks_mtime_and_missing_dir_is_empty(projects_dir):
    write_transcripts(projects_dir, {"s1": closed_session()})
    src = ClaudeCodeTranscripts()
    token = src.revision("s1")
    assert src.changed_since(token, "s1") is False

    path = src.path_of("s1")
    path.write_text(path.read_text())
    import os

    os.utime(path, (0, 0))
    assert src.changed_since(token, "s1") is True

    assert len(ClaudeCodeTranscripts(root=str(projects_dir / "nope"))) == 0


def test_revisioned_supplies_a_total_default_for_a_plain_mapping():
    """Callers never probe for a revision method; the adapter always has one."""
    from openloops.base import Session

    plain = Revisioned({"a": Session(key="a")})
    assert plain.changed_since(plain.revision("a"), "a") is False
    assert plain.changed_since("something-else", "a") is True

    on_disk = Revisioned(ClaudeCodeTranscripts(root="/nonexistent"))
    assert on_disk.revision() == "0"
