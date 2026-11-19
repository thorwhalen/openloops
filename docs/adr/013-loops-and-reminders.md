---
status: accepted
date: 2026-11-19
---

# ADR-013 — Loops: one record per commitment, and reminders that a channel holds

## Context

The owner wants to tell an agent "remind me of X in Y" and, later, "remind me of X when Y happens", and wants the fleet's organisation to follow Getting Things Done (David Allen) by default. "Open loop" is Allen's own term. Until now openloops only *found* loops: what sessions left open, what the owner owes, what is blocked. It kept no record of its own and wrote nothing but digests and board files.

The research behind this decision (prior reminder research in the equerry repository, a channels survey, a GTD survey) and an independent review of the first proposal settled four things:

- **The store is the source of truth; a push service is a pipe.** Fire-and-forget scheduling cannot evaluate conditions, cancel itself when the thing is done, escalate across channels, or put everything on one list.
- **A sleeping laptop must not mean a silent miss.** ntfy accepts a message scheduled up to three days ahead, replaces it when one with the same sequence id is published, and deletes it on `DELETE /<topic>/<sequence_id>`. A reminder handed to ntfy fires whatever the laptop is doing.
- **One lifecycle vocabulary.** equerry's desk `Item` already uses A2A's seven state names, and issue #42 asks `Task` to adopt them. A loop uses them too, so it is a desk item without translation. The GTD list is a separate field.
- **The core stays free of the channel.** openloops depends on `dol` and `cw` only, and crowsnest, astern and the desk import it. The reminder engine must not make openloops import correspond, acquaint or crowsnest.

## Decision

1. **`openloops.loops`** is the record and the evaluator, and it is pure. `Loop` carries:
   - `state`: A2A.
   - `list`: `in`, `next`, `waiting`, `someday` or `reference`.
   - Three times, never conflated: `remind_at` (the tickler, GTD's defer date), `due` (a deadline) and `created`.
   - Provenance: `source`, and `proposed_by` (a proposal is never pushed).
   - `reveal`, whether a push may carry the title.
   - `armed`, the delivery the channel holds.
   - The rest of a GTD-complete record (`project`, `contexts`, `energy`, `minutes`, `waiting`, `available_when`, `done_when`, `carried`).
   - An append-only `log`.

   `evaluate(loops, now, horizon=)` returns actions as data: `arm`, `deliver`, `woke` and `disarm`. It reads no clock, file or network.
2. **`openloops.remind`** is the runner, and nothing in the core imports it. It composes three seams, each one keyword argument with a working default:
   - `store`: JSON files under `~/.local/share/openloops/loops/`.
   - `deliver`: correspond's ntfy channel, imported on use, from the `openloops[remind]` extra.
   - `settings`: from the environment.

   A loop due within 72 h is armed at once as a scheduled ntfy message whose sequence id is the loop id. `done` cancels it, `snooze` replaces it under the same id, and an hourly tick (`ol remind-tick`, `ol install-remind-job`) arms what enters the horizon, records what fired, and delivers late, saying so, whatever was never armed.
3. **Privacy by default.** ntfy.sh is a public relay, so a push says only that a reminder is due unless the loop was made with `reveal`. That is the rule the desk courier and the notify-me skill already follow.
4. **Surfaces.** The CLI (`ol remind`, `ol loops`, `ol done`, `ol snooze`, `ol remind-tick`) and the shipped `openloops-remind` skill. They dispatch from the same `tools.py` list.

## Consequences

- **Invariants change, and only these.** openloops now writes its own store of loops, not only digests and board files. It also reaches the network through one optional runner module, when a reminder is armed, cancelled or delivered. The core modules still never call a model and never write to GitHub. `import openloops` and `import openloops.loops` pull in no channel library.
- **Equerry's role.** The desk's planned reminder engine ([equerry#3](https://github.com/thorwhalen/equerry/issues/3)) is this module. equerry keeps capture policy, the brief and the decision layer, and its desk reads loops.
- **v1 runs on the Mac.** Example A ("remind me in 3 hours") works end to end. These are later slices, each added at an existing seam:
  - The always-on tick on the server: an event-append store and a single writer, the reason the store is a seam.
  - Typed `done_when` and Waiting For predicates (never shell commands evaluated on a server).
  - Message-arrival conditions: correspond `listen`, with acquaint resolving the sender.
  - The weekly review packet.
- **What a channel can and cannot promise.** A message already delivered stays on the devices that received it. ntfy schedules three days ahead at most, which is why the tick exists. **Measured on ntfy.sh (2026-11-19): cancelling a scheduled message (`DELETE /<topic>/<sequence_id>`), or replacing it under the same sequence id, is acknowledged with a `message_delete` event, but the original is still delivered at its time**, contrary to ntfy's documentation. So in v1 a `done` or `snooze` before the time can still let the original push through, and `ol done`/`ol snooze` say so. The fix is the always-on tick on the server (a later slice), which delivers at the time and needs no scheduled copy, so there is nothing to cancel.
- crowsnest's `later` stays its own thing: it snoozes a derived session row, not a commitment.
