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
    def __init__(self, issues=(), visibility="PRIVATE"):
        self.issues = {i["number"]: i for i in issues}
        self.visibility = visibility
        self.calls: list[list[str]] = []

    def __call__(self, args, *, timeout):
        self.calls.append(list(args))
        verb = args[:2]
        if verb == ["issue", "list"]:
            return json.dumps([i for i in self.issues.values() if i["state"] == "OPEN"])
        if verb == ["issue", "view"]:
            return json.dumps(self.issues[int(args[2])])
        if verb == ["repo", "view"]:
            return self.visibility + "\n"
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
    assert all(c[:2] in (["issue", "list"],) for c in gh.calls)


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
        target_repo="me/_priv",
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


def test_a_signed_note_drops_the_session_link_on_a_public_repo():
    body = P.signed("progress", public=True, **ME)["body"]
    assert "Agent: tester@mac" in body and "claude.ai" not in body


class FakeLoops:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.made, self.done_ids = [], []

    def loops(self, state="open"):
        return {"loops": self.rows}

    def remind(self, title, **kw):
        self.made.append((title, kw))
        return {"id": "loop-n", "echo": "tomorrow 09:00"}

    def done(self, ref, **kw):
        self.done_ids.append(ref)


def _nudge_loop(state):
    return {
        "id": f"loop-{state}",
        "state": state,
        "source": {"kind": "ref", "ref": P.NUDGE_SOURCE},
    }


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


def test_nudge_does_not_duplicate_a_pending_one_and_withdraws_it_when_fresh():
    stale = FakeGh([_issue(1, "x")])
    api = FakeLoops([_nudge_loop("submitted")])
    P.nudge(repo=REPO, run_gh=stale, loops_api=api, now=NOW)
    assert api.made == []
    fresh = FakeGh([_issue(1, "x", created="2026-11-25T11:00:00Z")])
    P.nudge(repo=REPO, run_gh=fresh, loops_api=api, now=NOW)
    assert api.done_ids == ["loop-submitted"]


def test_nudge_closes_a_fired_one_when_it_makes_the_next():
    gh = FakeGh([_issue(1, "x")])
    api = FakeLoops([_nudge_loop("input-required")])
    P.nudge(repo=REPO, run_gh=gh, loops_api=api, now=NOW)
    assert api.done_ids == ["loop-input-required"] and len(api.made) == 1


def test_nudge_never_touches_a_pile_item():
    gh = FakeGh([_issue(1, "x")])
    P.nudge(repo=REPO, run_gh=gh, loops_api=FakeLoops(), now=NOW)
    assert all(c[:2] == ["issue", "list"] for c in gh.calls)
