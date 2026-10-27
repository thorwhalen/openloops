"""The board store's rules: events immutable, drafts newest-wins, roles per collection."""

from __future__ import annotations

import pytest

from openloops.board_store import BoardStoreError, get_doc, list_docs, put_doc


def _status(call):
    with pytest.raises(BoardStoreError) as caught:
        call()
    return caught.value.status


def test_an_event_is_created_once_and_an_identical_retry_is_harmless():
    store = {}
    first = put_doc(
        store, "outbox", "20261027-a", {"action": "done", "n": 1}, role="viewer"
    )
    again = put_doc(
        store, "outbox", "20261027-a", {"n": 1, "action": "done"}, role="viewer"
    )
    assert first["created"] and not again["created"]
    assert first["version"] == again["version"], "key order does not change an event"
    assert (
        _status(
            lambda: put_doc(
                store, "outbox", "20261027-a", {"action": "undo"}, role="viewer"
            )
        )
        == 409
    )
    # Not even the receiver, nor a version pin, can rewrite an event.
    assert (
        _status(
            lambda: put_doc(
                store,
                "outbox",
                "20261027-a",
                {"x": 1},
                role="receiver",
                if_match=first["version"],
            )
        )
        == 409
    )


def test_each_collection_has_its_own_writers():
    store = {}
    for collection in ("receipts", "meta", "questions", "state", "answers"):
        assert (
            _status(lambda: put_doc(store, collection, "x", {}, role="viewer")) == 403
        )
        assert put_doc(store, collection, "x", {}, role="receiver")["created"]
    assert put_doc(store, "drafts", "x", {"at": "1"}, role="receiver")["created"]
    assert _status(lambda: put_doc(store, "outbox", "x", {}, role="stranger")) == 403


def test_an_older_draft_never_overwrites_a_newer_one():
    store = {}
    put_doc(
        store,
        "drafts",
        "k",
        {"text": "new", "at": "2026-10-27T10:00:00Z"},
        role="viewer",
    )
    stale = put_doc(
        store,
        "drafts",
        "k",
        {"text": "old", "at": "2026-10-27T09:00:00Z"},
        role="viewer",
    )
    assert (
        not stale["created"] and get_doc(store, "drafts", "k")["data"]["text"] == "new"
    )
    put_doc(
        store,
        "drafts",
        "k",
        {"text": "newer", "at": "2026-10-27T11:00:00Z"},
        role="viewer",
    )
    assert get_doc(store, "drafts", "k")["data"]["text"] == "newer"


def test_version_pins_and_create_if_absent():
    store = {}
    made = put_doc(
        store,
        "receipts",
        "e1",
        {"status": "processing"},
        role="receiver",
        if_none_match=True,
    )
    assert (
        _status(
            lambda: put_doc(
                store,
                "receipts",
                "e1",
                {"status": "x"},
                role="receiver",
                if_none_match=True,
            )
        )
        == 412
    )
    assert (
        _status(
            lambda: put_doc(
                store,
                "receipts",
                "e1",
                {"status": "x"},
                role="receiver",
                if_match="0" * 16,
            )
        )
        == 412
    )
    done = put_doc(
        store,
        "receipts",
        "e1",
        {"status": "posted"},
        role="receiver",
        if_match=made["version"],
    )
    assert get_doc(store, "receipts", "e1")["version"] == done["version"]


@pytest.mark.parametrize("doc_id", ["../etc", "a/b", "", ".hidden", "x" * 201, "a b"])
def test_ids_that_could_escape_their_collection_are_refused(doc_id):
    assert _status(lambda: put_doc({}, "outbox", doc_id, {}, role="viewer")) == 400


def test_unknown_collections_bad_bodies_and_oversize_documents():
    assert _status(lambda: list_docs({}, "secrets")) == 404
    assert (
        _status(
            lambda: put_doc({}, "outbox", "e", ["not", "an", "object"], role="viewer")
        )
        == 400
    )
    assert (
        _status(
            lambda: put_doc(
                {}, "outbox", "e", {"t": "x" * 100}, role="viewer", max_bytes=50
            )
        )
        == 413
    )
    assert _status(lambda: get_doc({}, "outbox", "missing")) == 404


def test_listing_reads_only_its_own_collection_and_accepts_bytes_values():
    store = {
        "outbox/b.json": b'{"n":2}',
        "outbox/a.json": '{"n":1}',
        "drafts/a.json": "{}",
        "outbox/x.txt": "{}",
    }
    assert [(d["id"], d["data"]) for d in list_docs(store, "outbox")["docs"]] == [
        ("a", {"n": 1}),
        ("b", {"n": 2}),
    ]
