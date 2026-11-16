"""The board build: runs grouping, the age join, the files it writes, and the CLI path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openloops import board, job, tools
from openloops import board_refresh as refresh
from openloops.__main__ import main


def _t(id, *, tier="browser", pattern="api-key", status="open", minutes=3, **kw):
    return {
        "id": id,
        "url": f"https://github.com/{id.replace('#', '/issues/')}",
        "tier": tier,
        "pattern": pattern,
        "status": status,
        "minutes": minutes,
        **kw,
    }


def test_runs_follow_spec_order_and_a_run_of_one_is_not_a_run():
    tasks = [
        _t("a/x#1"),
        _t("a/y#2"),
        _t("a/z#3", pattern="purchase"),  # alone: no run
        _t("a/w#4", status="stale"),  # clean-up, whatever its pattern
        _t("a/v#5", tier="mac-only", pattern="server-chore"),
        _t("a/u#6", tier="mac-only"),
        _t("a/t#7", status="not-for-user"),  # never on a run
    ]
    runs = board.group_runs(tasks)
    assert [(r["key"], r["ids"]) for r in runs] == [
        ("cleanup", ["a/w#4"]),
        ("api-key", ["a/x#1", "a/y#2"]),
        ("mac-only", ["a/u#6", "a/v#5"]),
    ]
    assert runs[1]["minutes_each"] == 3 and runs[1]["tier"] == "browser"


def test_extras_overlay_a_run_and_absorb_another():
    tasks = [_t(f"a/n#{i}", pattern="npm-trusted-publisher") for i in (1, 2)]
    tasks += [
        _t(f"a/f#{i}", pattern="npm-first-publish", tier="session") for i in (3, 4)
    ]
    extras = {
        "npm-trusted-publisher": {
            "absorb": ["npm-first-publish"],
            "prompt": "do it",
            "packages": [{"pkg": "x"}],
        }
    }
    runs = board.group_runs(tasks, extras=extras)
    assert [r["key"] for r in runs] == ["npm-trusted-publisher"]
    assert runs[0]["ids"] == ["a/f#3", "a/f#4", "a/n#1", "a/n#2"]
    assert runs[0]["prompt"] == "do it" and runs[0]["packages"] == [{"pkg": "x"}]


def test_custom_specs_replace_the_packaged_ones(tmp_path):
    specs = tmp_path / "specs.json"
    specs.write_text(
        json.dumps(
            [{"key": "api-key", "title": "Keys", "min_items": 1, "machine": "box"}]
        )
    )
    runs = board.group_runs([_t("a/x#1")], specs=board.run_specs(specs))
    assert runs == [
        {
            "key": "api-key",
            "title": "Keys",
            "why": None,
            "steps": [],
            "tier": "browser",
            "minutes_each": 3,
            "ids": ["a/x#1"],
            "machine": "box",
        }
    ]


def test_every_packaged_spec_names_a_known_pattern():
    from openloops.tasks import PATTERNS

    keys = [s["key"] for s in board.run_specs()]
    assert len(keys) == len(set(keys))
    assert set(keys) <= {*PATTERNS, board.CLEANUP_KEY}


def test_build_writes_the_five_files_sorted_and_dated(tmp_path):
    records = [
        _t("a/s#1", tier="session", minutes=5),
        _t("a/t#2", tier="tap", minutes=2),
    ]
    candidates = [{"url": records[0]["url"], "created": "2026-08-01"}]
    result = board.build_board(
        records,
        tmp_path / "out",
        candidates=candidates,
        session="desk",
        read_only_orgs=["ro-org"],
        machine="box",
    )
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == sorted(board.BOARD_FILES)
    written = json.loads((out / "tasks.json").read_text())
    assert [t["id"] for t in written] == ["a/t#2", "a/s#1"], "cheapest tier first"
    assert written[1]["created"] == "2026-08-01"
    assert json.loads((out / "board.json").read_text()) == {
        "title": board.DFLT_TITLE,
        "session": "desk",
        "read_only_orgs": ["ro-org"],
        "machine": "box",
        "store": {"kind": "artifact"},
    }
    assert result["tasks"] == 2 and result["counts"]["tier"] == {"tap": 1, "session": 1}


def test_the_page_reads_its_deployment_settings_rather_than_baking_them_in():
    page = (board.board_dir() / "index.html").read_text(encoding="utf-8")
    assert 'fetch("board.json")' in page and "READ_ONLY_ORGS" in page
    # A deployment's own names must not be baked into a public package's page.
    for baked in ('t.org === "', 't.org !== "', 'const SESSION = "', 'machine: "'):
        assert baked not in page


def test_gather_classify_build_end_to_end_through_the_cli(tmp_path, capsys):
    cands = tmp_path / "cands.json"
    cands.write_text(
        json.dumps(
            {
                "listed": True,
                "candidates": [
                    {
                        "url": "https://github.com/acme/w/issues/1",
                        "repo": "acme/w",
                        "title": "Decide the name",
                        "created": "2026-08-01",
                    },
                    {
                        "url": "https://github.com/acme/w/issues/2",
                        "repo": "acme/w",
                        "title": "Create an API key",
                        "created": "2026-08-02",
                    },
                ],
            }
        )
    )
    main(["board-classify", str(cands), "--out", str(tmp_path / "records.json")])
    main(
        [
            "board-build",
            str(tmp_path / "board"),
            str(tmp_path / "records.json"),
            "-c",
            str(cands),
            "--session",
            "desk",
        ]
    )
    printed = capsys.readouterr().out
    assert "wrote 2 records" in printed and "wrote 2 tasks" in printed
    written = json.loads((tmp_path / "board" / "tasks.json").read_text())
    assert [t["pattern"] for t in written] == ["decision", "api-key"]
    assert all(t["created"] for t in written)


def test_tools_board_gather_writes_its_envelope_when_asked(tmp_path):
    out = tmp_path / "g.json"
    report = tools.board_gather(
        owners=["acme"], run_gh=lambda args, *, timeout: "[]", out=str(out)
    )
    assert report["path"] == str(out) and json.loads(out.read_text())["listed"] is True


def test_a_donor_too_small_for_its_own_run_is_still_absorbed_once():
    tasks = [_t(f"a/n#{i}", pattern="npm-trusted-publisher") for i in (1, 2)]
    tasks += [_t("a/f#3", pattern="npm-first-publish")]
    extras = {
        "npm-trusted-publisher": {"absorb": ["npm-first-publish", "npm-first-publish"]}
    }
    runs = board.group_runs(tasks, extras=extras)
    assert [(r["key"], r["ids"]) for r in runs] == [
        ("npm-trusted-publisher", ["a/f#3", "a/n#1", "a/n#2"])
    ]


def test_sloppy_minutes_from_a_classifier_do_not_break_the_sort(tmp_path):
    records = [
        _t("a/x#1", minutes="5"),
        _t("a/y#2", minutes="soon"),
        _t("a/z#3", minutes=None),
    ]
    result = board.build_board(records, tmp_path)
    written = json.loads((tmp_path / "tasks.json").read_text())
    assert result["tasks"] == 3 and {t["minutes"] for t in written} == {5, None}


def test_an_http_board_names_its_api_and_a_moved_board_its_new_home(tmp_path):
    board.build_board([], tmp_path / "h", store="http", api="api")
    assert json.loads((tmp_path / "h" / "board.json").read_text())["store"] == {
        "kind": "http",
        "api": "api",
    }
    board.build_board([], tmp_path / "m", moved_to="https://example.org/board/")
    assert (
        json.loads((tmp_path / "m" / "board.json").read_text())["moved_to"]
        == "https://example.org/board/"
    )


def test_store_options_are_checked_before_anything_is_written(tmp_path):
    import pytest

    for kwargs in (
        {"store": "s3"},
        {"store": "http"},
        {"moved_to": "javascript:alert(1)"},
    ):
        with pytest.raises(ValueError):
            board.build_board([], tmp_path / "x", **kwargs)
    assert not (tmp_path / "x").exists()


def test_the_page_has_both_store_adapters_and_the_forwarding_notice():
    page = (board.board_dir() / "index.html").read_text(encoding="utf-8")
    assert "function httpStore(" in page and 'window.claude.use("db")' in page
    assert "MOVED_TO" in page and 'credentials: "same-origin"' in page


def test_a_self_hosted_page_is_a_full_document_with_a_viewport(tmp_path):
    board.build_board([], tmp_path / "h", store="http", api="board-store")
    page = (tmp_path / "h" / "index.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert 'name="viewport" content="width=device-width, initial-scale=1' in page
    # The Artifact host supplies its own skeleton: the Artifact build stays a fragment.
    board.build_board([], tmp_path / "a")
    assert (
        not (tmp_path / "a" / "index.html")
        .read_text(encoding="utf-8")
        .startswith("<!doctype")
    )


def test_cards_offer_a_snooze_picker_and_the_recommendation_in_one_tap():
    page = (board.board_dir() / "index.html").read_text(encoding="utf-8")
    for label in ("3 hours", "Tomorrow morning", "3 days", "1 week", "1 month"):
        assert f'["{label}"' in page
    assert "Snooze ▾" in page and "Snooze 1 day" not in page
    # Same answer the Decide tab's star writes, so the receiver treats it the same way.
    assert "Do what's recommended" in page
    assert 'const ACCEPT = "Accept the recommendation"' in page


def test_a_cards_own_options_are_answer_buttons():
    """A Keep/Veto (or any optioned) card is answered on the card, with the option itself:
    the receiver matches the answer against the task's options, so it must be one."""
    page = (board.board_dir() / "index.html").read_text(encoding="utf-8")
    assert 'act(t, "answer", { answer: o,' in page
    # The free-text accept appears only when the recommendation is not one of the options.
    assert "!opts.includes(rec)" in page


