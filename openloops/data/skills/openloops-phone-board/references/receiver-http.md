# The receiver over HTTP (a self-hosted board)

[receiver.md](receiver.md) is the procedure; every rule in it holds unchanged. This file replaces only its store calls: where it says `list`, `get` or `set` through `ArtifactData`, a self-hosted board uses the board store API (`openloops.board_store`) with `curl`.

## Credentials: the receiver's own account, never printed

The receiver signs in as **its own account** (not the owner's), which the server maps to the role `receiver`. That role may write `receipts`, `meta`, `questions` and import `outbox`/`drafts`; the owner's browser login is `viewer` and may write only `outbox` (create-only) and `drafts`.

- Keep the account's credentials in a file only the receiving session's user can read (`chmod 600`), for example `~/.config/openloops/board-receiver.env` with `BOARD_ORIGIN`, `BOARD_API` (the store's path, e.g. `/api/openloops/store`), `BOARD_EMAIL`, `BOARD_PASSWORD`. Never commit it, never paste it into a prompt, an issue or the store, and never let a command print it: no `set -x`, no `echo`, no `curl -v`.
- Keep the session's cookies in a cookie jar with the same permissions (`~/.config/openloops/board-receiver.cookies`). Sign in only when a call answers 401.

Signing in depends on the platform. For an enlace_auth server (`thorwhalen.com`-style): fetch a CSRF token, then post the credentials built from the env file without echoing them:

```bash
set +x; umask 077
. ~/.config/openloops/board-receiver.env
J=~/.config/openloops/board-receiver.cookies
CSRF=$(curl -sS -c "$J" -b "$J" "$BOARD_ORIGIN/auth/csrf" | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf"])')
python3 -c 'import json,os; print(json.dumps({"email": os.environ["BOARD_EMAIL"], "password": os.environ["BOARD_PASSWORD"]}))' \
  | curl -sS -o /dev/null -w '%{http_code}\n' -c "$J" -b "$J" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' --data @- "$BOARD_ORIGIN/auth/login"
```

The env file must `export` `BOARD_EMAIL` and `BOARD_PASSWORD` so the `python3 -c` sees them. A `200` means signed in (enlace_auth sessions last weeks); on another platform, use its own sign-in.

## The calls

With `S="$BOARD_ORIGIN$BOARD_API"` and `C=(-sS -b "$J" -c "$J" -H 'Content-Type: application/json')`:

| receiver.md says | HTTP |
|---|---|
| list a collection (`outbox`, `receipts`, `drafts`, `meta`, `questions`) | `curl "${C[@]}" "$S/outbox"` → `{"docs": [{"id", "data", "version"}]}`. Save each response into the sweep's backup directory. There is no paging: one listing is the whole collection (capped at 5000 documents; a 507 means the board has outgrown this store). |
| get one document | `curl "${C[@]}" "$S/receipts/<id>"` → `{"id", "data", "version"}`, or 404 |
| set, create-if-absent (a claim with no receipt yet) | `curl "${C[@]}" -X PUT -H 'If-None-Match: *' --data @body.json "$S/receipts/<id>"`; **412** means another sweep holds it: skip |
| set, pinned to a version (a claim on an existing receipt, the finish, the heartbeat) | `curl "${C[@]}" -X PUT -H 'If-Match: <version>' --data @body.json "$S/receipts/<id>"`; **412** is a pin conflict: re-read, as receiver.md says |

Always write the body to a file and send it with `--data @file`; never interpolate store text into a command line. A 401 means sign in again and retry once; a 403 means the account lacks the `receiver` role, so stop and tell the owner; 409 on `outbox` means an event with that id already exists with different content (events never change).

`meta/receiver` is the heartbeat and `meta/schema` the page schema, exactly as on an Artifact board.
