"""Three states again, and a fourth thing that is not a state: a candidate that lied.

Every test here runs with both seams injected, so the suite needs no network, no
credentials and no `gh` — which is also the property the module claims and therefore
the property worth checking. Nothing here shells out, so nothing here assumes a shell:
this file has to pass on Windows too.
"""

from __future__ import annotations

import json

import pytest

from openloops import tools
from openloops.__main__ import main
from openloops.blockers import (
    BLOCKED,
    BLOCKED_FIELDS,
    BLOCKER_STATES,
    UNBLOCKED,
    UNKNOWN,
    Blocker,
    GhUnavailable,
    blocked,
    gh_blocked_by,
    gh_blocked_candidates,
)
from openloops.blockers import _repo_of_blocker, _verdict

NOW_TEXT = "2026-08-27T00:00:00Z"


def now(text: str = NOW_TEXT):
    from datetime import datetime

    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def candidate(
    number: int = 12,
    *,
    repo: str = "acme/widget",
    created: str = "2026-08-01T00:00:00Z",
    title: str = "Drop the workaround once the engine lands",
) -> dict:
    """One row shaped like `gh search issues --json ...` returns it."""
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/issues/{number}",
        "createdAt": created,
        "repository": {"nameWithOwner": repo},
    }


def edge(
    number: int = 15,
    *,
    repo: str = "acme/engine",
    state: str = "closed",
    closed_at: str = "2026-08-20T00:00:00Z",
) -> dict:
    """One row shaped like `gh api .../dependencies/blocked_by` returns it."""
    return {
        "number": number,
        "state": state,
        "closed_at": closed_at if state == "closed" else None,
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "repository": {"full_name": repo},
    }


def report(candidates, edges, **kwargs) -> dict:
    kwargs.setdefault("now", now())
    return blocked(issues_source=candidates, blockers_source=edges, **kwargs)


def only(candidates, edges, **kwargs) -> dict:
    rows = report(candidates, edges, **kwargs)["rows"]
    assert len(rows) == 1
    return rows[0]


# --------------------------------------------------------------------------------
# The three states.
# --------------------------------------------------------------------------------


def test_every_blocker_closed_reads_unblocked():
    row = only([candidate(12)], {"acme/widget#12": [edge(state="closed")]})
    assert row["state"] == UNBLOCKED
    assert row["blockers"][0]["ref"] == "acme/engine#15 [closed]"


def test_one_blocker_still_open_reads_blocked_and_names_the_foreign_repo():
    row = only([candidate(12)], {"acme/widget#12": [edge(state="open")]})
    assert row["state"] == BLOCKED
    assert "acme/engine#15 [open]" in row["evidence"]


def test_a_mix_of_open_and_closed_blockers_is_blocked_not_unblocked():
    """One survivor is enough. Rounding it to `unblocked` sends someone to do work
    that is still impossible, which is the expensive direction to be wrong in."""
    row = only(
        [candidate(12)],
        {"acme/widget#12": [edge(15, state="closed"), edge(16, state="open")]},
    )
    assert row["state"] == BLOCKED
    assert "1 of 2" in row["evidence"]


def test_a_blocker_whose_state_cannot_be_read_is_unknown_never_either_answer():
    row = only([candidate(12)], {"acme/widget#12": [{"number": 15, "state": "wat"}]})
    assert row["state"] == UNKNOWN


def test_a_resolution_that_failed_is_unknown_never_a_clean_board():
    def unreachable(repo, number):
        raise GhUnavailable("gh: not logged in")

    row = only([candidate(12)], unreachable)
    assert row["state"] == UNKNOWN
    assert "not logged in" in row["evidence"]


def test_a_resolver_that_raises_anything_at_all_is_unknown_not_a_crash():
    def broken(repo, number):
        raise RuntimeError("boom")

    row = only([candidate(12)], broken)
    assert row["state"] == UNKNOWN
    assert "boom" in row["evidence"]


def test_unknown_never_collapses_into_a_count_of_nothing_waiting():
    """The failure this module exists to avoid, stated as a test.

    A run that could not resolve anything must not read the same as a run that found
    every loop already harvested.
    """
    def unreachable(repo, number):
        raise GhUnavailable("no network")

    result = report([candidate(12), candidate(13)], unreachable)
    assert result["counts"][UNKNOWN] == 2
    assert result["counts"][UNBLOCKED] == 0
    assert result["counts"][BLOCKED] == 0
    assert result["counts"]["total"] == 2