def test_the_page_renders_the_review_as_text_only():
    page = (board.board_dir() / "index.html").read_text(encoding="utf-8")
    start = page.index("function reviewLines")
    assert "innerHTML" not in page[start : start + 1400]
    assert page.count("reviewLines(t.review)") >= 3


def test_board_build_reviews_overlay_sets_only_the_review(tmp_path):
    recs = tmp_path / "r.json"
    recs.write_text(
        json.dumps(
            [{"url": "https://github.com/a/b/issues/1", "tier": "tap", "ask": "Do it"}]
        )
    )
    rev = tmp_path / "rev_1.json"
    rev.write_text(
        json.dumps(
            [
                {"id": "a/b#1", "review": {"disagreement_risk": "high", "reason": "x"}},
                {"id": "zz/zz#9", "review": {"disagreement_risk": "low"}},
            ]
        )
    )
    main(
        [
            "board-build",
            str(tmp_path / "b"),
            str(recs),
            "--reviews",
            str(tmp_path / "rev_*.json"),
        ]
    )
    (task,) = json.loads((tmp_path / "b" / "tasks.json").read_text())
    assert task["tier"] == "tap" and task["ask"] == "Do it"
    assert task["review"]["disagreement_risk"] == "high"


def test_the_page_can_show_only_what_was_opened_this_week():
    """An "Opened this week" chip (from Monday), which a link can pre-select with
    `?opened=week`, so "what is new and still to do" is one address."""
    page = (board.board_dir() / "index.html").read_text(encoding="utf-8")
    assert '{ k: "week", label: "Opened this week"' in page
    assert '{ k: "7d", label: "Opened in the last 7 days"' in page
    # Monday-based week start, on the phone's clock.
    assert "d.getDate() - (d.getDay() + 6) % 7" in page
    # `created` has no time: it is read as a local day, never as UTC midnight.
    assert "new Date(+m[1], m[2] - 1, +m[3])" in page
    filt = page[page.index("function viewTasks") :][:1800]
    assert "new Date(t.created)" not in filt and "onOrAfter(t)" in filt
    # The link selects To do as well, and switching the filter off rewrites the address.
    assert (
        'ui.show = SHOWS.some(x => x.k === q.get("show")) ? q.get("show") : "todo"'
        in page
    )
    assert 'u.searchParams.delete("opened")' in page and "history.replaceState" in page
    # The page says what the filter did: the day it counts from, and why a list is empty.
    assert "newest first" in page and "Nothing opened since" in page
    assert "(ui.opened ? 1 : 0)" in page


