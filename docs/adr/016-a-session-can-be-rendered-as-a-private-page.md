---
status: proposed
date: 2026-11-24
---

# ADR-016 — A session can be rendered as a page: pure, script-free, and private by rule

**Proposed, not accepted. Nothing in this record is built.** It adds a new output made from transcript text, which [ADR-003](003-the-public-private-boundary.md) treats as the most sensitive data this package touches, so it stays `proposed` until the owner of this repository accepts it.

## Context

`openloops.exchanges` already reads a transcript into exchanges: each prompt a session received, with the reply its turn ended with, and the sentences of a typed prompt that ask something. A consumer can list "what the person asked, and what was answered" from that, and one does.

What no part of the ecosystem can do is show the answer in its place. A reader who finds a short answer on a card and wants the original has two options today, and both fail in the common case:

- **Open the session where it runs.** That works only while the session is alive and reachable, it opens the session and not the answer, and it means reviving a finished session to read one paragraph.
- **Read the transcript file.** It is JSONL with tool results, injected text and sub-agent threads interleaved; it is not readable, and nothing renders it.

A digest does not fill the gap: by [ADR-005](005-a-digest-is-dated-never-current.md) it holds the session's last word and last prompt, not its turns.

## Decision

### 1. A pure function renders a transcript as one page

`session_page(records, *, focus=None, sanitizer=...) -> str` returns one self-contained HTML document. It reads records already loaded and returns text: no model, no network, no account, as everything in the core. A thin `ol page <session> [--focus <turn>] [--out FILE]` writes it to a file the user names.

- One block per turn of the main thread: the prompt, then every text the session wrote in that turn, in order.
- Each turn carries a stable anchor made from the prompt record's own id (the same id `Exchange.uuid` carries), so an address ending in that anchor opens on the turn.
- A prompt shows who it came from, as `exchanges` classifies it: typed, another session (named), or tooling.

### 2. The page has no script

Highlighting the turn an address points at is the browser's own `:target` rule. Marking a sentence inside a prompt is markup written at render time. Nothing on the page needs script, so the page carries none, and it can be served under the strictest content policy a host has.

Consequence: anything that needs script (notes on a passage, folding, search) is not part of this page. It belongs to the host that serves it.

### 3. What is left out, and what is withheld

Left out by default: tool results, thinking, sub-agent threads, and text the tooling injected into a turn. A tool call is one line: the tool's name and what it was pointed at. A compaction summary is shown and labelled as one.

Credential-shaped text is withheld **per field and counted**, and the page states the count. Cleaning happens before any text is cut, so a credential cannot survive as a prefix.

This is deliberately not `egress.scrub`'s behaviour. `scrub` refuses a whole document on the first credential-shaped match, which is right for a digest that may be synced and wrong for a session, where one pasted token would make every page of every long session unavailable. The per-field behaviour already exists (`dashboard.Sanitizer.text`).

The patterns catch credential shapes and home paths. They do not catch private content in general, and nothing can. Rule 4 is what protects that.

### 4. A rendered session is private data, and the package says so

- A page is written only where the caller names. The package never publishes one, never uploads one, and ships no option that does.
- A page is never test data, a fixture, an example in the docs, or an attachment to an issue in this repository. Fixtures are synthetic, as for transcripts (ADR-003).
- The docs for `ol page` say plainly what a page is: the words of a session, for the person who ran it, to be kept where only they can read it.
- A host that serves pages owns the rest: who may read, how long a page is kept, and that it is sent uncached, unframed and unindexed.

### 5. Three additive facts on `Exchange`

So a reader can point at the answer and tell a read answer from an unread one, without a second parser:

- `reply_uuid`: the id of the record the reply came from (the anchor inside a turn).
- `texts`: every text of the turn in order, of which `reply` remains the last. An answer given before further work is otherwise invisible.
- `followed_up_at`: when the same person next typed in that session, or empty. "Nothing typed since the answer" is the cheapest honest signal that an answer was not read.

All three are new fields with defaults. No existing field changes meaning.

## Seams

| Seam | Default | The replacement that already exists |
|---|---|---|
| `records` (the function's input) | `load_records(path)`: the transcript on disk | a turn store that outlives the transcript, for sessions whose files the CLI has deleted |
| `sanitizer=` | `dashboard.Sanitizer` | a host's stricter sanitiser |

The page's layout, its styles and its omission rules are not seams.

## Consequences

- The package gains a second output made from transcript text (the digest is the first). Rule 4 is the price of that.
- A consumer can link a card to the turn that answers it, for a live session and a finished one alike, without reviving anything.
- `exchanges` output grows by three fields; consumers that cache it per file must renew that cache once.
- This is not a session dashboard. The page says what a session said, dated, exactly as ADR-005 requires of a digest. It shows no live state and offers no reply, attach or resume control ([ADR-004](004-loop-state-not-process-state.md)).

## Alternatives considered

- **Depend on an existing transcript-to-HTML tool.** Two are published under permissive licences. Neither documents withholding secrets or an anchor per turn, and each brings its own parser and several dependencies. Their layouts are worth studying; the rendering here is small because the reader, the sanitiser and the styles already exist.
- **Render inside the consumer that shows the cards.** It would need its own transcript parser, which the consumer's own rule forbids (one parser, here).
- **A page with script, so it can fold, search and annotate.** Rejected for this record: a page of private text is safest when it cannot run anything. A host can add those around it.
- **Reuse the digest.** A digest is one turn by design.

## Confirmation

When built: a synthetic transcript renders to a page with one anchored block per turn; a planted credential-shaped string appears nowhere in the output and the count is 1; the output contains no `<script`; `followed_up_at` is empty for the last typed prompt and set for the one before it; the wheel test still passes.
