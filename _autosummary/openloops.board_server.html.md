# openloops.board_server

An optional web app for a self-hosted phone board: the page, its files, its store API.

`pip install openloops[server]` adds FastAPI; nothing else in openloops imports this
module, so the core still never reaches the network. [`mk_app()`](#openloops.board_server.mk_app) returns a FastAPI
app with two route groups:

- `GET /board/` and `GET /board/{file}`: the board directory written by
  `ol board-build --store http --api <prefix>/board-store` (`index.html`, `tasks.json`,
  `runs.json`, `board.json`, `kit.html`, nothing else).
- `/board-store/...`: the board store API of [`openloops.board_store`](openloops.board_store.html.md#module-openloops.board_store). Not
  `/store`: a host may already own that path (enlace_auth mounts its own per-user
  store at `/api/<app>/store`), and the page sends no CSRF token, so the API must sit
  where the host exempts an app’s own routes from CSRF.

**It does not authenticate anyone.** It asks `role_of(request)` for `"viewer"` (the
owner’s browser) or `"receiver"` (the receiving session) and refuses every request,
reads included, for which it gets anything else. Put it behind your platform’s login
and derive the role from the identity that login established, never from anything the
client sends. The board’s task titles come from private repositories.

**Imports** (moving a board here, see the skill’s `migrate.md`) are possible only
while a file named `.import-open` exists in `store_root`: create it on the server
for the migration, delete it after. The receiver’s credentials cannot open it.

> app = mk_app(
> : board_dir=”~/.local/share/openloops/board”,
>   store_root=”~/.local/share/openloops/board-store”,
>   role_of=lambda request: “viewer” if request.state.user_email == OWNER else None,

> )

### Module Attributes

| [`IMPORT_FLAG`](#openloops.board_server.IMPORT_FLAG)   | Its presence in the store root allows imports; see the module docstring.   |
|----------------------------------------------------------------|----------------------------------------------------------------------------|

### Functions

| [`file_lock`](#openloops.board_server.file_lock)(path, \*[, shared])                     | A lock on `path` across processes (POSIX `flock`): shared to read, else exclusive.   |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`mk_app`](#openloops.board_server.mk_app)(\*, board_dir, store_root, role_of[, ...]) | The board's FastAPI app.                                                             |

### openloops.board_server.IMPORT_FLAG *= '.import-open'*

Its presence in the store root allows imports; see the module docstring.

### openloops.board_server.file_lock(path, , shared=False)

A lock on `path` across processes (POSIX `flock`): shared to read, else exclusive.

A web server usually runs several worker processes; without this, two of them can
both see an event as absent and both “create” it. Where `fcntl` is missing the
lock is process-local only, which is right for a single-process server.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

### openloops.board_server.mk_app(, board_dir, store_root, role_of, max_bytes=65536, title='openloops board')

The board’s FastAPI app. `role_of` is the only authorisation it has.
