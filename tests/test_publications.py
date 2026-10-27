"""``published`` reads documents through one seam: a fake publisher stands in for annals."""

import subprocess

from openloops import tools
from openloops.publications import published

DOCS = [
    {
        "id": "a1",
        "title": "Old",
        "created": "2026-01-01T00:00:00Z",
        "source": {"session": "s1"},
    },
    {
        "id": "b2",
        "title": "New",
        "created": "2026-01-03T00:00:00Z",
        "source": {"session": "s2"},
    },
    {
        "id": "c3",
        "title": "Mid",
        "created": "2026-01-02T00:00:00Z",
        "updated": "2026-01-04T00:00:00Z",
        "source": {"session": "s1"},
    },
    {"id": "d4", "title": "Loose", "created": "2025-12-31T00:00:00Z"},
]


def test_rows_are_newest_first_with_links_and_session_counts():
    report = published(source=DOCS)
    assert [r["id"] for r in report["rows"]] == [
        "c3",
        "b2",
        "a1",
        "d4",
    ]  # `updated` wins
    assert report["rows"][0]["url"] == "https://apps.thorwhalen.com/annals/d/c3"
    assert report["by_session"] == {"s1": 2, "s2": 1, "(none)": 1}


def test_a_callable_source_and_a_session_filter():
    report = published(source=lambda: iter(DOCS), session="s1")
    assert [r["id"] for r in report["rows"]] == ["c3", "a1"]


def test_limit_clips():
    assert len(published(source=DOCS, limit=2)["rows"]) == 2


def test_missing_annals_is_not_an_empty_list(monkeypatch):
    monkeypatch.setattr("openloops.publications.shutil.which", lambda name: None)
    report = published()
    assert report["listed"] is False and "annals" in report["error"]


def test_the_default_source_parses_annals_ls(monkeypatch):
    monkeypatch.setattr(
        "openloops.publications.shutil.which", lambda name: "/bin/annals"
    )
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, '{"docs": [{"id": "z9"}], "total": 1}', ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert published(limit=3)["rows"][0]["id"] == "z9"
    assert seen == [["/bin/annals", "ls", "-l", "3"]]


def test_the_tool_passes_the_seam_through():
    assert tools.published(source=DOCS)["listed"] is True