def test_the_three_states_are_the_only_states():
    result = report(
        [candidate(12), candidate(13), candidate(14)],
        {
            "acme/widget#12": [edge(state="closed")],
            "acme/widget#13": [edge(state="open")],
            "acme/widget#14": [{"number": 9, "state": "?"}],
        },
    )
    assert {row["state"] for row in result["rows"]} == set(BLOCKER_STATES)


# --------------------------------------------------------------------------------
# The candidate that the dependency graph does not agree with.
#
# `is:blocked` over-reports: measured on one real fleet on 2026-08-27 it returned 15
# open issues, 5 of which carried no dependency edge of any kind. A phantom row would
# put a repository on the "waiting" list that is waiting on nothing.
# --------------------------------------------------------------------------------


def test_a_candidate_with_no_edges_is_dropped_rather_than_given_a_state():
    result = report([candidate(12)], {})
    assert result["rows"] == []
    assert result["counts"]["without_edges"] == 1
    assert result["counts"]["candidates"] == 1
    assert result["counts"]["total"] == 0


def test_the_over_report_is_counted_rather_than_hidden():
    """Dropping silently and dropping visibly are different tools. This is the second."""
    result = report(
        [candidate(12), candidate(13)], {"acme/widget#12": [edge(state="closed")]}
    )
    assert result["counts"]["without_edges"] == 1
    assert result["counts"]["candidates"] == 2
    assert result["counts"]["total"] == 1


def test_a_dropped_candidate_is_never_counted_as_unblocked():
    result = report([candidate(12)], {})
    assert result["counts"][UNBLOCKED] == 0


# --------------------------------------------------------------------------------
# What a row carries.
# --------------------------------------------------------------------------------


def test_every_row_carries_every_documented_field():
    row = only([candidate(12)], {"acme/widget#12": [edge()]})
    assert set(row) == set(BLOCKED_FIELDS)


def test_a_cross_repo_blocker_is_marked_as_one():
    row = only([candidate(12)], {"acme/widget#12": [edge(repo="acme/engine")]})
    assert row["cross_repo"] is True


def test_a_same_repo_blocker_is_not_marked_cross_repo():
    """Still a loop, but a visible one: the repo that owns the workaround owns the fix."""
    row = only([candidate(12)], {"acme/widget#12": [edge(repo="acme/widget")]})
    assert row["cross_repo"] is False


def test_an_unblocked_row_says_how_long_it_has_been_free():
    row = only(
        [candidate(12)],
        {"acme/widget#12": [edge(closed_at="2026-08-20T00:00:00Z")]},
    )
    assert row["unblocked_days"] == 7
    assert row["age_days"] == 26


def test_free_time_is_measured_from_the_last_blocker_to_close_not_the_first():
    row = only(
        [candidate(12)],
        {
            "acme/widget#12": [
                edge(15, closed_at="2026-08-01T00:00:00Z"),
                edge(16, closed_at="2026-08-25T00:00:00Z"),
            ]
        },
    )
    assert row["unblocked_days"] == 2


def test_a_blocked_row_claims_no_free_time():
    row = only([candidate(12)], {"acme/widget#12": [edge(state="open")]})
    assert row["unblocked_days"] == 0


def test_age_is_whole_days_from_created_at_and_a_bad_stamp_is_not_a_crash():
    row = only(
        [candidate(12, created="nonsense")], {"acme/widget#12": [edge()]}
    )
    assert row["age_days"] == 0


def test_the_blockers_are_carried_in_full_so_a_reader_can_disagree():
    row = only([candidate(12)], {"acme/widget#12": [edge(15), edge(16, state="open")]})
    assert [b["number"] for b in row["blockers"]] == [15, 16]
    assert [b["state"] for b in row["blockers"]] == ["closed", "open"]


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"repository": {"full_name": "acme/engine"}}, "acme/engine"),
        ({"repository": {"nameWithOwner": "acme/engine"}}, "acme/engine"),
        ({"html_url": "https://github.com/acme/engine/issues/15"}, "acme/engine"),
        ({}, ""),
    ],
)
def test_a_blockers_repository_is_read_from_the_payload_or_from_its_url(
    payload, expected
):
    """Naming the foreign repository is the whole point, so it has a fallback."""
    assert _repo_of_blocker(payload) == expected