# --------------------------------------------------------------------------------
# The rebuild on a timer (openloops#39).


def _item(n, title="Add a key"):
    return {
        "id": f"a/b#{n}",
        "url": f"https://github.com/a/b/issues/{n}",
        "repo": "a/b",
        "title": title,
        "src": "label:manual-task",
        "created": "2026-11-01",
    }


def _sweep(*items, listed=True, saturated=(), calls=None):
    def gather(**kw):
        if calls is not None:
            calls.append(kw)
        return {
            "listed": listed,
            "candidates": list(items),
            "error": None if listed else "HTTP 500",
            "saturated": list(saturated),
        }

    return gather


def _seeded(tmp_path, **settings):
    """A WORK dir whose board was built once by hand (empty), as the refresh requires."""
    board.build_board([], tmp_path / "board", **settings)
    return tmp_path


def _ids(tmp_path):
    return [
        t["id"] for t in json.loads((tmp_path / "board" / "tasks.json").read_text())
    ]


def test_refresh_builds_then_leaves_an_unchanged_board_alone(tmp_path):
    _seeded(tmp_path)
    first = refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)))
    assert first["rebuilt"] and first["added"] == 2 and first["needs_enrichment"] == 2
    stamp = (tmp_path / "board" / "tasks.json").stat().st_mtime_ns
    again = refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)))
    assert again["rebuilt"] is False and again["status"] == "unchanged"
    assert (tmp_path / "board" / "tasks.json").stat().st_mtime_ns == stamp


