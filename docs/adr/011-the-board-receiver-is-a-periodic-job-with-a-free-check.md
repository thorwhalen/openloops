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

**The tick is free when nothing is pending.** Starting a model session every five minutes would cost money all day for a board that is usually idle. The job therefore runs `python -m openloops.receiver_tick`, which asks the board store over HTTP, with no model, whether anything needs the receiver (the work set of `references/receiver.md`: events without a receipt, stale or queued or transiently failed receipts). Only if something does, it replaces itself with `claude -p <the packaged receiver prompt>` (`openloops/data/board/receiver-prompt.md`), run in the board's working directory, on a named model, with a per-tick spend cap and an explicit tool allowlist.

**Fail open.** If the check cannot run (the store is unreachable, the sign-in fails, the credentials file is incomplete), the session starts anyway and the reason goes to the log. A check that fails closed would suppress the receiver without a trace, which is the silent failure this package exists to prevent. An outage therefore costs sessions, visibly, and not taps, invisibly.

**Credentials never enter the plist.** They live in `~/.config/openloops/board-receiver.env` (mode 600; the installer refuses a looser file), read by the tick and by the session, as `receiver-http.md` already says. The plist pins the interpreter, the path to `claude`, the directories of `claude` and `node`, and the owner's `OPENLOOPS_*` configuration; nothing else.

## Consequences

- `ol install-receiver-job WORK_DIR` installs it, `ol receiver-job-status` and `python -m openloops.receiver_tick --check-only` inspect it, `ol uninstall-receiver-job` removes it. macOS only, like the sync job; on Linux the same command belongs in a systemd timer or crontab.
- `openloops.receiver_tick` is the one module that reaches the network, only to the owner's own board store (ADR-009's API). Nothing imports it; `import openloops` and the `ol` CLI never load it (a test asserts this).
- The sign-in is the one documented for an enlace_auth-style host (CSRF token, then a JSON login, cookie jar). A host with a different sign-in needs a different tick; until then its check fails open, which is safe and merely not free.
- The log is touched only by ticks that had work, so an old log means an idle board, not a dead job. Liveness is the board's own `meta/receiver` heartbeat, which its page turns amber after 20 minutes.
- The job's idle cost is a handful of HTTP calls per tick. A busy board costs what its sessions cost, bounded by `--max-budget-usd` per tick.

## Confirmation

- A test asserts the plist uses `StartInterval`, carries no `KeepAlive`, invokes the interpreter with `-m openloops.receiver_tick`, and contains no credential name or value.
- Tests assert the pre-check against a fake board store (sign-in once, cookie reuse, each part of the work set), that a tick with nothing pending never starts a session, and that a failing check does.