# --------------------------------------------------------------------------------
# Ordering: the row that matters is the one nobody is looking for.
# --------------------------------------------------------------------------------


def test_unblocked_sorts_first_then_unknown_then_blocked():
    def edges(repo, number):
        if number == 12:
            return [edge(state="open")]
        if number == 13:
            raise GhUnavailable("no")
        return [edge(state="closed")]

    result = report([candidate(12), candidate(13), candidate(14)], edges)
    assert [row["state"] for row in result["rows"]] == [UNBLOCKED, UNKNOWN, BLOCKED]


def test_the_oldest_unblocked_row_comes_first():
    result = report(
        [
            candidate(12, created="2026-08-20T00:00:00Z"),
            candidate(13, created="2026-01-01T00:00:00Z"),
        ],
        {
            "acme/widget#12": [edge(state="closed")],
            "acme/widget#13": [edge(state="closed")],
        },
    )
    assert [row["number"] for row in result["rows"]] == [13, 12]


def test_a_cross_repo_row_outranks_a_same_repo_row_of_the_same_state():
    result = report(
        [candidate(12), candidate(13)],
        {
            "acme/widget#12": [edge(repo="acme/widget", state="closed")],
            "acme/widget#13": [edge(repo="acme/engine", state="closed")],
        },
    )
    assert [row["number"] for row in result["rows"]] == [13, 12]


# --------------------------------------------------------------------------------
# The envelope: "nothing is waiting" and "I could not find out" are different answers.
# --------------------------------------------------------------------------------


def test_a_failed_discovery_is_reported_as_unknown_never_as_zero():
    def broken(**query):
        raise GhUnavailable("gh: not logged in")

    result = blocked(issues_source=broken)
    assert result["listed"] is False
    assert result["error"] == "gh: not logged in"
    assert result["counts"]["total"] == 0


def test_an_empty_fleet_is_listed_and_empty_which_is_a_real_answer():
    result = report([], {})
    assert result["listed"] is True
    assert result["rows"] == []


def test_resolve_false_resolves_nothing_and_says_so_on_every_row():
    spent = []

    def counted(repo, number):
        spent.append(number)
        return [edge()]

    result = report([candidate(12), candidate(13)], counted, resolve=False)
    assert spent == [], "resolve=False must not spend an API call"
    assert result["resolved"] is False
    assert [row["state"] for row in result["rows"]] == [UNKNOWN, UNKNOWN]
    assert all("resolve=False" in row["evidence"] for row in result["rows"])


def test_a_candidate_list_that_saturates_its_own_cap_says_so():
    result = report([candidate(n) for n in range(10)], {}, limit=3)
    assert result["truncated"] is True
    assert result["counts"]["candidates"] == 3


def test_the_n_plus_one_is_bounded_by_the_limit():
    """Resolution is one API call per candidate, so the cap has to be a real cap."""
    spent = []

    def counted(repo, number):
        spent.append(number)
        return [edge()]

    report([candidate(n) for n in range(50)], counted, limit=4)
    assert len(spent) == 4


def test_a_result_that_fits_is_not_reported_as_truncated():
    result = report([candidate(n) for n in range(3)], {}, limit=3)
    assert result["truncated"] is False


def test_the_envelope_names_what_it_looked_at():
    result = report([candidate(12)], {}, owners=["acme"])
    assert result["owners"] == ["acme"]
    assert result["query"] == "is:blocked"


# --------------------------------------------------------------------------------
# The seams, and what the defaults actually do.
# --------------------------------------------------------------------------------


def test_a_mapping_and_a_callable_are_both_acceptable_blocker_sources():
    from_mapping = only([candidate(12)], {"acme/widget#12": [edge()]})
    from_callable = only([candidate(12)], lambda repo, number: [edge()])
    assert from_mapping == from_callable


def test_an_injected_source_never_asks_gh_for_the_owner_list(monkeypatch):
    monkeypatch.setattr(
        "openloops.blockers._gh",
        lambda args, *, timeout: pytest.fail("gh was called with a source injected"),
    )
    assert report([candidate(12)], {"acme/widget#12": [edge()]})["listed"] is True


def test_naming_repositories_never_asks_gh_for_the_owner_list(monkeypatch):
    monkeypatch.setattr(
        "openloops.blockers._gh",
        lambda args, *, timeout: pytest.fail("gh was called with repos named"),
    )
    result = report([], {}, repos=["acme/widget"])
    assert result["repos"] == ["acme/widget"]


