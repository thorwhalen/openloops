# openloops.dashboard

One page you can look at instead of reading three command outputs.

[`render_dashboard()`](#openloops.dashboard.render_dashboard) takes what [`openloops.owed()`](openloops.html.md#openloops.owed), [`openloops.blocked()`](openloops.html.md#openloops.blocked)
and [`openloops.ls()`](openloops.html.md#openloops.ls) returned and renders a single self-contained HTML document —
no stylesheet, no script, no font and no request to anywhere. That is not decoration:
the page is meant to be published, and a published page runs no `gh`, shells out to
nothing and reaches no network.

So **the page is a snapshot, and it says so in its largest type.** This module inverts
the one rule [`openloops.digest`](openloops.digest.html.md#module-openloops.digest) holds to — a digest deliberately stamps no
generation time so that regenerating it is byte-stable — because here the generation
time is the whole claim. `made_at` is a required-in-practice argument rather than a
hidden `now()`, which is also what lets a test compare bytes.

The four registers are ordered the way a person needs them, and the fourth is the one
the package exists for:

1. **Needs you now** — obligations still open, each printing the predicate that decided
   it, unabbreviated, so a reader can disagree with the verdict rather than absorb it.
2. **Free to proceed** — blocker edges that have all closed, led by how many days the
   work has been free while nothing anywhere said so.
3. **In flight** — what the sessions left open, newest last turn first.
4. **Unknown** — every `?`, with why. It carries the envelope-level failures too: an
   `owed` that could not list is not “nothing owed”, and rendering it as `0` would
   make this page worse than no page. When the count really is zero the section says
   which checks earned that, because a clean board with no provenance is the same lie
   told quietly.

Everything this module prints goes through [`Sanitizer`](#openloops.dashboard.Sanitizer), which is
[`openloops.egress.scrub()`](openloops.egress.html.md#openloops.egress.scrub) plus HTML escaping plus a scheme allowlist on every link.
The one carve-out is the shared kit below: [`register()`](#openloops.dashboard.register) and [`rail()`](#openloops.dashboard.rail) \*\*escape
nothing\*\*. Every argument they take is markup, interpolated as given and some of it into
an unquoted attribute, because that is what a markup builder is; a caller that passes
anything it did not write itself puts it through [`Sanitizer`](#openloops.dashboard.Sanitizer) first. This module
passes literals. A page that carries a
repository name and an issue title is fine; one that carries a home path or a token is
the failure `openloops.egress` exists to prevent, and this renderer scrubs its input
rather than trusting it. A credential-shaped field is *withheld and counted*, never
silently dropped — the count is printed in the footer.

`CSS`, [`Sanitizer`](#openloops.dashboard.Sanitizer), [`register()`](#openloops.dashboard.register) and [`rail()`](#openloops.dashboard.rail) are public for
sibling renderers — a tool that shows a different half of the same picture and wants to
look like this page — so that the look, the egress rule and the markup the stylesheet
dresses stay in one place instead of being copied and drifting. They are the shared kit:
the stylesheet here is what makes `register--needs` a colour and `rail` a column, so
a package that writes those class names by hand is one rename away from a broken page.

```pycon
>>> html = render_dashboard({}, {}, [], made_at='2026-01-01T00:00:00Z')
>>> '<title>' in html and 'snapshot' in html
True
```

### Module Attributes

| [`DFLT_TITLE`](#openloops.dashboard.DFLT_TITLE)        | What the page is called — in the tab, in a gallery, and in its own masthead.   |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`DFLT_MAX_SESSIONS`](#openloops.dashboard.DFLT_MAX_SESSIONS) | How many session rows are printed.                                             |
| [`GAUGE_FULL_DAYS`](#openloops.dashboard.GAUGE_FULL_DAYS)   | Where the age gauge tops out.                                                  |

### Functions

| [`headline_counts`](#openloops.dashboard.headline_counts)(owed, blocked, sessions)           | The four figures across the top of the page.                                    |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`rail`](#openloops.dashboard.rail)(chip, tone, age[, unit, extra])               | The fixed left column of every row: what state it is in, and for how long.      |
| [`register`](#openloops.dashboard.register)(\*, ident, name, figure, tone, rule, ...) | One band: a heading, the count in the largest figure on the page, and its rule. |
| [`render_dashboard`](#openloops.dashboard.render_dashboard)(owed, blocked, sessions, \*)      | The three envelopes as one self-contained HTML page.                            |
| [`unchecked_count`](#openloops.dashboard.unchecked_count)(owed, blocked)                     | How many OBLIGATIONS could not be checked against the world.                    |
| [`unknown_count`](#openloops.dashboard.unknown_count)(owed, blocked, sessions)             | How many things read `?`, or `None` when even that cannot be counted.           |

### Classes

| [`Sanitizer`](#openloops.dashboard.Sanitizer)([aliases])   | Scrub, then escape.   |
|-------------------------------------------------------------------------|-----------------------|

### openloops.dashboard.DFLT_MAX_SESSIONS *= 40*

How many session rows are printed. The register states the true total either way; a
page that showed all 150-odd would bury the two registers above it.

### openloops.dashboard.DFLT_TITLE *= 'Open Loops Board'*

What the page is called — in the tab, in a gallery, and in its own masthead.

### openloops.dashboard.GAUGE_FULL_DAYS *= 90*

Where the age gauge tops out. Ninety days is the point past which the length of the
bar stops being informative and the number beside it is doing all the work.

### *class* openloops.dashboard.Sanitizer(aliases=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Scrub, then escape. The single path from an envelope to the document.

Two failures are possible and they are treated differently, exactly as
[`openloops.egress`](openloops.egress.html.md#module-openloops.egress) prescribes. A home path is *rewritten* — it is an identifier
and the tail is the part a reader needs. A credential is *withheld and counted*: the
field is replaced by a visible notice naming the pattern class, never the text, and
`withheld` is printed in the footer so the run reports it rather than quietly
losing a field.

```pycon
>>> s = Sanitizer()
>>> s.text('a < b')
'a &lt; b'
>>> s.text('token=' + 'ghp_' + 'A' * 36)
'[withheld: credential-shaped text (github_token)]'
>>> s.withheld
['github_token']
```

#### text(value)

One field, safe to place in the document.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### url(value)

A link target, or `''` when it is not one this page will follow.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.dashboard.headline_counts(owed, blocked, sessions)

The four figures across the top of the page. `None` is `?`, never a zero.

Shared by the masthead and by [`openloops.tools.dashboard()`](openloops.tools.html.md#openloops.tools.dashboard), so the number a
caller reads back is the number the page printed.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

```pycon
>>> headline_counts({'listed': True, 'counts': {'open': 2}, 'rows': []},
...                 {'listed': False}, [])['free_to_proceed'] is None
True
```

### openloops.dashboard.rail(chip, tone, age, unit='d', , extra='')

The fixed left column of every row: what state it is in, and for how long.

Shared kit (see the module docstring): `CSS` styles `rail`, `chip`,
`chip--<tone>` and `age`, so a sibling renderer that builds this by hand breaks
the next time a class name here changes.

`age` is the figure beside the unit — a number, or `None` for the `?` that
means nobody knows. It is not required to be a day count: pass a string and a
`unit` of your own for a page whose durations run from seconds to days.

`extra` is further markup placed between the state chip and the age — a second
chip a sibling page needs and this one has no equivalent of.

Nothing here is escaped, `extra` least of all: see the module docstring.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> rail("owed", "needs", 3)
'<div class="rail"><span class="chip chip--needs">owed</span><span class="age"><b>3</b><i>d</i></span></div>'
```

### openloops.dashboard.register(, ident, name, figure, tone, rule, body, folds=False, start_open=False, extra='')

One band: a heading, the count in the largest figure on the page, and its rule.

Shared kit (see the module docstring): `CSS` styles `register`,
`register--<tone>` and `register-head`, laying the head out as `auto 1fr` —
the figure in the first column, the heading and the rule in the second.

`folds` renders the band as a `<details>` a person can close, `start_open`
opening it anyway; both default off, which is the plain `<section>` this page has
always rendered. A `<summary>` may hold phrasing content and a heading only, so
the folding head carries the figure and the rule as `<span>``s rather than
``<p>``s. :data:`CSS` places those three flat children into the same ``auto 1fr`
grid a plain section’s head uses (figure down column one across both rows, heading
and rule down column two) and restores the disclosure affordance a
`display:grid` summary would otherwise cost it (#13).
`start_open` is ignored when `folds` is false — there is no disclosure to open —
because a caller decides `folds` from whether it has rows and passes both.

A band with nothing in it is not worth folding — there is nothing to hide — so that
decision belongs to the caller, which knows whether its body is rows.

`extra` is markup that heads the band’s body. A `<summary>` may not hold
interactive content and what a caller puts here is usually a control, so in the
`<details>` it goes inside the body; in the `<section>` it stays in the head,
under the rule. That is above the head’s hairline in one form and below it in the
other, which is how the caller that needs it already reads.

Nothing here is escaped: see the module docstring. `ident` and `tone` reach an
unquoted attribute, so they are the two that must be literals or already safe.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> register(ident="x", name="Needs you", figure="2", tone="needs", rule="now", body="")
'<section class="register register--needs" id="x"><div class="register-head"><p class="figure">2</p><div><h2>Needs you</h2><p class="rule">now</p></div></div></section>'
>>> register(ident="x", name="Quiet", figure="9", tone="done", rule="why", body="",
...          folds=True, start_open=True)
'<details class="register register--done" id="x" open><summary class="register-head"><span class="figure">9</span><h2>Quiet</h2><span class="rule">why</span></summary></details>'
```

### openloops.dashboard.render_dashboard(owed, blocked, sessions, , made_at=None, source='', title='Open Loops Board', max_sessions=40, standalone=True, aliases=None)

The three envelopes as one self-contained HTML page. No network, no script.

`owed` and `blocked` are the envelopes [`openloops.owed()`](openloops.html.md#openloops.owed) and
[`openloops.blocked()`](openloops.html.md#openloops.blocked) return; `sessions` is the list [`openloops.ls()`](openloops.html.md#openloops.ls)
returns. All three may be empty mappings, and an envelope whose `listed` is
`False` renders as `?` throughout rather than as zero.

`made_at` is the moment the snapshot was taken and is printed in the largest type
on the page. It defaults to now, but a caller that wants a byte-stable page passes
it — this is the one module in openloops that stamps a generation time, and it does
so because the whole claim of the page is *when*.

`standalone` wraps the output in a document scaffold for a file you open yourself.
Pass `False` for a host that supplies its own `<head>` — a published artifact
does — and the same page comes back as title, styles and content only.

`max_sessions` bounds the in-flight register; the true total is stated either way.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> page = render_dashboard(
...     {'listed': False, 'error': 'gh: not logged in', 'counts': {}},
...     {'listed': True, 'counts': {'unblocked': 0, 'total': 0}, 'rows': []},
...     [], made_at='2026-01-01T00:00:00Z')
>>> 'gh: not logged in' in page and 'could not' in page
True
```

### openloops.dashboard.unchecked_count(owed, blocked)

How many OBLIGATIONS could not be checked against the world. `None` if unknowable.

Deliberately narrower than [`unknown_count()`](#openloops.dashboard.unknown_count), and the two must not be merged in
the masthead. A `?` on an obligation means *the world could not be reached* — a
timeout, a missing `gh`, an untrusted owner. A low-confidence session digest means
something else entirely: the digest half checks nothing against the world by design,
so it has nothing it was unable to check. Rolling forty of the second into the first
reports a crisis of forty when the real number is one, and in the alarming direction.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> unchecked_count({'listed': True, 'rows': [{'state': 'unknown'}]},
...                 {'listed': True, 'rows': []})
1
>>> unchecked_count({'listed': False}, {'listed': True, 'rows': []}) is None
True
```

### openloops.dashboard.unknown_count(owed, blocked, sessions)

How many things read `?`, or `None` when even that cannot be counted.

A register that never listed could be hiding any number of unknown rows, so the
headline figure for unknowns is itself unknown. Reporting `2` there — the two
failures we happen to know about — is the exact shape of the lie this page is
against, and it is a lie a reader has no way to spot.

It counts the rows that read `?`, not the entries in the list below: one entry
can stand for forty sessions, and reporting `1` for those would be the tidier
number rather than the true one.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> unknown_count({'listed': True, 'rows': []}, {'listed': True, 'rows': []}, [{}])
0
>>> lows = [{'confidence': 'low'}] * 5
>>> unknown_count({'listed': True, 'rows': []}, {'listed': True, 'rows': []}, lows)
5
>>> unknown_count({'listed': False}, {'listed': True, 'rows': []}, [{}]) is None
True
```