def test_refresh_reuses_enriched_records_and_classifies_only_the_new(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)))
    path = tmp_path / "board" / "tasks.json"
    tasks = json.loads(path.read_text())
    for t in tasks:
        if t["id"] == "a/b#1":
            t["ask"] = "ENRICHED BY A BRIEF"
    path.write_text(json.dumps(tasks))
    result = refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(3)))
    assert (result["added"], result["closed"], result["kept"]) == (1, 1, 1)
    after = {t["id"]: t for t in json.loads(path.read_text())}
    assert set(after) == {"a/b#1", "a/b#3"}
    assert after["a/b#1"]["ask"] == "ENRICHED BY A BRIEF"
    new = json.loads((tmp_path / refresh.NEW_ITEMS_FILE).read_text())
    # a/b#1 is still waiting for the brief from the first build; a/b#2 closed.
    assert [c["id"] for c in new] == ["a/b#1", "a/b#3"]


def test_an_incomplete_sweep_never_rebuilds(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)))
    before = (tmp_path / "board" / "tasks.json").read_text()
    result = refresh.refresh_board(tmp_path, gather=_sweep(_item(1), listed=False))
    assert result["rebuilt"] is False and result["status"] == "incomplete"
    assert "incomplete" in result["reason"]
    assert (tmp_path / "board" / "tasks.json").read_text() == before