def test_the_fleet_wide_discovery_is_a_filtered_search_never_an_enumeration(monkeypatch):
    seen = {}

    def fake_gh(args, *, timeout):
        seen["args"] = list(args)
        return "[]"

    monkeypatch.setattr("openloops.blockers._gh", fake_gh)
    assert gh_blocked_candidates(owners=("acme", "widgets"), limit=7) == []
    args = seen["args"]
    assert args[:2] == ["search", "issues"]
    assert args.count("--owner") == 2
    assert args[args.index("--limit") + 1] == "7"
    assert args[-2:] == ["--", "is:blocked"]


def test_discovery_refuses_to_search_the_whole_of_github():
    with pytest.raises(GhUnavailable):
        gh_blocked_candidates(owners=())


def test_the_per_repo_path_reads_the_dependency_counts_and_skips_pull_requests(
    monkeypatch,
):
    """The exact enumeration. GitHub already returns the counts on every listed row,
    so one request per repository names every issue with a blocker."""
    listing = [
        {"number": 1, "title": "no deps", "created_at": NOW_TEXT,
         "html_url": "u1", "issue_dependencies_summary": {"total_blocked_by": 0}},
        {"number": 2, "title": "blocked", "created_at": NOW_TEXT,
         "html_url": "u2", "issue_dependencies_summary": {"total_blocked_by": 1}},
        {"number": 3, "title": "a pull request", "created_at": NOW_TEXT,
         "html_url": "u3", "pull_request": {"url": "p"},
         "issue_dependencies_summary": {"total_blocked_by": 1}},
        {"number": 4, "title": "no summary at all", "created_at": NOW_TEXT,
         "html_url": "u4", "issue_dependencies_summary": None},
    ]
    seen = {}

    def fake_gh(args, *, timeout):
        seen["args"] = list(args)
        return json.dumps(listing)

    monkeypatch.setattr("openloops.blockers._gh", fake_gh)
    rows = gh_blocked_candidates(repos=("acme/widget",))
    assert [row["number"] for row in rows] == [2]
    assert rows[0]["repository"] == {"nameWithOwner": "acme/widget"}
    assert seen["args"][0] == "api"
    assert "--paginate" in seen["args"]
    assert "search" not in seen["args"], "the audit path must not touch the search index"


def test_the_per_repo_path_stops_at_the_cap_rather_than_reading_on(monkeypatch):
    listing = [
        {"number": n, "title": "t", "created_at": NOW_TEXT, "html_url": "u",
         "issue_dependencies_summary": {"total_blocked_by": 1}}
        for n in range(10)
    ]
    monkeypatch.setattr(
        "openloops.blockers._gh", lambda args, *, timeout: json.dumps(listing)
    )
    assert len(gh_blocked_candidates(repos=("acme/widget",), limit=3)) == 3


def test_the_default_resolution_asks_for_one_issues_dependencies(monkeypatch):
    seen = {}

    def fake_gh(args, *, timeout):
        seen["args"] = list(args)
        return "[]"

    monkeypatch.setattr("openloops.blockers._gh", fake_gh)
    assert gh_blocked_by("acme/widget", 12) == []
    assert seen["args"][0] == "api"
    assert "repos/acme/widget/issues/12/dependencies/blocked_by" in seen["args"][1]


def test_a_bad_json_payload_is_unknown_rather_than_an_empty_list(monkeypatch):
    monkeypatch.setattr("openloops.blockers._gh", lambda args, *, timeout: "not json")
    with pytest.raises(GhUnavailable):
        gh_blocked_candidates(owners=("acme",))
    with pytest.raises(GhUnavailable):
        gh_blocked_by("acme/widget", 12)


def test_a_payload_that_is_not_a_list_is_unknown_rather_than_believed(monkeypatch):
    monkeypatch.setattr(
        "openloops.blockers._gh", lambda args, *, timeout: '{"message": "Not Found"}'
    )
    with pytest.raises(GhUnavailable):
        gh_blocked_by("acme/widget", 12)


def test_with_no_gh_on_the_machine_the_default_path_answers_a_question_mark(monkeypatch):
    """The whole path on its defaults, on a machine with nothing installed."""
    monkeypatch.setattr("openloops.obligations.shutil.which", lambda name: None)
    result = blocked()
    assert result["listed"] is False
    assert "gh" in result["error"]
    assert result["counts"]["total"] == 0


