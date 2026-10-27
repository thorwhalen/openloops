# Moving a board from a claude.ai Artifact to a self-hosted server

Goal: nothing the owner entered is lost, and no tap lands in a store nobody reads any more. The Artifact's store is the source of truth until the cut-over.

1. **Stand up the new board, unannounced** (SKILL.md, 4b): build with `--store http --api <prefix>/board-store`, copy the files to the server, and check **anonymously only** that the page, `tasks.json` and the store API are all refused. Do not have the owner open it yet: until the import, every task there shows as to-do, and a tap would create a second event for something already done.
2. **Freeze the old board.** The session that owns the Artifact rebuilds it with `ol board-build ... --moved-to <new board URL>` (same records, same Artifact) and republishes it. From then on the old page takes no new taps and saves no drafts; a phone that still holds unsaved taps keeps flushing them to the old store.
3. **Final sweep.** That session runs one last receiver sweep on the old store, so every event there has a receipt (or a deliberate `queued`/`failed`).
4. **Export** with `ArtifactData` `list` (`query.limit: 1000`, following `next_cursor`) for `outbox`, `receipts`, `drafts`, `meta`, `questions` (and `state`, `answers` if the board is that old), saving into a dated backup directory. Keep it: it is the rollback.
5. **Open the import** on the server: create the empty file `.import-open` in the board store's root (on the host, with shell access; the receiver's credentials cannot do it). While it exists, the receiver account may create `outbox` events and write `drafts`.
6. **Import** as the receiver account (receiver-http.md), one `PUT` per document, the body being the document's data exactly as exported:
   - `outbox`: create-only; an identical document already there answers 200, a different one 409 (stop and look: two events with one id is a bug somewhere).
   - `receipts`, `meta`, `questions`, `state`, `answers`, `drafts`: plain `PUT`.
   - Then list each collection on the new store and compare the counts and ids with the export. Any difference: stop, fix, re-import (every step is idempotent).
7. **Close the import**: delete `.import-open`. Check that a receiver `PUT` to `outbox` now answers 403.
8. **Cut over the receiver**: the receiver's cron now runs receiver.md against the new store, and stops reading the old one. Now tell the owner the new link, and have them sign in and check that their answers and done items are there.
9. **Late taps**: keep checking the old store for events newer than the export (a phone that was offline during step 2) until it has been quiet for two weeks *and* the owner confirms no device still has the old page open. Each late event is imported the same way (steps 5 to 7) and then processed on the new board.
