"""An optional web app for a self-hosted phone board: the page, its files, its store API.

``pip install openloops[server]`` adds FastAPI; nothing else in openloops imports this
module, so the core still never reaches the network. :func:`mk_app` returns a FastAPI
app with two route groups:

- ``GET /board/`` and ``GET /board/{file}``: the board directory written by
  ``ol board-build --store http --api <prefix>/store`` (``index.html``, ``tasks.json``,
  ``runs.json``, ``board.json``, ``kit.html``, nothing else).
- ``/store/...``: the board store API of :mod:`openloops.board_store`.

**It does not authenticate anyone.** It asks ``role_of(request)`` for ``"viewer"`` (the
owner's browser) or ``"receiver"`` (the receiving session) and refuses every request,
reads included, for which it gets anything else. Put it behind your platform's login
and derive the role from the identity that login established, never from anything the
client sends. The board's task titles come from private repositories.

    app = mk_app(
        board_dir="~/.local/share/openloops/board",
        store_root="~/.local/share/openloops/board-store",
        role_of=lambda request: "viewer" if request.state.user_email == OWNER else None,
    )
"""

import contextlib
import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from openloops.board import BOARD_FILES
from openloops.board_store import (
    DFLT_MAX_BYTES,
    ROLES,
    BoardStoreError,
    get_doc,
    list_docs,
    put_doc,
)
from openloops.store import board_docs_store

__all__ = ["file_lock", "mk_app"]

#: Private and changing: never cached by a browser or a proxy.
NO_STORE = {"Cache-Control": "no-store"}
_LOCK_NAME = ".lock"


@contextlib.contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    """An exclusive lock on ``path`` across processes (POSIX ``flock``).

    A web server usually runs several worker processes; without this, two of them can
    both see an event as absent and both "create" it. Where ``fcntl`` is missing the
    lock is process-local only, which is right for a single-process server.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        with _PROCESS_LOCK:
            yield
        return
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


_PROCESS_LOCK = threading.Lock()


def mk_app(
    *,
    board_dir: str | Path,
    store_root: str | Path,
    role_of: Callable[[Any], str | None],
    max_bytes: int = DFLT_MAX_BYTES,
    title: str = "openloops board",
):
    """The board's FastAPI app. ``role_of`` is the only authorisation it has."""
    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

    board = Path(board_dir).expanduser()
    root = Path(store_root).expanduser()
    store = board_docs_store(root)
    lock_path = root / _LOCK_NAME
    app = FastAPI(title=title)

    def require_role(request: Request) -> str:
        role = role_of(request)
        if role not in ROLES:
            raise HTTPException(403, "not allowed on this board")
        return role

    def refused(exc: BoardStoreError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.message}, status_code=exc.status, headers=NO_STORE
        )

    @app.get("/board")
    def board_redirect(request: Request):
        require_role(request)
        # Relative, so it stays right under whatever prefix the app is mounted at.
        return RedirectResponse("board/", status_code=307)

    @app.get("/board/")
    def board_index(request: Request):
        return board_file("index.html", request)

    @app.get("/board/{name}")
    def board_file(name: str, request: Request):
        require_role(request)
        path = board / name
        if name not in BOARD_FILES or not path.is_file():
            raise HTTPException(404, "no such board file")
        return FileResponse(path, headers=NO_STORE)

    @app.get("/store/{collection}")
    def store_list(collection: str, request: Request):
        require_role(request)
        try:
            with file_lock(lock_path):
                listing = list_docs(store, collection)
        except BoardStoreError as exc:
            return refused(exc)
        tag = (
            '"'
            + hashlib.sha256(
                "".join(d["id"] + d["version"] for d in listing["docs"]).encode()
            ).hexdigest()[:16]
            + '"'
        )
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={**NO_STORE, "ETag": tag})
        return JSONResponse(listing, headers={**NO_STORE, "ETag": tag})

    @app.get("/store/{collection}/{doc_id}")
    def store_get(collection: str, doc_id: str, request: Request):
        require_role(request)
        try:
            with file_lock(lock_path):
                doc = get_doc(store, collection, doc_id)
        except BoardStoreError as exc:
            return refused(exc)
        return JSONResponse(doc, headers={**NO_STORE, "ETag": f'"{doc["version"]}"'})

    @app.put("/store/{collection}/{doc_id}")
    async def store_put(collection: str, doc_id: str, request: Request):
        role = require_role(request)
        raw = await request.body()
        if len(raw) > max_bytes:
            return refused(
                BoardStoreError(413, f"body is larger than {max_bytes} bytes")
            )
        try:
            data = json.loads(raw or b"null")
        except ValueError:
            return refused(BoardStoreError(400, "body is not JSON"))
        if_match = (request.headers.get("if-match") or "").strip('"') or None
        if_none_match = request.headers.get("if-none-match") == "*"
        try:
            with file_lock(lock_path):
                result = put_doc(
                    store,
                    collection,
                    doc_id,
                    data,
                    role=role,
                    if_match=if_match,
                    if_none_match=if_none_match,
                    max_bytes=max_bytes,
                )
        except BoardStoreError as exc:
            return refused(exc)
        return JSONResponse(result, headers=NO_STORE)

    return app
