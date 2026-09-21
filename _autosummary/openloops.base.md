# openloops.base

Data structures shared across openloops: what a session is, and what a digest is.

Nothing here does I/O and nothing here makes a judgement. [`openloops.transcripts`](openloops.transcripts.md#module-openloops.transcripts)
reads sessions, `openloops._classify` judges them, [`openloops.digest`](openloops.digest.md#module-openloops.digest) renders
them, and all three speak in the types defined here.

The types are deliberately flat and JSON-shaped. A session read from Claude Code’s
on-disk state and a session supplied by some other reader are the same object to the
rest of the package — that is what makes `transcript_source=` a one-argument swap.

### Module Attributes

| [`OPEN`](#openloops.base.OPEN)    | the session's own last word left something for the human.   |
|----------------------------------------------------------|-------------------------------------------------------------|
| [`ARCHIVE`](#openloops.base.ARCHIVE) | the session's own last word closed out.                     |
| [`STATES`](#openloops.base.STATES)  | The two loop states, in the order they are shown.           |

### Classes

| [`Digest`](#openloops.base.Digest)(key, text, session_key, source, state)   | One rendered digest: its store key and its markdown text.                   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`Locator`](#openloops.base.Locator)(type[, url, text, at])                  | A typed, human-readable pointer to something outside the digest.            |
| [`Session`](#openloops.base.Session)(key[, title, ai_title, cwd, ...])       | What one Claude Code session's persisted state says, parsed but not judged. |
| [`Verdict`](#openloops.base.Verdict)(state, reason[, cues, at, confidence])  | A loop-state judgement, with the rule that produced it and the cues it saw. |

### openloops.base.ARCHIVE *= 'archive'*

the session’s own last word closed out.

* **Type:**
  Loop state

### *class* openloops.base.Digest(key, text, session_key, source, state, verdict=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One rendered digest: its store key and its markdown text.

`text` is a pure function of the [`Session`](#openloops.base.Session) it was built from. It carries
no generation timestamp, which is what lets the regeneration test in
`tests/test_sync.py` compare bytes rather than fields.

#### as_dict()

JSON-ready form (without the markdown body).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *class* openloops.base.Locator(type, url='', text='', at='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A typed, human-readable pointer to something outside the digest.

The exportable half of ADR-015’s evidence split: a short typed reference that
another tool (or a person) can resolve, never a content hash and never a byte
offset into a file that is garbage-collected after thirty days.

```pycon
>>> Locator("pr", url="https://github.com/o/r/pull/1").as_dict()["type"]
'pr'
```

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### openloops.base.OPEN *= 'open'*

the session’s own last word left something for the human.

* **Type:**
  Loop state

### openloops.base.STATES *= ('open', 'archive')*

The two loop states, in the order they are shown.

### *class* openloops.base.Session(key, title='', ai_title='', cwd='', project='', git_branches=(), started_at='', ended_at='', last_turn_at='', last_user_prompt='', last_prompt_at='', last_assistant_text='', recap='', recap_at='', compaction='', compaction_at='', turn_count=0, model='', ended_mid_turn=False, ended_with_error=False, locators=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one Claude Code session’s persisted state says, parsed but not judged.

Every field is a *fact read from the transcript*, never an inference about the
world. `last_assistant_text` is what the session said last; it is not a claim
that the thing it describes is still true.

`key` is the session id. It is the only identifier openloops uses, and per
ADR-014 nothing in the model hangs off it: a digest is a view keyed by session,
not a record owned by one.

#### as_dict()

JSON-ready form (`asdict` already flattens the nested locators).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### compaction *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

The context-compaction summary, a different and much longer thing than the recap,
covering only the part of the session that preceded it.

#### ended_mid_turn *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

The transcript’s final conversational record is an unanswered human prompt, or an
assistant tool call whose result never arrived — i.e. the session stopped mid-turn.

#### ended_with_error *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

The last thing the session said is a usage-limit or API-error banner rather than
the assistant’s own words: it was cut off, not finished.

#### *property* git_branch *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The branch the session opened on — the one that names it, when several ran.

A third of sessions touch more than one branch, so a single value is a summary
rather than a fact; `git_branches` is what carries the truth.

#### *property* heading *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

its description, else its label.

* **Type:**
  What to call this session in prose

#### recap *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

Claude Code’s own end-of-turn recap (its `away_summary` record) — one to three
sentences it wrote itself, usually naming what it thought came next. Reading it
is retention, not duplication: it was generated and billed once already, and it
disappears with the transcript.

### *class* openloops.base.Verdict(state, reason, cues=(), at='', confidence='high')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A loop-state judgement, with the rule that produced it and the cues it saw.

`reason` and `cues` exist so a reader can disagree. A classification whose
grounds are not shown is an assertion, and openloops does not make assertions
about sessions — it reports what they said and why it read them that way.

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### at *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

When the text this verdict was read from was written. Usually the closing turn,
but the recap rule reads text written later, and a heading dated to the wrong
moment is exactly the thing ADR-005 forbids.

#### confidence *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'high'*

`"high"` when a rule actually fired, `"low"` when the state is the default
and nothing in the transcript supported it. A classifier that hides which of the
two it did is claiming knowledge it does not have.