def test_refresh_keeps_the_boards_own_settings_and_can_publish(tmp_path):
    _seeded(
        tmp_path,
        title="Mine",
        session="s1",
        read_only_orgs=["acme"],
        store="http",
        api="/x/board-store",
    )
    dest = tmp_path / "served"
    result = refresh.refresh_board(
        tmp_path, gather=_sweep(_item(1)), publish=refresh.dir_publisher(str(dest))
    )
    cfg = json.loads((tmp_path / "board" / "board.json").read_text())
    assert cfg["title"] == "Mine" and cfg["read_only_orgs"] == ["acme"]
    assert cfg["store"] == {"kind": "http", "api": "/x/board-store"}
    assert result["published"] and (dest / "tasks.json").is_file()
    assert result["needs_republish"] is False
    assert (dest / "index.html").read_text().startswith("<!doctype html>")


def test_the_refresh_job_runs_board_refresh_on_a_start_interval(tmp_path):
    spec = job.refresh_job_spec(tmp_path, refresh_args=["--owners", "me"])
    xml = spec["xml"]
    assert "<key>StartInterval</key>" in xml and "KeepAlive" not in xml
    assert spec["program_args"][1:4] == ["-m", "openloops", "board-refresh"]
    assert spec["program_args"][-2:] == ["--owners", "me"]
    assert spec["interval"] == job.REFRESH_INTERVAL


# A: the merge is pure.


def test_merge_refresh_is_pure_and_keeps_earlier_records():
    live = [{"id": "a/b#1", "title": "Add a key", "ask": "ENRICHED"}, {"id": "a/b#2"}]
    before = json.dumps(live)
    records, fresh, plan = refresh.merge_refresh(live, [_item(1), _item(3)])
    assert json.dumps(live) == before  # inputs untouched
    assert [r["id"] for r in records] == ["a/b#1", "a/b#3"]
    assert records[0]["ask"] == "ENRICHED" and [f["id"] for f in fresh] == ["a/b#3"]
    assert (plan.kept, plan.added, plan.closed) == (("a/b#1",), ("a/b#3",), ("a/b#2",))


# B: the scope persists in refresh.json; run specs/extras reach every rebuild.


def test_flags_are_saved_in_refresh_json_and_reused_when_absent(tmp_path):
    _seeded(tmp_path)
    calls = []
    refresh.refresh_board(
        tmp_path,
        owners=["me"],
        exclude_repos=["me/secret-*"],
        gather=_sweep(_item(1), calls=calls),
    )
    state = json.loads((tmp_path / refresh.STATE_FILE).read_text())
    assert state["owners"] == ["me"] and state["exclude_repos"] == ["me/secret-*"]
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), calls=calls))
    assert calls[1]["owners"] == ["me"] and calls[1]["exclude_repos"] == ["me/secret-*"]
    assert calls[1]["review_prs"] is True and calls[1]["searches"]


def test_install_refresh_job_saves_its_flags_and_the_plist_names_only_work(
    tmp_path, monkeypatch
):
    seen = {}

    def fake_install(work_dir, **kw):
        seen.update(work_dir=work_dir, **kw)
        return {"plist": "p", "log": "l", "interval": "60"}

    monkeypatch.setattr(job, "install_refresh", fake_install)
    from openloops import __main__ as cli

    cli.install_refresh_job(str(tmp_path), owners="me,you", publish_to="host:/srv/b")
    assert "refresh_args" not in seen
    state = json.loads((tmp_path / refresh.STATE_FILE).read_text())
    assert state["owners"] == ["me", "you"] and state["publish_to"] == "host:/srv/b"
    spec = job.refresh_job_spec(tmp_path)
    assert spec["program_args"][-1] == str(tmp_path.resolve())


def test_run_extras_reach_every_rebuild_and_an_edited_kit_is_kept(tmp_path):
    _seeded(tmp_path)
    extras = tmp_path / "extras.json"
    extras.write_text(json.dumps({"api-key": {"prompt": "DEPLOYMENT PROMPT"}}))
    kit = tmp_path / "board" / "kit.html"
    kit.write_text("EDITED KIT")
    items = [
        dict(_item(n), title="Add the API key", pattern="api-key", tier="browser")
        for n in (1, 2)
    ]
    refresh.refresh_board(tmp_path, run_extras=str(extras), gather=_sweep(*items))
    refresh.refresh_board(tmp_path, gather=_sweep(*items, _item(3)))
    runs = json.loads((tmp_path / "board" / "runs.json").read_text())
    assert any(r.get("prompt") == "DEPLOYMENT PROMPT" for r in runs), runs
    assert kit.read_text() == "EDITED KIT"


