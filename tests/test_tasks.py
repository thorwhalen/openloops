"""Gather, classify, merge: the board's read side, against a fake `gh` and synthetic items.

Every item here is invented. No test reaches GitHub: the gatherer takes ``run_gh=``.
"""

from __future__ import annotations

import json

import pytest

from openloops import tasks
from openloops.obligations import GhUnavailable


def _row(
    repo, number, title="t", *, body="", kind="issues", created="2026-08-01T00:00:00Z"
):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/{kind}/{number}",
        "repository": {"nameWithOwner": repo},
        "createdAt": created,
        "labels": [{"name": "manual-task"}],
        "body": body,
    }


class FakeGh:
    """Answers each query from a table keyed by (owner, kind of query); records the calls."""

    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, args, *, timeout):
        self.calls.append(args)
        owner = args[args.index("--owner") + 1]
        if "prs" in args:
            key = "prs"
        elif "--label" in args:
            label = args[args.index("--label") + 1]
            key = "label" if label == "manual-task" else label
        else:
            key = args[-1]
        result = self.table.get((owner, key), [])
        if isinstance(result, Exception):
            raise result
        return json.dumps(result)


def test_agent_decided_issues_are_gathered_by_label_and_become_a_keep_or_veto_card():
    """ADR-010: an agent's recorded decision is a one-tap card, not a free-text question."""
    decided = _row("acme/w", 9, "Decided: use the shorter retry window")
    decided["labels"] = [{"name": "agent-decided"}]
    gh = FakeGh({("acme", "agent-decided"): [decided]})
    report = tasks.gather(owners=["acme"], searches=["agent-decided"], run_gh=gh)
    assert [c["id"] for c in report["candidates"]] == ["acme/w#9"]
    assert report["candidates"][0]["src"] == "agent-decided"
    query = next(a for a in gh.calls if "agent-decided" in a)
    assert query[query.index("--label") + 1] == "agent-decided"
    assert "--match" not in query, "a label is not a text search"

    record = tasks.heuristic_classify(report["candidates"][0])
    assert (record["tier"], record["pattern"]) == ("tap", "decision")
    assert record["decision"]["options"] == ["Keep", "Veto"]
    assert record["decision"]["recommendation"] == "Keep"


def test_an_agent_decided_issue_is_keep_or_veto_whichever_query_found_it_first():
    """Deduplication keeps the first query that returned an issue (here: `decide`)."""
    row = _row("acme/w", 9, "Decided: use the shorter retry window")
    row["labels"] = [{"name": "agent-decided"}]
    gh = FakeGh({("acme", "Decide"): [row], ("acme", "agent-decided"): [row]})
    report = tasks.gather(
        owners=["acme"], searches=["decide", "agent-decided"], run_gh=gh
    )
    (candidate,) = report["candidates"]
    assert candidate["src"] == "decide"
    assert tasks.heuristic_classify(candidate)["decision"]["options"] == [
        "Keep",
        "Veto",
    ]


def test_the_agent_decided_label_is_matched_case_insensitively():
    candidate = {
        "url": "https://github.com/acme/w/issues/5",
        "repo": "acme/w",
        "title": "Decided: x",
        "body": "",
        "labels": ["Agent-Decided"],
    }
    assert tasks.heuristic_classify(candidate)["decision"]["options"] == [
        "Keep",
        "Veto",
    ]


def test_a_decided_title_without_the_label_is_not_a_keep_or_veto_card():
    plain = {
        "url": "https://github.com/acme/w/issues/4",
        "repo": "acme/w",
        "title": "Decided: nothing yet",
        "body": "",
        "src": "label",
        "labels": ["manual-task"],
    }
    assert tasks.heuristic_classify(plain)["decision"] is None


def test_gather_queries_each_owner_separately_and_deduplicates_by_url():
    shared = _row("acme/w", 1, "Decide the name")
    gh = FakeGh(
        {
            ("acme", "label"): [shared, _row("acme/w", 2)],
            ("acme", "Decide"): [shared],
            ("beta", "label"): [_row("beta/x", 3)],
        }
    )
    report = tasks.gather(owners=["acme", "beta"], searches=["decide"], run_gh=gh)
    assert report["listed"] and report["owners"] == ["acme", "beta"]
    assert sorted(c["id"] for c in report["candidates"]) == [
        "acme/w#1",
        "acme/w#2",
        "beta/x#3",
    ]
    # One query per owner per kind: no owner's results can crowd out another's.
    assert len(gh.calls) == 4  # (label + decide) x (acme, beta)
    assert all(
        "--limit" in call and call[call.index("--limit") + 1] == "1000"
        for call in gh.calls
    )


