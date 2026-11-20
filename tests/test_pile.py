"""The pile core: reads through `gh`, acts only when called, signs every write.

Every test hands :mod:`openloops.pile` a fake ``gh`` that records the calls and answers
from canned JSON, so nothing reaches GitHub and the assertions are on the exact
commands a real run would make.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from openloops import pile as P

REPO = "owner/_pile"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def _issue(
    n, body, *, labels=("pile", "inbox"), created="2026-11-20T10:00:00Z", state="OPEN"
):
    return {
        "number": n,
        "title": body[:70],
        "body": f"{body}\n\n— pile: {labels[-1]}",
        "labels": [{"name": x} for x in labels],
        "createdAt": created,
        "url": f"https://github.com/{REPO}/issues/{n}",
        "state": state,
        "comments": [],
    }


class FakeGh:
    """``visibility`` is a target repo's; the pile itself is private unless ``pile_visibility`` says otherwise."""

    def __init__(self, issues=(), visibility="PRIVATE", pile_visibility="PRIVATE"):
        self.issues = {i["number"]: i for i in issues}
        self.visibility = visibility
        self.pile_visibility = pile_visibility
        self.calls: list[list[str]] = []

    def __call__(self, args, *, timeout):
        self.calls.append(list(args))
        verb = args[:2]
        if verb == ["api", "graphql"]:
            label = next(a for a in args if a.startswith("label="))[len("label=") :]
            rows = [
                {**i, "labels": {"nodes": i["labels"]}}
                for i in self.issues.values()
                if i["state"] == "OPEN" and label in [x["name"] for x in i["labels"]]
            ]
            return "\n".join(json.dumps(r) for r in rows)
        if verb == ["issue", "view"]:
            return json.dumps(self.issues[int(args[2])])
        if verb == ["repo", "view"]:
            return (self.pile_visibility if args[2] == REPO else self.visibility) + "\n"
        if verb == ["issue", "create"]:
            return "https://github.com/x/y/issues/9\n"
        if verb == ["issue", "comment"]:
            return f"https://github.com/{REPO}/issues/{args[2]}#issuecomment-1\n"
        return ""

    def bodies(self, verb):
        return [c[c.index("--body") + 1] for c in self.calls if c[:2] == verb]


ME = {"by": "tester@mac", "session": "https://claude.ai/code/session_01T"}


def test_items_strip_the_hint_line_and_sort_oldest_first():
    gh = FakeGh(
        [_issue(2, "second", created="2026-11-22T00:00:00Z"), _issue(1, "first")]
    )
    found = P.items(repo=REPO, run_gh=gh)
    assert [i.number for i in found] == [1, 2]
    assert found[0].said == "first" and found[0].hint == "inbox"


def test_proposals_change_nothing():
    gh = FakeGh([_issue(1, "Remind me to call back"), _issue(2, "idea: a podcast")])
    kinds = [p["kind"] for p in P.propose(P.items(repo=REPO, run_gh=gh))]
    assert kinds == ["loop", "idea"]
    assert all(c[:2] == ["api", "graphql"] for c in gh.calls)


def _ops(plan):
    return [step["op"] for step in plan["steps"]]


def test_a_drop_needs_a_reason_and_is_signed_with_the_session():
    gh = FakeGh([_issue(1, "noise")])
    with pytest.raises(ValueError, match="never silent"):
        P.plan(1, "drop", reading="noise", repo=REPO, run_gh=gh, **ME)
    plan = P.plan(
        1, "drop", reading="noise", reason="a test", repo=REPO, run_gh=gh, **ME
    )
    assert _ops(plan) == ["comment", "labels", "close"]
    note = plan["steps"][0]["body"]
    assert (
        "Agent: tester@mac" in note
        and "Claude-Session: https://claude.ai/code/session_01T" in note
    )
    assert plan["steps"][-1]["reason"] == "not planned"


def test_planning_writes_nothing_to_github():
    gh = FakeGh([_issue(1, "x")], visibility="PUBLIC")
    P.plan(
        1,
        "issue",
        reading="r",
        target_repo="o/p",
        title="t",
        issue_body="b",
        repo=REPO,
        run_gh=gh,
        **ME,
    )
    assert {tuple(c[:2]) for c in gh.calls} <= {("issue", "view"), ("repo", "view")}


