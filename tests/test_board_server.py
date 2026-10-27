"""The self-hosted board app: roles gate everything, the store rules hold over HTTP."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from openloops import board  # noqa: E402
from openloops.board_server import mk_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    board.build_board(
        [{"id": "a/b#1", "url": "https://github.com/a/b/issues/1"}],
        tmp_path / "board",
        store="http",
        api="board-store",
    )

    def role_of(request):
        # A test stand-in for the platform's login: real servers derive this from the
        # authenticated identity, never from a header the client controls.
        return {"owner": "viewer", "agent": "receiver"}.get(
            request.headers.get("x-test-who")
        )

    app = mk_app(
        board_dir=tmp_path / "board", store_root=tmp_path / "store", role_of=role_of
    )
    return TestClient(app)


OWNER, AGENT, NOBODY = {"x-test-who": "owner"}, {"x-test-who": "agent"}, {}


def test_nothing_is_served_without_a_role(client):
    for path in (
        "/board/",
        "/board/tasks.json",
        "/board-store/outbox",
        "/board-store/outbox/e1",
    ):
        assert client.get(path, headers=NOBODY).status_code == 403
    assert (
        client.put("/board-store/outbox/e1", json={"a": 1}, headers=NOBODY).status_code
        == 403
    )


def test_the_board_files_and_only_those(client):
    assert client.get("/board/", headers=OWNER).text.startswith("<title>")
    tasks = client.get("/board/tasks.json", headers=OWNER)
    assert tasks.json()[0]["id"] == "a/b#1"
    assert tasks.headers["cache-control"] == "no-store"
    assert client.get("/board/board.json", headers=OWNER).json()["store"] == {
        "kind": "http",
        "api": "board-store",
    }
    for name in ("../store/.lock", "secret.txt", "%2e%2e%2fboard.json"):
        assert client.get(f"/board/{name}", headers=OWNER).status_code == 404


def test_events_are_immutable_and_receipts_belong_to_the_receiver(client):
    assert client.put(
        "/board-store/outbox/e1", json={"action": "done"}, headers=OWNER
    ).json()["created"]
    assert (
        client.put(
            "/board-store/outbox/e1", json={"action": "done"}, headers=OWNER
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/board-store/outbox/e1", json={"action": "undo"}, headers=OWNER
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/board-store/receipts/e1", json={"status": "posted"}, headers=OWNER
        ).status_code
        == 403
    )
    made = client.put(
        "/board-store/receipts/e1",
        json={"status": "processing"},
        headers={**AGENT, "If-None-Match": "*"},
    )
    assert made.status_code == 200
    stale = client.put(
        "/board-store/receipts/e1",
        json={"status": "x"},
        headers={**AGENT, "If-Match": '"0000000000000000"'},
    )
    assert stale.status_code == 412
    pinned = client.put(
        "/board-store/receipts/e1",
        json={"status": "posted"},
        headers={**AGENT, "If-Match": made.json()["version"]},
    )
    assert pinned.status_code == 200


def test_listing_supports_a_conditional_poll(client):
    client.put("/board-store/outbox/e1", json={"action": "done"}, headers=OWNER)
    first = client.get("/board-store/outbox", headers=OWNER)
    assert [d["id"] for d in first.json()["docs"]] == ["e1"]
    again = client.get(
        "/board-store/outbox", headers={**OWNER, "If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
    client.put("/board-store/outbox/e2", json={"action": "skip"}, headers=OWNER)
    assert (
        client.get(
            "/board-store/outbox",
            headers={**OWNER, "If-None-Match": first.headers["etag"]},
        ).status_code
        == 200
    )


def test_bad_bodies_ids_and_collections_are_refused(client):
    assert (
        client.put(
            "/board-store/outbox/e1", content=b"{nope", headers=OWNER
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/board-store/outbox/e1", content=b"x" * 70000, headers=OWNER
        ).status_code
        == 413
    )
    assert client.put("/board-store/outbox/..", json={}, headers=OWNER).status_code in (
        400,
        404,
    )
    assert client.get("/board-store/secrets", headers=OWNER).status_code == 404


def test_api_docs_are_not_served(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=NOBODY).status_code == 404


def test_imports_need_the_flag_file_on_the_server(client, tmp_path):
    body = {"action": "done"}
    assert (
        client.put("/board-store/outbox/old1", json=body, headers=AGENT).status_code
        == 403
    )
    (tmp_path / "store" / ".import-open").write_text("")
    assert (
        client.put("/board-store/outbox/old1", json=body, headers=AGENT).status_code
        == 200
    )
    (tmp_path / "store" / ".import-open").unlink()
    assert (
        client.put("/board-store/outbox/old2", json=body, headers=AGENT).status_code
        == 403
    )


def test_nan_bodies_never_reach_the_store(client):
    bad = client.put("/board-store/outbox/e1", content=b'{"x": NaN}', headers=OWNER)
    assert bad.status_code == 400
    assert client.get("/board-store/outbox", headers=OWNER).json()["docs"] == []


def test_a_weakened_etag_still_gets_a_304(client):
    client.put("/board-store/outbox/e1", json={"a": 1}, headers=OWNER)
    tag = client.get("/board-store/outbox", headers=OWNER).headers["etag"]
    assert (
        client.get(
            "/board-store/outbox", headers={**OWNER, "If-None-Match": "W/" + tag}
        ).status_code
        == 304
    )


def test_a_write_by_another_worker_invalidates_the_cached_listing(client, tmp_path):
    from openloops.board_store import put_doc
    from openloops.store import board_docs_store

    client.put("/board-store/outbox/e1", json={"a": 1}, headers=OWNER)
    assert len(client.get("/board-store/outbox", headers=OWNER).json()["docs"]) == 1
    # Another process writes straight to the store and raises the generation, as the
    # app's own write path does; the cached listing must not survive it.
    put_doc(
        board_docs_store(tmp_path / "store"), "outbox", "e2", {"a": 2}, role="viewer"
    )
    gen = tmp_path / "store" / ".gen-outbox"
    gen.write_text(str(int(gen.read_text()) + 1))
    assert len(client.get("/board-store/outbox", headers=OWNER).json()["docs"]) == 2