def test_an_untouched_kit_follows_the_packaged_template(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))
    packaged = (board.board_dir() / "kit.html").read_text()
    assert (tmp_path / "board" / "kit.html").read_text() == packaged


# C: missing is empty, corrupt is an error.


def test_a_corrupt_tasks_json_raises_instead_of_resetting(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))
    path = tmp_path / "board" / "tasks.json"
    path.write_text(path.read_text()[:-5])
    with pytest.raises(ValueError, match="not valid JSON"):
        refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))


@pytest.mark.parametrize(
    "name, content, match",
    [
        ("tasks.json", '{"a": 1}', "should hold a JSON list"),
        ("tasks.json", "[1, 2]", "not task records"),
        ("board.json", "{oops", "not valid JSON"),
        ("board.json", "[]", "should hold a JSON object"),
    ],
)
def test_a_board_file_of_the_wrong_shape_raises(tmp_path, name, content, match):
    _seeded(tmp_path)
    (tmp_path / "board" / name).write_text(content)
    with pytest.raises(ValueError, match=match):
        refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))


def test_a_corrupt_refresh_json_raises(tmp_path):
    _seeded(tmp_path)
    (tmp_path / refresh.STATE_FILE).write_text("{nope")
    with pytest.raises(ValueError, match="refresh.json"):
        refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))


def test_a_first_run_without_a_board_asks_for_a_build_by_hand(tmp_path):
    published = []
    with pytest.raises(ValueError, match="ol board-build"):
        refresh.refresh_board(
            tmp_path, gather=_sweep(_item(1)), publish=published.append
        )
    assert not published and not (tmp_path / "board").exists()
    # Explicit settings are an explicit choice.
    result = refresh.refresh_board(
        tmp_path, gather=_sweep(_item(1)), settings={"title": "Mine"}
    )
    assert result["rebuilt"]


# D: a saturated sweep never closes; a mass close needs force.


def test_a_saturated_sweep_adds_but_never_closes(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2), _item(3)))
    result = refresh.refresh_board(
        tmp_path, gather=_sweep(_item(1), _item(4), saturated=["me label"])
    )
    assert result["rebuilt"] and result["closed"] == 0 and result["withheld"] == 2
    assert sorted(_ids(tmp_path)) == ["a/b#1", "a/b#2", "a/b#3", "a/b#4"]


def test_closing_most_of_a_large_board_is_refused_without_force(tmp_path):
    _seeded(tmp_path)
    many = [_item(i) for i in range(1, 50)]
    refresh.refresh_board(tmp_path, gather=_sweep(*many))
    published = []
    result = refresh.refresh_board(tmp_path, gather=_sweep(), publish=published.append)
    assert result["status"] == "refused" and not result["rebuilt"]
    assert "49 of 49" in result["reason"] and len(_ids(tmp_path)) == 49
    forced = refresh.refresh_board(tmp_path, gather=_sweep(), force=True)
    assert forced["rebuilt"] and _ids(tmp_path) == []
    # An empty board that stays empty is not rebuilt on every tick.
    again = refresh.refresh_board(tmp_path, gather=_sweep())
    assert again["status"] == "unchanged"


def test_a_small_board_may_close_everything(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)))
    assert refresh.refresh_board(tmp_path, gather=_sweep())["rebuilt"]


# E: new-items.json accumulates.


