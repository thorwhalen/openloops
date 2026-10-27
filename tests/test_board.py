"""The board build: runs grouping, the age join, the files it writes, and the CLI path."""

from __future__ import annotations

import json

from openloops import board, tools
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
