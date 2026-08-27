"""The SSOT surface: flat arguments in, JSON-ready dicts out, nothing printed."""

import io
import json
from contextlib import redirect_stdout

import pytest

from fixtures import asking_session, closed_session, write_transcripts

from openloops import tools


def two_digests():
    store = {}
    tools.sync(
        transcript_source={},
        digests_store=store,
    )
    store.update(
        {
            "m/open/aaa.md": "---\nsession: aaa\nstate: open\nproject: p\n"
            "last_turn: 2026-01-02T00:00:00Z\nconfidence: low\n---\nbody a",
            "m/archive/bbb.md": "---\nsession: bbb\nstate: archive\nproject: q\n"
            "last_turn: 2026-01-01T00:00:00Z\nconfidence: high\n---\nbody b",
        }
    )
    return store


def test_every_tool_returns_something_json_serialisable(projects_dir):
    write_transcripts(projects_dir, {"s1": closed_session("s1")})
    for result in (
        tools.sync(),
        tools.ls(state="all"),
        tools.status(),
        tools.show("s1"),
    ):
        json.dumps(result)


def test_no_tool_prints(projects_dir):
    """The core has no opinion about how it is called; printing belongs to a surface."""
    write_transcripts(projects_dir, {"s1": closed_session("s1")})
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        tools.sync()
        tools.ls(state="all")
        tools.status()
    assert buffer.getvalue() == ""


def test_ls_filters_and_orders():
    store = two_digests()
    assert [r["session"] for r in tools.ls(state="all", digests_store=store)] == ["aaa", "bbb"]
    assert [r["session"] for r in tools.ls(state="open", digests_store=store)] == ["aaa"]
    assert [r["session"] for r in tools.ls(state="all", project="q", digests_store=store)] == ["bbb"]
    assert [r["session"] for r in tools.ls(state="all", confidence="high", digests_store=store)] == ["bbb"]
    assert tools.ls(state="all", source="other", digests_store=store) == []


def test_ls_limit_is_honoured_and_zero_means_all():
    store = two_digests()
    assert len(tools.ls(state="all", limit=1, digests_store=store)) == 1
    assert len(tools.ls(state="all", limit=0, digests_store=store)) == 2


def test_ls_refuses_a_state_that_is_not_one():
    with pytest.raises(ValueError):
        tools.ls(state="running", digests_store={})


def test_show_by_prefix_and_its_two_failure_modes():
    store = two_digests()
    assert tools.show("aa", digests_store=store)["key"] == "m/open/aaa.md"
    with pytest.raises(KeyError):
        tools.show("zzz", digests_store=store)

    store["m/open/aab.md"] = "---\nsession: aab\n---\n"
    with pytest.raises(KeyError, match="matches 2"):
        tools.show("aa", digests_store=store)


def test_status_reports_the_cache_age_even_when_there_is_no_cache(projects_dir):
    info = tools.status(digests_store={})
    assert info["cache_mtime"] is None
    tools.sync()
    assert tools.status(digests_store={})["cache_mtime"] is not None


def test_status_counts_retained_digests_separately(projects_dir):
    write_transcripts(projects_dir, {"s1": asking_session("s1")})
    store = {}
    tools.sync(digests_store=store, source="m")
    store["m/open/gone.md"] = "---\nsession: gone\n---\n"
    info = tools.status(digests_store=store, source="m")
    assert info["retained"] == 1
    assert info["sessions_on_disk"] == 1


def test_the_dispatch_list_is_the_public_surface():
    names = {f.__name__ for f in tools._dispatch_funcs}
    assert names == {"sync", "ls", "show", "status", "owed", "blocked", "dashboard"}
    for func in tools._dispatch_funcs:
        assert func.__doc__, f"{func.__name__} needs a docstring — it is the CLI help"


def test_swapping_the_seams_can_be_isolated_from_the_real_cache(tmp_path):
    """A fixture's revisions must not be writable into the caller's own cache."""
    from openloops.base import Session
    from openloops.store import load_sync_state

    scoped = tmp_path / "elsewhere"
    tools.sync(
        transcript_source={"s1": Session(key="s1", last_assistant_text="Merged.")},
        digests_store={},
        source="m",
        state_dir=str(scoped),
    )
    assert (scoped / "sync-state.json").exists()
    assert load_sync_state() == {}, "the default cache must be untouched"


def test_every_row_carries_every_documented_field():
    """`row["title"]` must not be a coin flip — most sessions have no custom title."""
    rows = tools.ls(
        state="all",
        digests_store={"m/open/s1.md": "---\nsession: s1\n---\nbody"},
    )
    assert set(tools.ROW_FIELDS) <= set(rows[0])
    assert rows[0]["title"] == "" and rows[0]["ai_title"] == ""
