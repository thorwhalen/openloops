# openloops.digest

Rendering one session into one dated markdown digest. No model, no network.

The whole of the release’s honesty rule lives in this module:

> **A digest states what the session said, dated — never what is currently true.**

So every heading here carries the timestamp of the thing under it, the loop state is
phrased as a reading of the transcript rather than a claim about the world, and the
front matter says `verified: false` because nothing has been checked against
anything. ADR-015’s failure mode — a snapshot of local state that was already wrong on
two of four fields, published and handed to a consumer that acted on it — is what these
rules exist to prevent, and the way to prevent it is to never make the claim.

[`render()`](#openloops.digest.render) is a pure function of its [`Session`](openloops.base.md#openloops.base.Session) and
[`Verdict`](openloops.base.md#openloops.base.Verdict). It stamps no generation time, which is what allows
`tests/test_sync.py` to delete the entire store, regenerate, and compare bytes.

### Module Attributes

| [`SECTION_LIMITS`](#openloops.digest.SECTION_LIMITS)   | How much of each section is kept.   |
|-------------------------------------------------------------------|-------------------------------------|

### Functions

| [`render`](#openloops.digest.render)(session, verdict, \*, source)             | The markdown for one digest.       |
|---------------------------------------------------------------------------------------------------|------------------------------------|
| [`make_digest`](#openloops.digest.make_digest)(session, verdict, \*, source[, ...]) | Render, scrub, and key one digest. |

### openloops.digest.SECTION_LIMITS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [int](https://docs.python.org/3/builtins/functions.html#int)]* *= {'compaction': 3000, 'last_assistant_text': 4000, 'last_user_prompt': 1200, 'recap': 1500}*

How much of each section is kept. Bounds are deterministic so regeneration is
byte-stable; they exist because a digest is meant to be read, not archived whole.

### openloops.digest.make_digest(session, verdict, , source, aliases=None)

Render, scrub, and key one digest.

Raises [`CredentialFound`](openloops.egress.md#openloops.egress.CredentialFound) when the rendered text matches a
credential pattern — deliberately, so the caller skips that session loudly rather
than writing a secret into a store that may be synced.

* **Return type:**
  [`Digest`](openloops.base.md#openloops.base.Digest)

```pycon
>>> from openloops.base import Session, Verdict
>>> d = make_digest(Session(key='s1'), Verdict('open', 'why'), source='demo')
>>> d.key
'demo/open/s1.md'
```

### openloops.digest.render(session, verdict, , source)

The markdown for one digest. Pure, dated, and bounded.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from openloops.base import Session, Verdict
>>> s = Session(key='s1', project='proj', started_at='T0', last_turn_at='T1',
...             last_assistant_text='Shipped it.', turn_count=3)
>>> verdict = Verdict('archive', 'its closing lines declare it finished')
>>> text = render(s, verdict, source='demo')
>>> text.splitlines()[0]
'---'
>>> 'state: archive' in text
True
>>> render(s, verdict, source='demo') == text     # pure: same in, same out
True
```