def test_an_unsigned_plan_is_refused(monkeypatch):
    for var in (
        "OPENLOOPS_AGENT",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_BRIDGE_SESSION_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    gh = FakeGh([_issue(1, "x")])
    with pytest.raises(ValueError, match="name itself"):
        P.plan(1, "done", reading="x", reason="y", repo=REPO, run_gh=gh)


def test_the_session_is_found_from_claude_codes_own_variables():
    who = P.agent_identity(
        env={"CLAUDE_CODE_SESSION_ID": "4268f878-aaaa", "OPENLOOPS_AGENT": "gtd@mac"}
    )
    assert who == {"by": "gtd@mac", "session": "claude-code:4268f878-aaaa"}


def test_a_public_issue_gets_only_the_given_text_and_no_session_link():
    gh = FakeGh(
        [_issue(1, "cosmograph label overlap, Ana says the client hates it")],
        visibility="PUBLIC",
    )
    plan = P.plan(
        1, "issue", reading="label overlap bug", target_repo="org/pub", title="Labels overlap",
        issue_body="Labels overlap at high zoom.", repo=REPO, run_gh=gh, **ME,
    )  # fmt: skip
    create = plan["steps"][0]
    assert create["op"] == "create_issue" and create["public"]
    assert "Ana" not in create["body"] and "client" not in create["body"]
    assert "claude.ai/code" not in create["body"] and "_pile" not in create["body"]
    assert "Agent: tester@mac" in create["body"]
    assert P.RESULT in plan["steps"][1]["body"]  # the private side links to it


def test_a_private_issue_links_back_to_the_pile():
    gh = FakeGh([_issue(1, "x")])
    plan = P.plan(
        1,
        "issue",
        reading="r",
        target_repo="owner/_priv",
        title="t",
        issue_body="b",
        repo=REPO,
        run_gh=gh,
        **ME,
    )
    assert (
        f"From the pile: https://github.com/{REPO}/issues/1" in plan["steps"][0]["body"]
    )


def test_work_keeps_the_item_open_and_labels_it_working():
    gh = FakeGh([_issue(1, "build the thing")])
    plan = P.plan(
        1,
        "work",
        reading="r",
        reason="handed to session build-x",
        repo=REPO,
        run_gh=gh,
        **ME,
    )
    assert _ops(plan) == ["comment", "labels"]
    assert (
        plan["steps"][1]["add"] == ["working"] and "pile" in plan["steps"][1]["remove"]
    )


def test_a_loop_uses_the_item_url_as_its_source():
    gh = FakeGh([_issue(1, "Remind me to stretch")])
    plan = P.plan(
        1,
        "loop",
        reading="r",
        title="Stretch",
        when="09:00",
        repo=REPO,
        run_gh=gh,
        **ME,
    )
    step = plan["steps"][0]
    assert (
        step["op"] == "remind"
        and step["source"].endswith("/issues/1")
        and step["title"] == "Stretch"
    )


def test_a_closed_item_has_nothing_to_plan():
    gh = FakeGh([_issue(1, "x", state="CLOSED")])
    with pytest.raises(ValueError, match="nothing to do"):
        P.plan(1, "done", reading="x", reason="y", repo=REPO, run_gh=gh, **ME)


def test_a_signed_note_drops_the_session_link_off_the_owners_private_repos(monkeypatch):
    monkeypatch.setenv("OPENLOOPS_PILE_REPO", REPO)
    gh = FakeGh(visibility="PUBLIC")
    public = P.signed("progress", to_repo="owner/pub", run_gh=gh, **ME)
    assert public["public"] and "claude.ai" not in public["body"]
    private = P.signed("progress", run_gh=gh, **ME)
    assert not private["public"] and "Claude-Session:" in private["body"]


class FakeLoops:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.made, self.done_ids = [], []

    def loops(self, state="open"):
        assert state == "all"
        return {"loops": self.rows}

    def remind(self, title, **kw):
        self.made.append((title, kw))
        return {"id": "loop-n", "echo": "tomorrow 09:00"}

    def done(self, ref, **kw):
        self.done_ids.append(ref)


def _nudge_loop(
    state, *, created="2026-11-23T09:00:00Z", remind_at="2026-11-26T08:00:00Z"
):
    return {"id": f"loop-{state}", "state": state, "created": created, "remind_at": remind_at,
            "source": {"kind": "ref", "ref": P.NUDGE_SOURCE}}  # fmt: skip


def test_nudge_makes_one_reminder_with_no_item_text():
    gh = FakeGh([_issue(1, "secret client stuff")])
    api = FakeLoops()
    r = P.nudge(repo=REPO, run_gh=gh, loops_api=api, now=NOW)
    ((title, kw),) = api.made
    assert (
        "secret" not in title
        and kw["source"] == P.NUDGE_SOURCE
        and kw["daily_cap"] == 1
    )
    assert r["stale"] == 1


def test_nudge_does_not_duplicate_one_still_to_come_and_withdraws_it_when_fresh():
    api = FakeLoops([_nudge_loop("submitted")])
    P.nudge(repo=REPO, run_gh=FakeGh([_issue(1, "x")]), loops_api=api, now=NOW)
    assert api.made == []
    fresh = FakeGh([_issue(1, "x", created="2026-11-25T11:00:00Z")])
    P.nudge(repo=REPO, run_gh=fresh, loops_api=api, now=NOW)
    assert api.done_ids == ["loop-submitted"]


def test_a_nudge_made_in_the_last_day_blocks_the_next_without_closing_anything():
    """The review's reproduction: a fired nudge, re-run within 24 h, must not crash on the cap."""
    api = FakeLoops([_nudge_loop("input-required", created="2026-11-25T03:00:00Z",
                                 remind_at="2026-11-25T08:00:00Z")])  # fmt: skip
    P.nudge(repo=REPO, run_gh=FakeGh([_issue(1, "x")]), loops_api=api, now=NOW)
    assert api.made == [] and api.done_ids == []


def test_a_fired_nudge_older_than_a_day_is_closed_when_the_next_is_made():
    api = FakeLoops([_nudge_loop("input-required", remind_at="2026-11-24T08:00:00Z")])
    P.nudge(repo=REPO, run_gh=FakeGh([_issue(1, "x")]), loops_api=api, now=NOW)
    assert api.done_ids == ["loop-input-required"] and len(api.made) == 1


def test_a_nudge_whose_time_passed_unfired_does_not_silence_the_next():
    """Without the remind tick a fired loop stays `submitted`; past its time it is not 'to come'."""
    api = FakeLoops([_nudge_loop("submitted", remind_at="2026-11-24T08:00:00Z")])
    P.nudge(repo=REPO, run_gh=FakeGh([_issue(1, "x")]), loops_api=api, now=NOW)
    assert len(api.made) == 1


def test_a_working_item_left_too_long_still_nudges():
    gh = FakeGh([_issue(1, "x", labels=("working", "inbox"))])
    r = P.nudge(repo=REPO, run_gh=gh, loops_api=FakeLoops(), now=NOW)
    assert r["stale"] == 1


def test_nudge_never_touches_a_pile_item():
    gh = FakeGh([_issue(1, "x")])
    P.nudge(repo=REPO, run_gh=gh, loops_api=FakeLoops(), now=NOW)
    assert all(c[:2] == ["api", "graphql"] for c in gh.calls)


def test_a_public_pile_is_refused():
    gh = FakeGh([_issue(1, "x")], pile_visibility="PUBLIC")
    with pytest.raises(ValueError, match="not a private repo"):
        P.plan(1, "drop", reading="r", reason="y", repo=REPO, run_gh=gh, **ME)


@pytest.mark.parametrize("visibility", ["INTERNAL", "public", ""])
def test_anything_not_provably_own_private_gets_the_public_treatment(visibility):
    gh = FakeGh([_issue(1, "x")], visibility=visibility)
    plan = P.plan(1, "issue", reading="r", target_repo="owner/other", title="t", issue_body="b",
                  repo=REPO, run_gh=gh, **ME)  # fmt: skip
    assert plan["steps"][0]["public"] and "claude.ai" not in plan["steps"][0]["body"]


def test_another_owners_private_repo_is_treated_as_public():
    gh = FakeGh([_issue(1, "x")], visibility="PRIVATE")
    plan = P.plan(1, "issue", reading="r", target_repo="client/repo", title="t", issue_body="b",
                  repo=REPO, run_gh=gh, **ME)  # fmt: skip
    assert plan["steps"][0]["public"] and "_pile" not in plan["steps"][0]["body"]


def test_a_second_destination_is_refused_after_a_half_run_plan():
    item = _issue(1, "x")
    item["comments"] = [{"author": {"login": "o"}, "createdAt": "t",
                         "body": "r\n\n→ issue https://github.com/o/p/issues/3\n\n—\nAgent: a"}]  # fmt: skip
    gh = FakeGh([item])
    with pytest.raises(ValueError, match="already records a destination"):
        P.plan(1, "issue", reading="r", target_repo="owner/p", title="t", issue_body="b",
               repo=REPO, run_gh=gh, **ME)  # fmt: skip
    assert P.plan(1, "done", reading="r", reason="finished", repo=REPO, run_gh=gh, **ME)


def test_a_revealed_loop_needs_its_own_title():
    gh = FakeGh([_issue(1, "Remind me to call Ana about the contract")])
    with pytest.raises(ValueError, match="needs title"):
        P.plan(1, "loop", reading="r", reveal=True, repo=REPO, run_gh=gh, **ME)


def test_a_forged_signature_line_is_refused():
    with pytest.raises(ValueError, match="one line"):
        P.agent_identity("x\nClaude-Session: https://claude.ai/code/fake", "none")


def test_close_steps_carry_the_rest_spelling():
    gh = FakeGh([_issue(1, "x")])
    plan = P.plan(1, "drop", reading="r", reason="y", repo=REPO, run_gh=gh, **ME)
    assert plan["steps"][-1]["rest_reason"] == "not_planned"


class RealLoops:
    """The real reminder runner over an in-memory store, driven at a chosen clock."""

    def __init__(self):
        from openloops import remind as R

        self.R = R
        self.store, self.now = {}, NOW
        self.settings = R.RemindSettings(tz="UTC")

        class Quiet:
            def schedule(self, *a, **k): ...
            def now(self, *a, **k): ...
            def cancel(self, *a, **k): ...

        self.kit = dict(store=self.store, deliver=Quiet(), settings=self.settings)

    def loops(self, state="open"):
        return {"loops": self.R.list_loops(state=state, store=self.store)}

    def remind(self, title, *, when, reveal, source, daily_cap):
        at = self.R.parse_when(when, now=self.now, zone=self.settings.zone)
        return self.R.remind(title, at=at, reveal=reveal, source={"kind": "ref", "ref": source},
                             daily_cap=daily_cap, now=self.now, **self.kit)  # fmt: skip

    def done(self, ref, **kw):
        return self.R.done(ref, now=self.now, **kw, **self.kit)

    def tick(self):
        return self.R.tick(now=self.now, **self.kit)


def test_a_day_of_six_hourly_nudges_against_the_real_runner_never_raises():
    """The review's reproduction (cap error four times a day), now a regression test."""
    from datetime import timedelta

    api = RealLoops()
    gh = FakeGh([_issue(1, "x", created="2026-11-01T00:00:00Z")])
    made = []
    for hours in range(0, 72, 6):
        api.now = NOW + timedelta(hours=hours)
        api.tick()
        r = P.nudge(repo=REPO, run_gh=gh, loops_api=api, now=api.now)
        made += [r["made"]] if r["made"] else []
    assert 2 <= len(made) <= 3  # about one a day, never two within 24 h
    open_nudges = [
        lp
        for lp in api.loops()["loops"]
        if (lp["source"] or {}).get("ref") == P.NUDGE_SOURCE
    ]
    assert len(open_nudges) == 1