def test_a_query_that_reaches_the_limit_is_reported_saturated():
    gh = FakeGh({("acme", "label"): [_row("acme/w", n) for n in range(5)]})
    report = tasks.gather(owners=["acme"], limit=5, run_gh=gh)
    assert report["saturated"] == ["acme label:manual-task"]


def test_one_failed_query_makes_the_whole_sweep_unlisted_not_quietly_partial():
    gh = FakeGh(
        {
            ("acme", "label"): [_row("acme/w", 1)],
            ("beta", "label"): GhUnavailable("rate limited"),
        }
    )
    report = tasks.gather(owners=["acme", "beta"], run_gh=gh)
    assert report["listed"] is False and "beta" in report["error"]
    assert [c["id"] for c in report["candidates"]] == ["acme/w#1"]


def test_exclusions_drop_owners_and_repo_globs(monkeypatch):
    gh = FakeGh(
        {
            ("acme", "label"): [_row("acme/keep", 1), _row("acme/secret-a", 2)],
            ("beta", "label"): [_row("beta/x", 3)],
        }
    )
    report = tasks.gather(
        owners=["acme", "beta"],
        exclude_owners=["beta"],
        exclude_repos=["acme/secret-*"],
        run_gh=gh,
    )
    assert [c["id"] for c in report["candidates"]] == ["acme/keep#1"]
    assert not any("beta" in call for call in gh.calls), (
        "an excluded owner is never queried"
    )

    monkeypatch.setenv(tasks.EXCLUDE_ENV_VAR, "acme/keep")
    gh2 = FakeGh({("acme", "label"): [_row("acme/keep", 1), _row("acme/other", 4)]})
    assert [
        c["id"] for c in tasks.gather(owners=["acme"], run_gh=gh2)["candidates"]
    ] == ["acme/other#4"]


def test_review_prs_adds_a_pr_query_and_unknown_searches_are_refused():
    gh = FakeGh({("acme", "prs"): [_row("acme/w", 9, "Add a feature", kind="pull")]})
    report = tasks.gather(owners=["acme"], review_prs=True, run_gh=gh)
    assert report["candidates"][0]["kind"] == "pr"
    assert any("--review-requested" in call for call in gh.calls)
    with pytest.raises(ValueError, match="unknown search"):
        tasks.gather(owners=["acme"], searches=["nope"], run_gh=gh)


def test_owners_default_to_the_configured_ones(monkeypatch):
    monkeypatch.setenv("OPENLOOPS_OWNERS", "acme")
    gh = FakeGh({("acme", "label"): [_row("acme/w", 1)]})
    assert tasks.gather(run_gh=gh)["owners"] == ["acme"]


# --------------------------------------------------------------------------------
# The heuristic classifier.


def _cand(title, body="", *, repo="acme/widget", number=1, kind="issues"):
    return tasks._candidate(
        _row(repo, number, title, body=body, kind=kind), src="label"
    )


@pytest.mark.parametrize(
    "title, body, pattern, tier",
    [
        (
            "Decision: drop the legacy flag?",
            "Mentions a server deploy.",
            "decision",
            "tap",
        ),
        (
            "Configure npm trusted publishing",
            "https://www.npmjs.com/package/@acme/widget",
            "npm-trusted-publisher",
            "browser",
        ),
        ("Add a PyPI trusted publisher", "", "pypi-trusted-publisher", "browser"),
        ("Set the DEPLOY_TOKEN secret", "", "github-settings", "browser"),
        ("Create an API key on the speech service", "", "api-key", "browser"),
        ("Record a voice sample for the demo", "", "record", "physical"),
        ("Install the new reaper on the server", "", "server-chore", "session"),
        ("Sign the app in Xcode", "", "mac-only", "mac-only"),
        ("Something nobody wrote a rule for", "", "other", "browser"),
    ],
)
def test_the_heuristic_picks_pattern_and_tier_from_the_words(
    title, body, pattern, tier
):
    record = tasks.heuristic_classify(_cand(title, body))
    assert (record["pattern"], record["tier"]) == (pattern, tier)
    assert set(record) == set(tasks.TASK_FIELDS)
    assert record["links"][-1] == {
        "label": "Issue",
        "url": "https://github.com/acme/widget/issues/1",
    }