# --------------------------------------------------------------------------------
# The verdict rule, on its own.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blockers, expected",
    [
        ([Blocker("a/b", 1, "closed")], UNBLOCKED),
        ([Blocker("a/b", 1, "open")], BLOCKED),
        ([Blocker("a/b", 1, "closed"), Blocker("a/c", 2, "open")], BLOCKED),
        ([Blocker("a/b", 1, "")], UNKNOWN),
        ([Blocker("a/b", 1, "closed"), Blocker("a/c", 2, "")], UNKNOWN),
        ([], UNKNOWN),
    ],
)
def test_the_verdict_rule(blockers, expected):
    assert _verdict(blockers)[0] == expected


def test_an_unreadable_blocker_poisons_the_row_rather_than_being_ignored():
    """Ignoring the one edge that could not be read would report a confident verdict
    over a partial graph, which is the same defect as a count that cannot say `?`."""
    state, evidence = _verdict([Blocker("a/b", 1, "closed"), Blocker("a/c", 2, "")])
    assert state == UNKNOWN
    assert "a/c#2" in evidence


# --------------------------------------------------------------------------------
# The surface.
# --------------------------------------------------------------------------------


def canned(**kwargs) -> dict:
    base = {
        "listed": True,
        "resolved": True,
        "error": "",
        "truncated": False,
        "query": "is:blocked",
        "owners": ["acme"],
        "repos": [],
        "counts": {
            UNBLOCKED: 1,
            BLOCKED: 1,
            UNKNOWN: 1,
            "cross_repo": 3,
            "candidates": 4,
            "without_edges": 1,
            "total": 3,
        },
        "rows": [
            {
                "repo": "acme/widget", "number": 1, "title": "free now",
                "url": "u", "created": "", "age_days": 30, "state": UNBLOCKED,
                "blockers": [{"repo": "acme/engine", "number": 15, "state": "closed",
                              "url": "", "closed_at": "", "ref": "acme/engine#15 [closed]"}],
                "cross_repo": True, "unblocked_days": 12, "evidence": "every blocker is closed",
            },
            {
                "repo": "acme/widget", "number": 2, "title": "still waiting",
                "url": "u", "created": "", "age_days": 20, "state": BLOCKED,
                "blockers": [{"repo": "acme/parser", "number": 7, "state": "open",
                              "url": "", "closed_at": "", "ref": "acme/parser#7 [open]"}],
                "cross_repo": True, "unblocked_days": 0, "evidence": "1 of 1 blockers still open",
            },
            {
                "repo": "acme/widget", "number": 3, "title": "could not tell",
                "url": "u", "created": "", "age_days": 10, "state": UNKNOWN,
                "blockers": [], "cross_repo": False, "unblocked_days": 0,
                "evidence": "the blocker edges could not be read: no network",
            },
        ],
    }
    return {**base, **kwargs}


def test_the_cli_shows_all_three_states_and_every_edge(monkeypatch, capsys):
    monkeypatch.setattr(tools, "blocked", lambda **kwargs: canned())
    main(["blocked"])
    out = capsys.readouterr().out
    assert "1 unblocked, 1 blocked, 1 unknown" in out
    assert "acme/engine#15 [closed]" in out, "a verdict without its edge"
    assert "acme/parser#7 [open]" in out, "a blocked row must name what it waits on"
    assert "ready" in out and "waits" in out and "?" in out


def test_the_cli_prints_how_long_an_unblocked_row_has_been_free(monkeypatch, capsys):
    monkeypatch.setattr(tools, "blocked", lambda **kwargs: canned())
    main(["blocked"])
    assert "free for 12d" in capsys.readouterr().out


def test_the_cli_prints_how_many_candidates_had_no_edge(monkeypatch, capsys):
    """Search over-reports; a surface that hides by how much is trusting an index."""
    monkeypatch.setattr(tools, "blocked", lambda **kwargs: canned())
    main(["blocked"])
    assert "1 had no dependency edge" in capsys.readouterr().out


def test_the_cli_says_question_mark_when_it_could_not_check(monkeypatch, capsys):
    monkeypatch.setattr(
        tools,
        "blocked",
        lambda **kwargs: canned(listed=False, error="gh: not logged in"),
    )
    main(["blocked"])
    out = capsys.readouterr().out
    assert out.startswith("blocked ?")
    assert "0 unblocked" not in out, "a surface that cannot check must print no count"


