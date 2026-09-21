# openloops.transcripts

The default `transcript_source`: a direct reader of Claude Code’s on-disk state.

Claude Code persists one JSONL transcript per session under
`~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl`. [`ClaudeCodeTranscripts`](#openloops.transcripts.ClaudeCodeTranscripts)
is a `Mapping` from session id to [`Session`](openloops.base.md#openloops.base.Session), so a caller who
wants a different reader — a test fixture, a copy synced from another machine, an
in-house parser — passes any mapping of the same shape and nothing downstream changes.

Two things this reader deliberately does not do.

It never reverses a project directory name back into a working directory. The encoding
is lossy (`/`, `_` and `.` all become `-`), so `cwd` is read from the records
themselves or left empty.

It never looks at whether a process is running. A session’s transcript is a document;
what openloops reports is what the document says. Liveness is a different tool’s job,
and mixing the two is how a digest store becomes a session dashboard. That tool is
[crowsnest](https://github.com/thorwhalen/crowsnest), which reads the session registry
and the tail of these same transcripts to say who is busy, idle or waiting on you.

```pycon
>>> src = ClaudeCodeTranscripts(root='/nonexistent-dir-for-doctest')
>>> len(src)
0
>>> src.revision()
'0'
```

### Functions

| [`claude_projects_dir`](#openloops.transcripts.claude_projects_dir)([root])       | Where Claude Code keeps per-session transcripts.                                                                      |
|------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`parse_session`](#openloops.transcripts.parse_session)(records, \*[, key]) | Read one transcript's records into a [`Session`](openloops.base.md#openloops.base.Session). |

### Classes

| [`ClaudeCodeTranscripts`](#openloops.transcripts.ClaudeCodeTranscripts)([root, since_days, ...])   | Claude Code's persisted sessions, as a `Mapping[str, Session]`.         |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`Revisioned`](#openloops.transcripts.Revisioned)(source)                               | Give any mapping of sessions a total `revision` / `changed_since` pair. |

### *class* openloops.transcripts.ClaudeCodeTranscripts(root=None, , since_days=None, projects=None, skip_scratchpads=True)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

Claude Code’s persisted sessions, as a `Mapping[str, Session]`.

`since_days` bounds the scan by file modification time (`None` scans
everything); `projects` keeps only project directories whose name contains one of
the given substrings; `skip_scratchpads` drops the throwaway directories the CLI
creates under a temp root, which hold agent scratch sessions rather than work.

ADR-010’s revision shape lives here: [`revision()`](#openloops.transcripts.ClaudeCodeTranscripts.revision) returns an opaque token —
a file’s modification time for one session, a hash over all of them for the
collection — and [`changed_since()`](#openloops.transcripts.ClaudeCodeTranscripts.changed_since) compares against it. mtime is a coarse
signal that both misses content-preserving rewrites and fires on touches; that
trade is accepted rather than reprocessing several thousand transcripts a tick.

```pycon
>>> src = ClaudeCodeTranscripts(root='/nonexistent-dir-for-doctest')
>>> list(src), src.changed_since('0')
([], False)
```

#### changed_since(token, key=None)

Whether the current [`revision()`](#openloops.transcripts.ClaudeCodeTranscripts.revision) differs from *token*.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### path_of(key)

The transcript file backing *key*.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

#### revision(key=None)

An opaque change token: for one session, or for the whole collection.

For a single key it is the transcript’s modification time in nanoseconds. For
the collection it is a hash over every `(key, mtime)` pair, so a token can
be compared without holding the whole index.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### scratchpad_marker *= '-private-tmp'*

Project-directory names starting with this are scratchpads, not work.

### *class* openloops.transcripts.Revisioned(source)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

Give any mapping of sessions a total `revision` / `changed_since` pair.

ADR-010’s rule is that no caller may branch on whether a backend happens to
implement change detection — capability probing is backend leakage by another name.
So the probe happens exactly once, here, at the boundary: a wrapped source that
supplies its own cheap revision token keeps it, and one that does not gets a total
default (a hash of the value). `sync()` therefore always has
the methods and never asks.

The default is honest rather than fast: hashing requires loading the session, so a
source with no cheap token gains correctness and no speed. That is the right way
round — a plain `dict` of sessions in a test costs nothing to hash, and the
on-disk reader supplies mtime.

```pycon
>>> from openloops.base import Session
>>> src = Revisioned({'a': Session(key='a')})
>>> src.revision('a') == Revisioned({'a': Session(key='a')}).revision('a')
True
>>> src.changed_since(src.revision('a'), 'a')
False
```

#### changed_since(token, key=None)

Whether the current [`revision()`](#openloops.transcripts.Revisioned.revision) differs from *token*.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### revision(key=None)

An opaque token that changes when the underlying session changes.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.transcripts.claude_projects_dir(root=None)

Where Claude Code keeps per-session transcripts.

Resolution order: the *root* argument, then `CLAUDE_PROJECTS_DIR`, then
`~/.claude/projects`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

```pycon
>>> claude_projects_dir('/tmp/x').name
'x'
```

### openloops.transcripts.parse_session(records, , key='')

Read one transcript’s records into a [`Session`](openloops.base.md#openloops.base.Session).

Pure: same records in, same session out. Everything it reports is a fact about the
document — no inference, no judgement, and nothing about running processes.

Three details are corpus-driven rather than obvious, and getting them wrong
mislabels a large fraction of real sessions:

- \*\*Start and end come from `min`/`max` over every timestamp\*\*, not from the
  first and last line. Transcript lines are not written in timestamp order; on real
  data the first line holds the earliest timestamp only about four times in five.
- \*\*The project comes from the *first* record’s `cwd`.\*\* Four sessions in five
  visit more than one working directory (scratchpads, sibling repos, task dirs), and
  the last or most-frequent one names a different repository about half the time.
- **Branches are a tuple.** A third of sessions touch more than one.

```pycon
>>> recs = [
...     {"type": "user", "sessionId": "s1", "cwd": "/w/proj", "timestamp": "T1",
...      "gitBranch": "main",
...      "message": {"role": "user", "content": [{"type": "text", "text": "do it"}]}},
...     {"type": "assistant", "sessionId": "s1", "timestamp": "T2",
...      "message": {"role": "assistant", "model": "m",
...                  "content": [{"type": "text", "text": "done"}]}},
... ]
>>> s = parse_session(recs)
>>> s.key, s.project, s.turn_count, s.last_assistant_text
('s1', 'proj', 1, 'done')
>>> s.started_at, s.ended_at, s.git_branch, s.ended_mid_turn
('T1', 'T2', 'main', False)
```

* **Return type:**
  [`Session`](openloops.base.md#openloops.base.Session)
