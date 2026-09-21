"""The HTML page: it must never render a failure as a clean board, and never leak.

Every envelope in this file is canned, so nothing here reaches the network or needs
`gh`. That is the point of the seams; a test that needed either would be testing the
fleet rather than the renderer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openloops import tools
from openloops.dashboard import (
    DFLT_TITLE,
    headline_counts,
    rail,
    register,
    render_dashboard,
    unknown_count,
)
from openloops.egress import scan, scan_files

STAMP = "2026-02-01T00:00:00Z"


def obligation(**over):
    row = {
        "repo": "acme/widget",
        "number": 7,
        "title": "Pick a distribution name",
        "url": "https://github.com/acme/widget/issues/7",
        "created": "2026-01-02T00:00:00Z",
        "age_days": 30,
        "state": "open",
        "verify": "`gh api repos/acme/widget`",
        "predicate": "gh api repos/acme/widget",
        "evidence": "exit 1",
    }
    return {**row, **over}


def owed_envelope(*rows, **over):
    counts = {"open": 0, "discharged": 0, "unknown": 0, "with_predicate": 0, "total": 0}
    for row in rows:
        counts[row["state"]] += 1
        counts["with_predicate"] += 1 if row["predicate"] else 0
    counts["total"] = len(rows)
    envelope = {
        "listed": True,
        "checked": True,
        "error": "",
        "truncated": False,
        "label": "manual-task",
        "owners": ["acme"],
        "trusted_owners": ["acme"],
        "counts": counts,
        "rows": list(rows),
    }
    return {**envelope, **over}


def blocked_row(**over):
    row = {
        "repo": "acme/widget",
        "number": 109,
        "title": "Rename sweep forced by the companion repo",
        "url": "https://github.com/acme/widget/issues/109",
        "created": "2026-01-24T00:00:00Z",
        "age_days": 8,
        "state": "unblocked",
        "blockers": [
            {
                "repo": "acme/engine",
                "number": 15,
                "state": "closed",
                "url": "",
                "closed_at": "2026-01-27T00:00:00Z",
                "ref": "acme/engine#15 [closed]",
            }
        ],
        "cross_repo": True,
        "unblocked_days": 5,
        "evidence": "every blocker is closed: acme/engine#15 [closed]",
    }
    return {**row, **over}


def blocked_envelope(*rows, **over):
    counts = {
        "unblocked": 0,
        "blocked": 0,
        "unknown": 0,
        "cross_repo": 0,
        "candidates": len(rows),
        "without_edges": 0,
        "total": len(rows),
    }
    for row in rows:
        counts[row["state"]] += 1
    envelope = {
        "listed": True,
        "resolved": True,
        "error": "",
        "truncated": False,
        "query": "is:blocked",
        "owners": ["acme"],
        "repos": [],
        "counts": counts,
        "rows": list(rows),
    }
    return {**envelope, **over}


def session(**over):
    row = {
        "session": "abcdef1234567890",
        "source": "testhost",
        "state": "open",
        "title": "widget_rename",
        "ai_title": "",
        "project": "widget",
        "branches": "main",
        "started": "2026-01-20T00:00:00Z",
        "ended": "2026-01-21T00:00:00Z",
        "last_turn": "2026-01-21T00:00:00Z",
        "turns": "6",
        "model": "test-model",
        "confidence": "high",
        "verified": "false",
    }
    return {**row, **over}


def page(owed=None, blocked=None, sessions=None, **kwargs):
    return render_dashboard(
        owed_envelope() if owed is None else owed,
        blocked_envelope() if blocked is None else blocked,
        [] if sessions is None else sessions,
        made_at=STAMP,
        **kwargs,
    )


# --------------------------------------------------------------------------------
# The rule the whole package rests on: a failed check is never a clean board.
# --------------------------------------------------------------------------------


def test_an_unread_owed_renders_question_marks_and_never_a_zero():
    html = page(owed=owed_envelope(listed=False, error="gh: not logged in"))
    assert "gh: not logged in" in html
    assert "could not read the world" in html
    # The headline figure, and the register's own figure, are both `?`.
    assert html.count(">?<") >= 2
    assert "nothing is owed" in html  # named only to say it is NOT what this means


def test_an_unread_register_makes_the_unknown_count_itself_unknown():
    """`2` would be a count of the failures we happen to know about. That is a lie."""
    assert unknown_count(owed_envelope(listed=False), blocked_envelope(), []) is None
    counts = headline_counts(owed_envelope(listed=False), blocked_envelope(), [])
    assert counts["needs_you"] is None and counts["unknown"] is None


def test_a_caveat_is_listed_but_does_not_inflate_the_figure():
    """`--no-verify` already turns those rows into `unknown`; counting it again doubles."""
    owed = owed_envelope(obligation(state="unknown"), checked=False)
    html = page(owed=owed)
    assert "Predicates were not evaluated" in html
    assert unknown_count(owed, blocked_envelope(), []) == 2  # the row, plus empty store


def test_unknown_rows_are_never_silently_dropped():
    owed = owed_envelope(obligation(state="unknown", evidence="owner is not trusted"))
    html = page(owed=owed)
    assert "owner is not trusted" in html
    assert "Pick a distribution name" in html


def test_a_clean_board_has_to_show_what_earned_it():
    html = page(owed=owed_envelope(obligation()), sessions=[session()])
    assert "Nothing on this page reads" in html
    # Not a bare claim: the proof list names the checks that produced it.
    assert "read 1 obligation and ran 1 predicate" in html
    assert "read 1 open digest" in html


def test_not_verified_and_truncated_both_reach_the_unknown_register():
    html = page(owed=owed_envelope(obligation(), checked=False, truncated=True))
    assert "Predicates were not evaluated" in html
    assert "hit its cap" in html


def test_an_empty_digest_store_is_unknown_not_nothing():
    """`ls` returns a list, not an envelope, so empty cannot be told from unread."""
    html = page(sessions=[])
    assert "No digests in the store" in html
    assert "has never run" in html


def test_low_confidence_sessions_are_counted_as_unknown():
    sessions = [session(session=f"s{i}", confidence="low") for i in range(3)]
    html = page(sessions=sessions)
    assert "3 of 3 open sessions are open by default" in html
    # Three, not one. The figure counts rows that read `?`, not entries in the list —
    # one entry standing for forty sessions would report `1` and read as a tidy board.
    assert unknown_count(owed_envelope(), blocked_envelope(), sessions) == 3


# --------------------------------------------------------------------------------
# What it says, and how loudly.
# --------------------------------------------------------------------------------


def test_the_page_says_it_is_a_snapshot_and_when_it_was_made():
    html = page()
    assert "2026-02-01 00:00 UTC" in html
    assert "snapshot" in html
    assert "cannot check anything" in html


def test_the_days_free_figure_leads_the_unblocked_row():
    html = page(blocked=blocked_envelope(blocked_row()))
    assert "Free to proceed for 5 days, and nothing anywhere has said so." in html


def test_every_issue_row_links_to_its_issue():
    html = page(
        owed=owed_envelope(obligation()), blocked=blocked_envelope(blocked_row())
    )
    hrefs = set(re.findall(r'href="([^"]+)"', html))
    assert "https://github.com/acme/widget/issues/7" in hrefs
    assert "https://github.com/acme/widget/issues/109" in hrefs


def test_the_predicate_is_printed_in_full():
    """It is the reason to believe the verdict; a clipped one cannot be checked."""
    long_predicate = "gh api repos/acme/widget " + "--jq .name " * 40
    html = page(owed=owed_envelope(obligation(predicate=long_predicate)))
    assert long_predicate.strip() in html


def test_session_totals_are_stated_even_when_the_register_is_bounded():
    sessions = [session(session=f"s{i}") for i in range(12)]
    html = page(sessions=sessions, max_sessions=4)
    assert "Showing the 4 most recent of 12" in html
    assert html.count("ol show s") == 4


# --------------------------------------------------------------------------------
# Egress. The page is published; it is an export surface.
# --------------------------------------------------------------------------------


def test_a_home_path_in_an_issue_body_is_rewritten_not_printed():
    home = "/Us" + "ers/someone/secret-project"
    html = page(owed=owed_envelope(obligation(evidence=f"failed in {home}/x.py")))
    assert home not in html
    # The identity is dropped and the tail is kept, which is the whole rule.
    assert "~other/secret-project/x.py" in html
    assert scan(html, aliases={}) == []


def test_a_credential_shaped_field_is_withheld_counted_and_never_printed():
    token = "gh" + "p_" + "B" * 36
    html = page(owed=owed_envelope(obligation(evidence=f"token={token}")))
    assert token not in html
    assert "withheld: credential-shaped text (github_token)" in html
    assert "1 field(s) were withheld" in html
    assert scan(html, aliases={}) == []


def test_html_in_a_title_cannot_become_html():
    html = page(owed=owed_envelope(obligation(title="<script>alert(1)</script>")))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_non_http_link_target_is_not_linked():
    html = page(owed=owed_envelope(obligation(url="javascript:alert(1)")))
    assert "javascript:" not in html
    assert 'class="ref">acme/widget#7<' in html


# --------------------------------------------------------------------------------
# The document itself.
# --------------------------------------------------------------------------------


def test_the_page_reaches_nowhere():
    """No stylesheet, no script, no image, no font, no fetch. It has to work offline."""
    html = page(owed=owed_envelope(obligation()), sessions=[session()])
    for forbidden in ("<script", "<link", "<iframe", "@import", "src=", "http://"):
        assert forbidden not in html, forbidden
    # The only external URLs are the GitHub links a reader clicks on purpose.
    assert set(re.findall(r"https?://[^\"'\s]+", html)) <= {
        "https://github.com/acme/widget/issues/7"
    }


def test_both_themes_are_defined_at_token_level():
    html = page()
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ':root:not([data-theme="light"])' in style
    assert ':root[data-theme="dark"]' in style
    assert "body{" in style and "background:var(--ground)" in style
    # Every token the dark blocks define must also exist on bare `:root`, or it has no
    # value in the un-stamped light state — the classic unreadable-artifact bug.
    base = set(re.findall(r"--[a-z-]+(?=:)", style.split("@media", 1)[0]))
    dark = set(re.findall(r"--[a-z-]+(?=:)", style.split('data-theme="dark"', 1)[1]))
    assert dark <= base, dark - base


def test_standalone_wraps_the_document_and_fragment_does_not():
    assert page().startswith("<!doctype html>")
    fragment = page(standalone=False)
    assert not fragment.startswith("<!doctype")
    assert "<html" not in fragment and "<body" not in fragment
    assert fragment.startswith("<title>")


def test_the_title_is_the_page_name():
    assert f"<title>{DFLT_TITLE}</title>" in page()
    assert "<title>Board</title>" in page(title="Board")


def test_the_page_is_byte_stable_for_a_given_moment():
    """`made_at` is the only clock. Two renders of one snapshot are one document."""
    args = dict(owed=owed_envelope(obligation()), sessions=[session()])
    assert page(**args) == page(**args)


def test_every_open_tag_is_closed():
    html = page(
        owed=owed_envelope(obligation(), obligation(number=8, state="discharged")),
        blocked=blocked_envelope(blocked_row(), blocked_row(number=27, state="blocked")),
        sessions=[session(), session(session="b" * 16, confidence="low")],
    )
    body = re.search(r"<main\b.*</main>", html, re.S).group(0)
    void = {"br", "hr", "img", "input", "meta", "link"}
    stack: list[str] = []
    for closing, name in re.findall(r"<(/?)([a-z0-9]+)", body):
        if closing:
            assert stack and stack[-1] == name, f"{name} closed out of order: {stack[-3:]}"
            stack.pop()
        elif name not in void:
            stack.append(name)
    assert stack == [], stack


# --------------------------------------------------------------------------------
# The operation, and the CLI verb over it.
# --------------------------------------------------------------------------------


def test_the_tool_needs_no_network_when_all_three_seams_are_injected():
    result = tools.dashboard(
        owed_report=owed_envelope(obligation()),
        blocked_report=blocked_envelope(blocked_row()),
        sessions=[session()],
        made_at=STAMP,
    )
    assert result["counts"] == {
        "needs_you": 1,
        "free_to_proceed": 1,
        "in_flight": 1,
        # Two figures, not one, and the masthead shows `unchecked`. A `?` on an
        # obligation means the world would not answer; a low-confidence digest means the
        # classifier had nothing to go on. Merging them once reported 42 against a real
        # unchecked count of 1, in the alarming direction.
        "unchecked": 0,
        "low_confidence": 0,
        "unknown": 0,
    }
    assert result["bytes"] == len(result["html"].encode("utf-8"))
    assert result["path"] == ""


def test_the_tool_reports_null_rather_than_zero_for_what_it_could_not_read():
    result = tools.dashboard(
        owed_report=owed_envelope(listed=False, error="no gh"),
        blocked_report=blocked_envelope(),
        sessions=[],
        made_at=STAMP,
    )
    assert result["counts"]["needs_you"] is None
    assert result["counts"]["unknown"] is None


def test_the_tool_writes_where_it_is_told(tmp_path):
    target = tmp_path / "nested" / "board.html"
    result = tools.dashboard(
        owed_report=owed_envelope(obligation()),
        blocked_report=blocked_envelope(),
        sessions=[session()],
        made_at=STAMP,
        path=str(target),
    )
    assert result["path"] == str(target)
    assert target.read_text(encoding="utf-8") == result["html"]
    # The written file is an export surface, and it is scanned like any other.
    assert scan_files([target], aliases={}) == []


def test_the_written_page_opens_as_its_own_document(tmp_path):
    target = tmp_path / "board.html"
    tools.dashboard(
        owed_report=owed_envelope(),
        blocked_report=blocked_envelope(),
        sessions=[],
        made_at=STAMP,
        path=str(target),
    )
    text = target.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in text


def test_the_cli_verb_prints_a_page_and_a_written_summary(tmp_path, monkeypatch):
    from openloops import __main__ as cli

    canned = {
        "html": "<title>x</title>",
        "path": str(tmp_path / "b.html"),
        "bytes": 16,
        "made_at": STAMP,
        "counts": {"needs_you": None, "free_to_proceed": 2, "in_flight": 0, "unknown": None},
    }
    monkeypatch.setattr(tools, "dashboard", lambda **kw: canned)
    assert cli.dashboard() == "<title>x</title>"
    summary = cli.dashboard(out=canned["path"])
    assert "wrote 16 bytes" in summary
    # A `?` survives all the way to the console, the same as in `ol owed`.
    assert "needs_you: ?" in summary and "free_to_proceed: 2" in summary


def test_dashboard_is_on_the_one_dispatch_list():
    """Two surfaces drift apart when there are two lists. There is one."""
    assert tools.dashboard in tools._dispatch_funcs
    from openloops import __main__ as cli

    assert cli.dashboard in cli._commands


@pytest.mark.parametrize("bad", [b"\xff", "—" * 3])
def test_odd_field_values_do_not_break_the_render(bad):
    html = page(owed=owed_envelope(obligation(title=bad, evidence=bad)))
    assert "<title>" in html


def test_the_shipped_module_carries_no_home_path():
    module = Path(__file__).resolve().parent.parent / "openloops" / "dashboard.py"
    assert scan_files([module], aliases={}) == []


def test_the_stylesheet_and_the_sanitizer_are_public_for_sibling_renderers():
    """crowsnest renders a live-session page in this design; a copy would drift.

    The private spellings stay bound to the same objects for one release, so a caller
    that still imports them keeps working while it moves to the public names.
    """
    from openloops import dashboard

    assert dashboard.CSS is dashboard._CSS
    assert dashboard.Sanitizer is dashboard._Sanitizer
    assert {"CSS", "Sanitizer"} <= set(dashboard.__all__)
    # And the public name is the one the page is actually rendered with.
    assert f"<style>{dashboard.CSS}</style>" in page()


# --------------------------------------------------------------------------------
# The shared kit: the markup a sibling renderer builds its page out of. Pinned, because
# a change here is a change to another package's page and nothing there would fail.
# --------------------------------------------------------------------------------


def test_the_register_and_rail_builders_are_public_for_sibling_renderers():
    from openloops import dashboard

    assert {"register", "rail"} <= set(dashboard.__all__)


def test_a_register_is_a_section_whose_head_is_the_figure_then_heading_and_rule():
    assert register(
        ident="needs",
        name="Needs you now",
        figure="2",
        tone="needs",
        rule="Why.",
        body="<ol></ol>",
    ) == (
        '<section class="register register--needs" id="needs">'
        '<div class="register-head">'
        '<p class="figure">2</p>'
        '<div><h2>Needs you now</h2><p class="rule">Why.</p></div>'
        "</div><ol></ol></section>"
    )


def test_a_folding_register_is_a_details_whose_summary_carries_the_same_three_parts():
    """crowsnest folds every register (its #86); the head must stay one shape.

    A ``<summary>`` may hold phrasing content and a heading only, so the figure and the
    rule are spans there rather than the paragraphs the section head uses.
    """
    assert register(
        ident="quiet",
        name="Quiet",
        figure="9",
        tone="flight",
        rule="Why.",
        body="<ol></ol>",
        folds=True,
    ) == (
        '<details class="register register--flight" id="quiet">'
        '<summary class="register-head">'
        '<span class="figure">9</span>'
        "<h2>Quiet</h2>"
        '<span class="rule">Why.</span>'
        "</summary><ol></ol></details>"
    )
    opened = register(
        ident="quiet",
        name="Quiet",
        figure="9",
        tone="flight",
        rule="Why.",
        body="",
        folds=True,
        start_open=True,
    )
    assert opened.startswith(
        '<details class="register register--flight" id="quiet" open>'
    )


def test_extra_heads_the_body_in_the_details_and_the_head_in_the_section():
    """A control belongs above the rows either way -- but never inside a ``<summary>``."""
    control = '<button type="button">Seen above</button>'
    section = register(
        ident="x",
        name="N",
        figure="1",
        tone="needs",
        rule="r",
        body="<ol></ol>",
        extra=control,
    )
    assert f'<p class="rule">r</p>{control}</div></div><ol></ol>' in section
    details = register(
        ident="x",
        name="N",
        figure="1",
        tone="needs",
        rule="r",
        body="<ol></ol>",
        extra=control,
        folds=True,
    )
    assert f"</summary>{control}<ol></ol>" in details
    assert control not in details.split("</summary>")[0]


def test_a_rail_is_the_state_chip_then_the_age_and_an_unknown_age_is_a_question_mark():
    assert rail("open", "flight", 3) == (
        '<div class="rail"><span class="chip chip--flight">open</span>'
        '<span class="age"><b>3</b><i>d</i></span></div>'
    )
    assert "<b>?</b>" in rail("open", "flight", None)
    # Not every sibling page counts in days: the figure may arrive already written.
    assert "<b>40</b><i>s</i>" in rail("said", "needs", "40", "s")


def test_a_rails_extra_chips_sit_between_the_state_and_the_age():
    chip = '<span class="chip chip--reach">phone</span>'
    assert rail("said", "needs", "2", "m", extra=chip) == (
        '<div class="rail"><span class="chip chip--needs">said</span>'
        f'{chip}<span class="age"><b>2</b><i>m</i></span></div>'
    )


def test_the_page_is_built_out_of_the_public_builders(monkeypatch):
    """Not just exported: these very functions write the page this package renders.

    Substring-matching the builders' output would pass against an inline copy emitting
    the same bytes -- which is the drift the shared kit exists to prevent -- so the
    functions are replaced and the page is checked for what the replacements wrote.
    """
    from openloops import dashboard

    # The stub keeps the body, so the rows (and their rails) still reach the page.
    monkeypatch.setattr(
        dashboard, "register", lambda **kw: f"[REGISTER {kw['ident']}]{kw['body']}"
    )
    monkeypatch.setattr(dashboard, "rail", lambda *a, **kw: "[RAIL]")
    html = page(owed=owed_envelope(obligation()))
    assert "[REGISTER needs]" in html
    assert "[RAIL]" in html
    # Every register on the page, not just the first: no band builds its own head.
    for ident in ("needs", "free", "flight", "unknown"):
        assert f"[REGISTER {ident}]" in html, ident
    # And no band wrote a head of its own: the stub is the only builder.
    assert '<section class="register' not in html