def test_new_items_accumulate_until_closed(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)))
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2), _item(3)))
    new = tmp_path / refresh.NEW_ITEMS_FILE
    assert [c["id"] for c in json.loads(new.read_text())] == ["a/b#1", "a/b#2", "a/b#3"]
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(3)), force=True)
    assert [c["id"] for c in json.loads(new.read_text())] == ["a/b#1", "a/b#3"]


# F: publish on a hash mismatch, record only after success; artifact boards say so.


def test_a_failed_publish_is_retried_on_the_next_tick(tmp_path):
    _seeded(tmp_path, store="http", api="/x")
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))

    def boom(board_dir):
        raise RuntimeError("scp failed")

    with pytest.raises(refresh.PublishError, match="scp failed"):
        refresh.refresh_board(tmp_path, gather=_sweep(_item(1), _item(2)), publish=boom)
    assert _ids(tmp_path) == ["a/b#1", "a/b#2"]  # the local rebuild stays
    published = []
    result = refresh.refresh_board(
        tmp_path, gather=_sweep(_item(1), _item(2)), publish=published.append
    )
    assert result["status"] == "unchanged" and result["published"] and published
    # Published once: the next tick has nothing to send.
    again = refresh.refresh_board(
        tmp_path, gather=_sweep(_item(1), _item(2)), publish=published.append
    )
    assert again["published"] is False and len(published) == 1


def test_an_artifact_board_needs_a_republish_after_a_rebuild(tmp_path):
    _seeded(tmp_path)  # store defaults to the claude.ai Artifact
    result = refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))
    assert result["rebuilt"] and result["needs_republish"] is True
    assert (
        refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))["needs_republish"]
        is False
    )


def test_board_files_are_replaced_atomically(tmp_path, monkeypatch):
    _seeded(tmp_path)
    replaced = []
    real = refresh.os.replace
    monkeypatch.setattr(
        refresh.os, "replace", lambda a, b: (replaced.append(Path(b).name), real(a, b))
    )
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1)))
    assert "tasks.json" in replaced and replaced.index("tasks.json") > replaced.index(
        "runs.json"
    )
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_scp_publishing_never_prompts(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(refresh.subprocess, "run", lambda args, **kw: ran.append(args))
    refresh.dir_publisher("host:/srv/board")(tmp_path)
    assert ran[0][:4] == ["scp", "-q", "-o", "BatchMode=yes"]


# G: kept records follow GitHub's title, and are never re-classified.


def test_a_kept_record_takes_the_new_title_but_keeps_its_enrichment(tmp_path):
    _seeded(tmp_path)
    refresh.refresh_board(tmp_path, gather=_sweep(_item(1, "Add a key")))
    path = tmp_path / "board" / "tasks.json"
    tasks = json.loads(path.read_text())
    tasks[0].update(ask="ENRICHED", tier="session")
    path.write_text(json.dumps(tasks))
    result = refresh.refresh_board(
        tmp_path, gather=_sweep(_item(1, "Decide: rename the package"))
    )
    assert result["rebuilt"] and result["updated"] == 1
    task = json.loads(path.read_text())[0]
    assert task["title"] == "Decide: rename the package"
    assert (task["ask"], task["tier"]) == ("ENRICHED", "session")


# H: the CLI exits non-zero on an incomplete sweep, zero on an unchanged board.


def test_the_cli_exits_nonzero_on_an_incomplete_sweep(tmp_path, monkeypatch, capsys):
    _seeded(tmp_path)
    sweeps = iter([_sweep(_item(1)), _sweep(_item(1)), _sweep(listed=False)])

    def fake(**kw):
        return refresh.refresh_board(kw.pop("work_dir"), gather=next(sweeps), **kw)

    monkeypatch.setattr(tools, "board_refresh", fake)
    main(["board-refresh", str(tmp_path)])
    main(["board-refresh", str(tmp_path)])
    assert "board left as it was" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exit_:
        main(["board-refresh", str(tmp_path)])
    assert exit_.value.code == 1
    assert "incomplete" in capsys.readouterr().err
