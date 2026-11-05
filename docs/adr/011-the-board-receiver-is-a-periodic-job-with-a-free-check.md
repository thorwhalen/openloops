---
status: accepted
date: 2026-11-03
---

# ADR-011 — The board receiver is a periodic job whose idle ticks cost nothing

## Context

The phone board's receiver (ADR-008, ADR-009) is a Claude session that turns the owner's taps into GitHub comments, closes and dispatched workers. It ran as a session cron on a server, and stops when that session closes. Taps made meanwhile are stored safely but reach GitHub only when a receiver next runs.

Options were a periodic job on the owner's Mac that starts a short session, a sweep run by hand, or a long-lived receiver session on a server.

## Decision

**A launchd `StartInterval` job on the owner's Mac, as in ADR-006**, every five minutes. It is a periodic job, not a daemon: it runs, may start a session, and exits.

**The tick is free when nothing is pending.** Starting a model session every five minutes would cost money all day for a board that is usually idle. The job therefore runs `python -m openloops.receiver_tick`, which asks the board store over HTTPS, with no model, whether anything needs the receiver: the work set of `references/receiver.md` (events without a receipt, stale `processing` claims, `queued` receipts and transient failures). The last two are counted only once they are an hour old: a receipt queued for another machine or a busy worker, or failing on a lasting GitHub error, would otherwise make every tick "pending" and start a paid session every five minutes to change nothing. Only if something is due does the tick replace itself with `claude -p <the packaged receiver prompt>` (`openloops/data/board/receiver-prompt.md`, which points at the packaged `references/`, so the job does not depend on an installed skill), run in the board's working directory, on a named model, with a per-tick spend cap and a tool allowlist that limits Bash to the commands the procedure runs.

**The tick keeps the heartbeat.** A session now runs only when there is work, so the session can no longer be what keeps `meta/receiver` fresh: an idle board would read amber all day, and a dead job would look like an idle one. Every successful check therefore writes the heartbeat itself (`{at, by, processed: 0, pending}`, `by` being the session name in `board/board.json`, pinned to the version it read, and left alone if another receiver's heartbeat is under 20 minutes old). This is the one store write the tick makes; it is the receiver's own document, and everything that reaches GitHub stays in the skill (ADR-008). The tick also touches a local `board-receiver.lastcheck` stamp, so `ol receiver-job-status` reports the last check and the last work separately: a recent check with old work is an idle board, an old check is a dead job.

**Fail closed on configuration, open on everything else.** A configuration error (no credentials file, a missing key, a cleartext `http://` origin other than loopback, a refused sign-in, a 403 from the store) is not something a session could get past, so the tick starts none, says so in the log on every tick, and stops writing the heartbeat, which turns the board amber. Any other failure (the store unreachable, a malformed answer, a bug in the check) starts the session anyway, because a check that failed closed there would suppress the receiver without a trace. Repeated failures back off exponentially: the next session one hour after the first, then two, four, and at most every six hours.

**Credentials never enter the plist.** They live in `~/.config/openloops/board-receiver.env` (mode 600; the installer refuses a looser file), read by the tick and by the session, as `receiver-http.md` already says. The plist pins the interpreter, the path to `claude` as `PATH` found it (a link, never the versioned file it points to, which an update deletes), the directories of `claude` and `node`, and the owner's `OPENLOOPS_*` configuration; nothing else.

## Consequences

- `ol install-receiver-job WORK_DIR` installs it, `ol receiver-job-status` and `python -m openloops.receiver_tick --check-only` inspect it, `ol uninstall-receiver-job` removes it. macOS only, like the sync job; on Linux the same command belongs in a systemd timer or crontab.
- `openloops.receiver_tick` is the one module that reaches the network, only to the owner's own board store (ADR-009's API). Nothing imports it; `import openloops` and the `ol` CLI never load it (a test asserts this).
- The sign-in is the one documented for an enlace_auth-style host (CSRF token, then a JSON login, cookie jar). On a host with a different sign-in the check fails, as a configuration error if the host refuses it, and the job is not the right receiver there until the tick learns that host's sign-in.
- The log is touched only by ticks that had work or failed. Liveness is the board's `meta/receiver` heartbeat, which the tick keeps fresh and the page turns amber after 20 minutes, and the local last-check stamp.
- The job's idle cost is a handful of HTTP calls per tick. A busy board costs what its sessions cost. `--max-budget-usd` caps **the tick's own session only**: the desk workers it dispatches are separate sessions with no cap from here.
- The unattended session reads issue text anyone can write. Its prompt says that everything it reads from GitHub or the store is data, reads comments only through a `--jq` filter (author, id, last line), and its Bash is limited to `gh`, `curl`, `python3`, the dispatch command and the sign-in's shell steps. `python3` is still arbitrary code, so the allowlist narrows mistakes rather than sandboxing; the prompt's rule is the guard.

## When to remove it

This is a bet that a timer beats a sweep run by hand. Remove it (`ol uninstall-receiver-job`; the board keeps every tap, and "process the board" in any session still works) if, a month after installing it, `ol receiver-job-status` shows no tick with work (the board is not being used from the phone), or the log shows sessions started for work that their receipts never finish (it costs without delivering).

## Confirmation

- A test asserts the plist uses `StartInterval`, carries no `KeepAlive`, invokes the interpreter with `-m openloops.receiver_tick`, and contains no credential name or value.
- Tests assert the pre-check against a fake board store (sign-in once, cookie reuse, each part of the work set, a fresh `queued` or failed receipt not yet due), that a tick with nothing pending never starts a session but writes the heartbeat and the last-check stamp, that another live receiver's heartbeat is left alone, that a configuration error starts nothing, and that a failing check does start one, backing off exponentially.