def test_deep_links_point_at_the_exact_page():
    npm = tasks.heuristic_classify(
        _cand("npm trusted publisher", "see https://www.npmjs.com/package/@acme/widget")
    )
    assert npm["links"][0]["url"] == "https://www.npmjs.com/package/@acme/widget/access"
    assert npm["pattern_key"] == "@acme/widget"
    pages = tasks.heuristic_classify(_cand("Turn on GitHub Pages"))
    assert pages["links"][0]["url"] == "https://github.com/acme/widget/settings/pages"
    pr = tasks.heuristic_classify(_cand("Bump x from 1 to 2", kind="pull"))
    assert pr["pattern"] == "merge-bot-pr" and pr["links"][0]["url"].endswith(
        "/pull/1/files"
    )


def test_a_decision_carries_the_recommendation_its_body_states_and_never_invents_one():
    with_rec = tasks.heuristic_classify(
        _cand("Decide the format", "**Recommendation:** B, smaller")
    )
    assert with_rec["decision"] == {
        "question": "Decide the format",
        "options": [],
        "recommendation": "B, smaller",
    }
    without = tasks.heuristic_classify(_cand("Decide the format"))
    assert without["decision"]["recommendation"] is None


def test_session_items_get_a_prompt_and_the_owner_machine():
    record = tasks.heuristic_classify(
        _cand("Deploy the fix"), machines={"acme": "box1"}
    )
    assert record["tier"] == "session" and record["machine"] == "box1"
    assert "https://github.com/acme/widget/issues/1" in record["prompt"]
    assert tasks.heuristic_classify(_cand("Decide it"))["prompt"] is None


# --------------------------------------------------------------------------------
# The schema and merging.


def test_a_record_outside_the_vocabulary_is_normalised_not_rejected():
    task = tasks.Task.from_mapping(
        {
            "url": "https://github.com/a/b/pull/4",
            "tier": "x",
            "status": "?",
            "kind": "?",
            "junk": 1,
        }
    )
    assert (task.id, task.tier, task.status, task.kind) == (
        "a/b#4",
        "session",
        "open",
        "pr",
    )
    assert "junk" not in task.as_dict()


def test_merge_lets_the_brief_win_and_keeps_the_gathered_date(tmp_path):
    heuristic = tasks.classify([_cand("Decide the name")])
    enriched = [
        {
            "id": "acme/widget#1",
            "url": "https://github.com/acme/widget/issues/1",
            "tier": "tap",
            "ask": "Pick B",
            "status": "likely-done",
        }
    ]
    (tmp_path / "out_00.json").write_text(json.dumps(enriched))
    merged = tasks.merge_records(
        heuristic, tasks.load_records([str(tmp_path / "out_*.json")])
    )
    assert len(merged) == 1
    assert (merged[0]["ask"], merged[0]["status"], merged[0]["created"]) == (
        "Pick B",
        "likely-done",
        "2026-08-01",
    )


def test_load_records_reads_a_gather_envelope(tmp_path):
    path = tmp_path / "cands.json"
    path.write_text(json.dumps({"listed": True, "candidates": [{"url": "u"}]}))
    assert tasks.load_records([path]) == [{"url": "u"}]


def test_exclusions_and_owners_compare_case_insensitively():
    gh = FakeGh({("Acme", "label"): [_row("Acme/w", 1), _row("Acme/keep", 2)]})
    report = tasks.gather(owners=["Acme", "acme"], exclude_repos=["acme/w"], run_gh=gh)
    assert [c["id"] for c in report["candidates"]] == ["Acme/keep#2"]
    assert len(gh.calls) == 1, "one owner in two spellings is queried once"


def test_an_enriched_record_without_a_url_still_merges_with_its_heuristic_twin():
    heuristic = tasks.classify([_cand("Decide the name")])
    merged = tasks.merge_records(heuristic, [{"id": "acme/widget#1", "ask": "Pick B"}])
    assert len(merged) == 1 and merged[0]["ask"] == "Pick B"
    assert tasks.merge_records([{"title": "no id, no url"}]) == []
    assert tasks.Task.from_mapping({"id": "a/b#1", "title": None}).title == ""


def test_a_batch_glob_that_matches_nothing_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        tasks.load_records([str(tmp_path / "out_*.json")])


def test_an_agent_decided_card_shows_what_a_veto_would_run():
    """The owner never vetoes blind: the Reverse and Veto-by lines are on the card."""
    candidate = {
        "url": "https://github.com/acme/w/issues/5",
        "repo": "acme/w",
        "title": "Decided: x",
        "body": "**Decided:** x\n\n**Reverse:** `git revert abc1234`\n\n**Veto by:** 2026-11-08.",
        "labels": ["agent-decided"],
    }
    note = tasks.heuristic_classify(candidate)["note"]
    assert "Reverse: `git revert abc1234`" in note and "Veto by: 2026-11-08" in note
    candidate["body"] = "**Decided:** x"
    assert "a Veto reverts nothing" in tasks.heuristic_classify(candidate)["note"]
    # A long body is cut before classification: a missing line there is unknown, not absent.
    candidate["body"] = "**Decided:** x\n" + "y" * tasks.DFLT_BODY_CHARS
    assert "not seen" in tasks.heuristic_classify(candidate)["note"]


