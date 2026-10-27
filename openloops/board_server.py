"""An optional web app for a self-hosted phone board: the page, its files, its store API.

``pip install openloops[server]`` adds FastAPI; nothing else in openloops imports this
module, so the core still never reaches the network. :func:`mk_app` returns a FastAPI
app with two route groups:

- ``GET /board/`` and ``GET /board/{file}``: the board directory written by
  ``ol board-build --store http --api <prefix>/board-store`` (``index.html``, ``tasks.json``,
  ``runs.json``, ``board.json``, ``kit.html``, nothing else).
- ``/board-store/...``: the board store API of :mod:`openloops.board_store`. Not
  ``/store``: a host may already own that path (enlace_auth mounts its own per-user
  store at ``/api/<app>/store``), and the page sends no CSRF token, so the API must sit
  where the host exempts an app's own routes from CSRF.

**It does not authenticate anyone.** It asks ``role_of(request)`` for ``"viewer"`` (the
owner's browser) or ``"receiver"`` (the receiving session) and refuses every request,
reads included, for which it gets anything else. Put it behind your platform's login
and derive the role from the identity that login established, never from anything the
client sends. The board's task titles come from private repositories.

**Imports** (moving a board here, see the skill's ``migrate.md``) are possible only
while a file named ``.import-open`` exists in ``store_root``: create it on the server
for the migration, delete it after. The receiver's credentials cannot open it.

    app = mk_app(
        board_dir="~/.local/share/openloops/board",
        store_root="~/.local/share/openloops/board-store",
        role_of=lambda request: "viewer" if request.state.user_email == OWNER else None,
    )
"""

import contextlib
import hashlib
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from openloops.board import BOARD_FILES
from openloops.board_store import (
    COLLECTIONS,
    DFLT_MAX_BYTES,
    ROLES,
    BoardStoreError,
    get_doc,
    list_docs,
    parse_body,
    put_doc,
)
from openloops.store import board_docs_store

__all__ = ["IMPORT_FLAG", "file_lock", "mk_app"]

#: Private and changing: never cached by a browser or a proxy.
NO_STORE = {"Cache-Control": "no-store"}
#: Its presence in the store root allows imports; see the module docstring.
IMPORT_FLAG = ".import-open"
_LOCK_NAME = ".lock"
_PROCESS_LOCK = threading.Lock()


@contextlib.contextmanager
def file_lock(path: str | Path, *, shared: bool = False) -> Iterator[None]:
    """A lock on ``path`` across processes (POSIX ``flock``): shared to read, else exclusive.

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
        fcntl.flock(handle, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _etag(text: str) -> str:
    return '"' + hashlib.sha256(text.encode()).hexdigest()[:16] + '"'


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
    from starlette.concurrency import run_in_threadpool

    board = Path(board_dir).expanduser()
    root = Path(store_root).expanduser()
    store = board_docs_store(root)
    lock_path = root / _LOCK_NAME
    # Interactive API docs would answer without a role: off.
    app = FastAPI(title=title, docs_url=None, redoc_url=None, openapi_url=None)
    # Every poll lists every collection; re-reading every file each time is the cost
    # that grows. A listing is reused until its collection's generation changes: a
    # counter in a dotfile that every write raises inside the exclusive lock, so every
    # worker sees it (a directory mtime would not do: coarse kernel clocks can give two
    # writes one stamp).
    listings: dict[str, tuple[Any, dict, str]] = {}

    def require_role(request: Request) -> str:
        role = role_of(request)
        if role not in ROLES:
            raise HTTPException(403, "not allowed on this board")
        return role

    def refused(exc: BoardStoreError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.message}, status_code=exc.status, headers=NO_STORE
        )

    def generation(collection: str) -> str:
        try:
            return (root / f".gen-{collection}").read_text(encoding="utf-8")
        except FileNotFoundError:
            return "0"

    def bump(collection: str) -> None:
        path = root / f".gen-{collection}"
        store_tmp = path.with_name(path.name + ".tmp")
        store_tmp.write_text(
            str(int(generation(collection) or 0) + 1), encoding="utf-8"
        )
        store_tmp.replace(path)

    def listing_of(collection: str) -> tuple[dict, str]:
        if collection not in COLLECTIONS:
            raise BoardStoreError(404, f"no collection {collection!r}")
        with file_lock(lock_path, shared=True):
            now = generation(collection)
            cached = listings.get(collection)
            if cached and cached[0] == now:
                return cached[1], cached[2]
            listing = list_docs(store, collection)
        tag = _etag("".join(d["id"] + d["version"] for d in listing["docs"]))
        listings[collection] = (now, listing, tag)
        return listing, tag

    def write(collection, doc_id, data, role, if_match, if_none_match):
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
                allow_import=(root / IMPORT_FLAG).exists(),
            )
            bump(collection)
            return result

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

    @app.get("/board-store/{collection}")
    def store_list(collection: str, request: Request):
        require_role(request)
        try:
            listing, tag = listing_of(collection)
        except BoardStoreError as exc:
            return refused(exc)
        # A compressing proxy may weaken the tag to W/"..."; it still names this listing.
        sent = (request.headers.get("if-none-match") or "").removeprefix("W/")
        if sent == tag:
            return Response(status_code=304, headers={**NO_STORE, "ETag": tag})
        return JSONResponse(listing, headers={**NO_STORE, "ETag": tag})

    @app.get("/board-store/{collection}/{doc_id}")
    def store_get(collection: str, doc_id: str, request: Request):
        require_role(request)
        try:
            with file_lock(lock_path, shared=True):
                doc = get_doc(store, collection, doc_id)
        except BoardStoreError as exc:
            return refused(exc)
        return JSONResponse(doc, headers={**NO_STORE, "ETag": f'"{doc["version"]}"'})

    @app.put("/board-store/{collection}/{doc_id}")
    async def store_put(collection: str, doc_id: str, request: Request):
        role = require_role(request)
        raw = await request.body()
        try:
            if len(raw) > max_bytes:
                raise BoardStoreError(413, f"body is larger than {max_bytes} bytes")
            data = parse_body(raw)
            if_match = (request.headers.get("if-match") or "").removeprefix("W/").strip(
                '"'
            ) or None
            if_none_match = request.headers.get("if-none-match") == "*"
            # flock blocks: run it off the event loop so one slow write stalls no one.
            result = await run_in_threadpool(
                write, collection, doc_id, data, role, if_match, if_none_match
            )
        except BoardStoreError as exc:
            return refused(exc)
        return JSONResponse(result, headers=NO_STORE)

    return app