def test_the_cli_passes_no_resolve_through(monkeypatch, capsys):
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return canned(resolved=False)

    monkeypatch.setattr(tools, "blocked", spy)
    main(["blocked", "--no-resolve"])
    assert seen["resolve"] is False
    assert "NOT resolved" in capsys.readouterr().out


def test_the_cli_passes_named_repositories_through(monkeypatch):
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return canned()

    monkeypatch.setattr(tools, "blocked", spy)
    main(["blocked", "--repos", "acme/widget,acme/engine"])
    assert seen["repos"] == ["acme/widget", "acme/engine"]


def test_the_cli_prints_ascii_only(monkeypatch, capsys):
    """This renders on a Windows console; a UnicodeEncodeError is not an answer."""
    monkeypatch.setattr(tools, "blocked", lambda **kwargs: canned(truncated=True))
    main(["blocked"])
    capsys.readouterr().out.encode("ascii")


def test_nothing_waiting_is_a_sentence_not_an_empty_screen(monkeypatch, capsys):
    monkeypatch.setattr(
        tools,
        "blocked",
        lambda **kwargs: canned(
            rows=[],
            counts={
                UNBLOCKED: 0, BLOCKED: 0, UNKNOWN: 0, "cross_repo": 0,
                "candidates": 0, "without_edges": 0, "total": 0,
            },
        ),
    )
    main(["blocked"])
    assert "(nothing is waiting on another repo)" in capsys.readouterr().out


def test_the_tool_returns_something_json_serialisable():
    json.dumps(
        tools.blocked(
            issues_source=[candidate(12)],
            blockers_source={"acme/widget#12": [edge()]},
        )
    )


def test_the_tool_and_the_module_are_the_same_operation():
    """One dispatch list, one implementation. A parity test between two surfaces would
    mean there were two implementations; this checks there is one."""
    from openloops.tools import _dispatch_funcs

    assert tools.blocked in _dispatch_funcs
    same = tools.blocked(issues_source=[], blockers_source={})
    assert same == blocked(issues_source=[], blockers_source={})


def test_the_package_re_exports_it_the_way_it_re_exports_owed():
    import openloops

    assert openloops.blocked is blocked
    for name in ("BLOCKED", "UNBLOCKED", "BLOCKER_STATES", "BLOCKED_FIELDS"):
        assert name in openloops.__all__


def test_github_claiming_blockers_and_listing_none_is_unknown_not_a_clean_board():
    """The audit path selects a row BECAUSE GitHub said it has blockers.

    So an empty edge listing there is a contradiction, not an absence -- most likely a
    blocker in a repository this token cannot read. Dropping it would print "nothing is
    waiting" over an issue known to be waiting, which is the one failure this module
    exists to prevent.
    """
    candidates = [
        {
            "_expected_blockers": 1,
            "number": 7,
            "title": "Waits on something I cannot see",
            "url": "https://github.com/acme/widget/issues/7",
            "createdAt": "2026-08-01T00:00:00Z",
            "repository": {"nameWithOwner": "acme/widget"},
        }
    ]
    result = report(candidates, lambda repo, number: [])
    assert result["counts"]["unknown"] == 1
    assert result["counts"]["without_edges"] == 0, (
        "a contradiction is not the same as having no edges"
    )
    row = result["rows"][0]
    assert row["state"] == UNKNOWN
    assert "cannot read" in row["evidence"]


def test_a_search_only_candidate_with_no_edges_is_still_merely_counted():
    """Without GitHub's own count claiming otherwise, an edgeless row is not a state.

    The fleet search over-reports -- measured 15 candidates against 10 real edges on
    2026-08-27 -- so those five are counted and printed, not turned into `?` noise.
    """
    candidates = [
        {
            "number": 7,
            "title": "Search thinks this is blocked; the graph disagrees",
            "url": "https://github.com/acme/widget/issues/7",
            "createdAt": "2026-08-01T00:00:00Z",
            "repository": {"nameWithOwner": "acme/widget"},
        }
    ]
    result = report(candidates, lambda repo, number: [])
    assert result["counts"]["without_edges"] == 1
    assert result["counts"]["unknown"] == 0
    assert result["rows"] == []