def test_all_kinds_on_the_cli_gathers_agent_decided_issues(monkeypatch):
    from openloops import __main__ as cli

    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"counts": {"total": 0}, "owners": [], "saturated": [], "listed": True}

    monkeypatch.setattr(cli.tools, "board_gather", fake)
    cli.board_gather(all_kinds=True)
    assert tasks.AGENT_DECIDED_LABEL in seen["searches"]
    assert seen["review_prs"] is True


def test_review_garbage_normalises_to_none():
    for bad in ("nope", 3, ["x"], {}, {"junk": 1}, {"disagreement_risk": "sure"}):
        assert tasks.Task.from_mapping({"id": "a/b#1", "review": bad}).review is None


def test_review_keeps_only_the_vocabulary():
    review = tasks.Task.from_mapping(
        {
            "id": "a/b#1",
            "review": {
                "verdict": "shown",
                "disagreement_risk": "medium",
                "reason": 5,
                "junk": 1,
                "concerns": [
                    {
                        "concern": "cost",
                        "stance": "caution",
                        "severity": "major",
                        "x": 1,
                    },
                    {"concern": "tone", "stance": "weird", "severity": "huge"},
                    {"stance": "object"},
                    "str",
                ],
            },
        }
    ).review
    assert review == {
        "verdict": "shown",
        "disagreement_risk": "medium",
        "reason": None,
        "concerns": [
            {
                "concern": "cost",
                "stance": "caution",
                "severity": "major",
                "reason": None,
            },
            {"concern": "tone", "stance": None, "severity": None, "reason": None},
        ],
    }


def test_merge_carries_a_review_forward_and_a_later_one_replaces_it():
    first = {"id": "a/b#1", "review": {"disagreement_risk": "low"}}
    bare = {"id": "a/b#1", "tier": "tap"}
    newer = {"id": "a/b#1", "review": {"disagreement_risk": "high", "reason": "r"}}
    kept = tasks.merge_records([first], [bare])[0]
    assert kept["tier"] == "tap" and kept["review"]["disagreement_risk"] == "low"
    assert (
        tasks.merge_records([first], [newer])[0]["review"]["disagreement_risk"]
        == "high"
    )


def test_review_round_trips_through_as_dict():
    once = tasks.Task.from_mapping(
        {"id": "a/b#1", "review": {"disagreement_risk": "high", "reason": "r"}}
    ).as_dict()
    assert tasks.Task.from_mapping(once).as_dict() == once


def test_merge_explicit_null_review_clears_and_changed_decision_drops():
    first = {"id": "a/b#1", "review": {"disagreement_risk": "low"}}
    assert (
        tasks.merge_records([first], [{"id": "a/b#1", "review": None}])[0]["review"]
        is None
    )
    d1 = {
        "id": "a/b#1",
        "decision": {"question": "q", "options": ["A"]},
        "review": first["review"],
    }
    same = {"id": "a/b#1", "decision": {"question": "q", "options": ["A"]}}
    changed = {"id": "a/b#1", "decision": {"question": "q", "options": ["B"]}}
    assert tasks.merge_records([d1], [same])[0]["review"]["disagreement_risk"] == "low"
    assert tasks.merge_records([d1], [changed])[0]["review"] is None


def test_apply_reviews_sets_only_review_and_ignores_unknown_ids():
    recs = [{"id": "a/b#1", "tier": "tap", "ask": "A", "decision": {"question": "q"}}]
    out = tasks.apply_reviews(
        recs,
        [
            {"id": "a/b#1", "review": {"disagreement_risk": "low"}},
            {"id": "n/o#2", "review": {"disagreement_risk": "high"}},
        ],
    )
    assert len(out) == 1 and out[0]["review"]["disagreement_risk"] == "low"
    assert {k: v for k, v in out[0].items() if k != "review"} == recs[0]


def test_review_verdict_validated_and_blank_concern_dropped():
    r = tasks.Task.from_mapping(
        {
            "id": "a/b#1",
            "review": {
                "verdict": "maybe",
                "disagreement_risk": "low",
                "concerns": [{"concern": "  "}, {"concern": ""}],
            },
        }
    ).review
    assert r["verdict"] is None and r["concerns"] == []
    ok = tasks.Task.from_mapping({"id": "a/b#1", "review": {"verdict": "shown"}}).review
    assert ok["verdict"] == "shown"
