# Moving a board from a claude.ai Artifact to a self-hosted server

Goal: nothing the owner entered is lost, and no tap lands in a store nobody reads any more. The Artifact's store is the source of truth until the cut-over.

1. **Stand up the new board** (SKILL.md, 4b): build with `--store http --api <prefix>/store`, copy the files to the server, and check, signed in as the owner, that the page loads and that an anonymous request for the page, `tasks.json` and the store all get refused.
2. **Freeze the old board.** The session that owns the Artifact rebuilds it with `ol board-build ... --moved-to <new board URL>` (same records, same Artifact) and republishes it. From then on the old page takes no new taps; a phone that still holds unsaved taps keeps flushing them to the old store.
3. **Final sweep.** That session runs one last receiver sweep on the old store, so every event there has a receipt (or a deliberate `queued`/`failed`).
4. **Export** with `ArtifactData` `list` (`query.limit: 1000`, following `next_cursor`) for `outbox`, `receipts`, `drafts`, `meta`, `questions` (and `state`, `answers` if the board is that old), saving into a dated backup directory. Keep it: it is the rollback.
5. **Import** as the receiver account (receiver-http.md), one `PUT` per document, the body being the document's data exactly as exported:
   - `outbox`: create-only; an identical document already there answers 200, a different one 409 (stop and look: two events with one id is a bug somewhere).
   - `receipts`, `meta`, `questions`, `state`, `answers`, `drafts`: plain `PUT`.
   - Then list each collection on the new store and compare the counts and ids with the export. Any difference: stop, fix, re-import (every step is idempotent).
6. **Cut over the receiver**: the receiver's cron now runs receiver.md against the new store, and stops reading the old one. Tell the owner the new link.
7. **Late taps**: for a week, check the old store for events newer than the export (a phone that was offline during step 2). Import any you find, then process them on the new board.
