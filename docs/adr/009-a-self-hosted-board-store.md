---
status: accepted
date: 2026-10-27
---

# ADR-009 — A self-hosted board: one store seam in the page, the rules in openloops, authentication in the host

## Context

The phone board (ADR-008) keeps its state in the claude.ai Artifact `db` store. Owners also want it on their own website. That needs three things the Artifact gave for free: a document store, a login, and a way for the receiving session to reach the store.

## Decision

- **One store seam, in the page.** The page uses exactly two calls from its store, `doc(path).set(body)` and `collection(name).onSnapshot(...)`. `board.json` `store: {kind: "http", api}` swaps the Artifact store for `httpStore`, which speaks the **board store API** (`GET`/`PUT` on `<api>/<collection>[/<id>]`, `If-Match`/`If-None-Match: *`, conditional polling by ETag) on the page's own origin with the viewer's own cookie. Error codes map onto the Artifact store's, so nothing else in the page changed. `ol board-build --store http --api <base>` builds such a page; `--moved-to URL` builds the forwarding notice used to cut an Artifact board over.
- **The rules live in openloops, network-free.** `openloops.board_store` enforces the page's persistence model over any `MutableMapping`: events immutable (identical retry is a no-op, anything else 409), drafts newest-wins, and per-collection writers by role (`viewer`, the owner's browser: `outbox`, `drafts`; `receiver`, the receiving session: everything else, plus importing). Any server that hosts a board enforces the same rules by calling it.
- **An optional web app, not a core module.** `openloops.board_server.mk_app` (extra `openloops[server]`, FastAPI) serves the board files and the store API. It authenticates nobody: the host's login does, and `role_of(request)` maps the identity that login established to a role. Requests with no role, reads included, are refused, because the task titles come from private repositories.
- **The receiver is its own account.** Where a platform has no API tokens, the receiving session signs in as a dedicated account mapped to `receiver`, rather than as the owner, so the owner's browser can never write receipts and the receiver can never hold the owner's password.

## Consequences

- `import openloops` still never reaches the network; FastAPI is needed only by whoever runs `board_server`.
- A host platform needs no openloops-specific auth: a login that can tell the owner from the receiver account is enough.
- Polling replaces the Artifact's live snapshots (a few seconds' delay; a 304 when nothing changed).
- The board's data (built files, store) lives in the host's data directory, never in an app's code directory or a repository.
