# openloops.egress

The egress choke point: nothing leaves openloops carrying a home path or a secret.

A digest is derived from a transcript, and transcripts are the highest-entropy secret
source on a developer’s machine — pasted tokens, `.env` contents, tracebacks full of
absolute paths. A digest store can be a git-synced private repository, so \*\*a written
digest is an export surface\*\*, and the moment to apply that discipline is before the
first byte is written rather than before the first push.

Two rules, and they are deliberately asymmetric:

- **Paths are rewritten**, never raised on. A path is an identifier, not a secret, and
  the tail of it is the part a reader needs. This machine’s home becomes `~`; \*any
  other\* home — a server’s root home, a colleague’s, a CI runner’s — becomes
  `~other`, keeping the tail and dropping the identity.
- **Credentials raise.** [`scrub()`](#openloops.egress.scrub) never silently redacts a secret, because a silent
  redaction teaches nobody that a secret was there. It raises [`CredentialFound`](#openloops.egress.CredentialFound),
  the caller skips that one session, and the run reports it — loudly, and without ever
  quoting the matched text.

Two shapes are easy to miss and both were, at first. Claude Code encodes a working
directory into a directory name by turning `/`, `_` and `.` into `-`, so a home
path appears throughout transcripts in a dashed form — trivially reversible and just
as identifying. And a transcript from an ssh session names *that* machine’s home,
not this one’s, so rewriting only `$HOME` leaves every foreign home intact. Both forms
are handled here, and [`scrub()`](#openloops.egress.scrub) asserts its own postcondition afterwards rather than
trusting that it did.

The same rules apply to openloops’ own repository, which is why
`tests/test_egress_repo.py` runs [`scan_files()`](#openloops.egress.scan_files) over everything the build ships.
One implementation, two configurations.

```pycon
>>> scrub("see /nowhere/at/all/x.py", aliases={"/nowhere/at/all": "~/code"})
'see ~/code/x.py'
>>> scrub("token=" + "ghp_" + "A" * 36)
Traceback (most recent call last):
    ...
openloops.egress.CredentialFound: credential-shaped text (github_token) at offset 6
```

### Module Attributes

| [`CREDENTIAL_PATTERNS`](#openloops.egress.CREDENTIAL_PATTERNS)   | Named credential patterns, checked in order.   |
|------------------------------------------------------------------------|------------------------------------------------|

### Functions

| [`apply_aliases`](#openloops.egress.apply_aliases)(text[, aliases])       | Replace each alias at a path boundary, longest key first.                                                             |
|---------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`default_aliases`](#openloops.egress.default_aliases)()                    | The rewrites applied when a caller supplies none: this machine's home → `~`.                                          |
| [`find_credentials`](#openloops.egress.find_credentials)(text)               | Every credential-pattern hit, as `(pattern_name, offset)` pairs.                                                      |
| [`find_absolute_paths`](#openloops.egress.find_absolute_paths)(text[, aliases]) | Home paths — literal or encoded — still present after rewriting, with offsets.                                        |
| [`rewrite_paths`](#openloops.egress.rewrite_paths)(text[, aliases])       | Apply the aliases, then rewrite every home path they did not cover.                                                   |
| [`scan`](#openloops.egress.scan)(text, \*[, aliases, where])     | Report egress violations instead of raising — for auditing many files at once.                                        |
| [`scan_files`](#openloops.egress.scan_files)(paths, \*[, aliases])     | Run [`scan()`](#openloops.egress.scan) over each readable text file, accumulating every problem. |
| [`scrub`](#openloops.egress.scrub)(text, \*[, aliases, where])    | Rewrite paths and raise on credentials.                                                                               |

### Exceptions

| [`CredentialFound`](#openloops.egress.CredentialFound)(pattern_name, offset, \*[, where])   | Raised when text about to be written matches a credential pattern.   |
|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|

### openloops.egress.CREDENTIAL_PATTERNS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Pattern](https://docs.python.org/3/library/re.html#re.Pattern)], ...]* *= (('aws_access_key_id', re.compile('(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])')), ('aws_secret_access_key', re.compile('(?i)aws_secret_access_key\\\\s\*[:=]\\\\s\*\\\\S{20,}', re.IGNORECASE)), ('github_token', re.compile('\\\\bgh[pousr]_[A-Za-z0-9]{36,}\\\\b')), ('github_pat', re.compile('\\\\bgithub_pat_[A-Za-z0-9_]{22,}\\\\b')), ('gitlab_token', re.compile('\\\\bglpat-[A-Za-z0-9_\\\\-]{20,}\\\\b')), ('anthropic_api_key', re.compile('\\\\bsk-ant-[A-Za-z0-9_\\\\-]{20,}\\\\b')), ('openai_api_key', re.compile('\\\\bsk-(?!ant-)[A-Za-z0-9_\\\\-]{20,}\\\\b')), ('stripe_key', re.compile('\\\\b[srp]k_(?:live|test)_[A-Za-z0-9]{16,}\\\\b')), ('npm_token', re.compile('\\\\bnpm_[A-Za-z0-9]{30,}\\\\b')), ('pypi_token', re.compile('\\\\bpypi-[A-Za-z0-9_\\\\-]{32,}')), ('huggingface_token', re.compile('\\\\bhf_[A-Za-z0-9]{30,}\\\\b')), ('sendgrid_key', re.compile('\\\\bSG\\\\.[A-Za-z0-9_\\\\-]{20,}\\\\.[A-Za-z0-9_\\\\-]{20,}\\\\b')), ('slack_token', re.compile('\\\\bxox[baprs]-[A-Za-z0-9\\\\-]{10,}\\\\b')), ('google_api_key', re.compile('\\\\bAIza[0-9A-Za-z_\\\\-]{35}\\\\b')), ('google_oauth_refresh_token', re.compile('\\\\b1//0[A-Za-z0-9_\\\\-]{20,}\\\\b')), ('json_web_token', re.compile('\\\\beyJ[A-Za-z0-9_\\\\-]{10,}\\\\.eyJ[A-Za-z0-9_\\\\-]{10,}\\\\.')), ('private_key_block', re.compile('-----BEGIN [A-Z ]\*PRIVATE KEY-----')), ('url_inline_password', re.compile('\\\\b[a-z][a-z0-9+.\\\\-]\*://[^/\\\\s:@]+:[^/\\\\s@]{6,}@')), ('secret_assignment', re.compile('(?i)(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])\*(?:api[_-]?key|secret[_-]?\\\\w\*|passwd|password|access[_-]?token|auth[_-]?token|token|credential\\\\w\*)\\\\b\\\\s\*[:=]\\\\s\*[\\'\\\\"]?((?=[^\\'\\\\"\\\\s]\*[A-Za-z])(?=[^\\'\\\\", re.IGNORECASE)))*

Named credential patterns, checked in order. Most are well-known vendor prefixes,
which give near-zero false positives; the assignment rule at the end is the only
heuristic among them, and the URL rule catches the shape a prefix list cannot.

### *exception* openloops.egress.CredentialFound(pattern_name, offset, , where='')

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when text about to be written matches a credential pattern.

The message names the pattern class and the offset. It never contains the matched
text: an exception that quotes a secret has moved the secret into a log file.

### openloops.egress.apply_aliases(text, aliases=None)

Replace each alias at a path boundary, longest key first. Nothing else.

Longest-first matters: a home directory and a projects directory beneath it are both
aliases, and the more specific one must win. Boundary-anchoring matters for the
opposite reason: a bare `str.replace` turns a *longer* sibling name into a
half-rewritten mess — a home of `…/bob` would mangle `…/bobby` into `~by`,
corrupting the path and leaving half the other name behind.

Separate from [`rewrite_paths()`](#openloops.egress.rewrite_paths) because auditing and scrubbing want different
things: an audit must still be able to *see* a foreign home path in order to report
it, which it could not if every caller had already rewritten one away.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> apply_aliases("/a/b/c and /a", {"/a": "~", "/a/b": "$B"})
'$B/c and ~'
>>> apply_aliases("/a2/x", {"/a": "~"})
'/a2/x'
```

### openloops.egress.default_aliases()

The rewrites applied when a caller supplies none: this machine’s home → `~`.

Both spellings of it, because the encoded form appears in transcripts as often as
the literal one.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> sorted(set(default_aliases().values()))
['~']
```

### openloops.egress.find_absolute_paths(text, aliases=None)

Home paths — literal or encoded — still present after rewriting, with offsets.

The example builds its path by concatenation and compares rather than printing,
because this module’s own source is scanned by the rule it implements: a literal
home-rooted path in a docstring would violate the thing being documented.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

```pycon
>>> home = "/Us" + "ers/someone"
>>> [p for p, _ in find_absolute_paths(home + "/x", aliases={})] == [home]
True
>>> find_absolute_paths(home + "/x", aliases={home: "~"})
[]
```

### openloops.egress.find_credentials(text)

Every credential-pattern hit, as `(pattern_name, offset)` pairs.

The matched text is never returned — only where it is and what it looked like.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

```pycon
>>> find_credentials("nothing to see here")
[]
>>> find_credentials("AKIA" + "B" * 16)
[('aws_access_key_id', 0)]
```

### openloops.egress.rewrite_paths(text, aliases=None)

Apply the aliases, then rewrite every home path they did not cover.

A transcript from an ssh session names *that* machine’s home, and a CI traceback
names a runner’s; neither is covered by an alias derived from this process. They are
rewritten to `FOREIGN_HOME`, which keeps the tail of the path and drops the
part that identifies somebody.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> rewrite_paths("/ro" + "ot/py/x", aliases={})
'~other/py/x'
>>> rewrite_paths("-Us" + "ers-someone-proj", aliases={})
'~other-proj'
```

### openloops.egress.scan(text, , aliases=None, where='')

Report egress violations instead of raising — for auditing many files at once.

Returns a list of human-readable problem descriptions, empty when the text is clean.
[`scrub()`](#openloops.egress.scrub) is what production code calls; this is what the repository’s own egress
test calls, because a test that stopped at the first violation would take one run per
problem to converge.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> scan("all clear")
[]
```

### openloops.egress.scan_files(paths, , aliases=None)

Run [`scan()`](#openloops.egress.scan) over each readable text file, accumulating every problem.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### openloops.egress.scrub(text, , aliases=None, where='')

Rewrite paths and raise on credentials. The only way text leaves openloops.

`where` is a caller-supplied label (a session id, a file name) carried into the
exception so a failed run can say *which* input tripped, without quoting it.

The path check runs on the **output**, not the input, because `aliases` is
caller-supplied: a rewrite can in principle produce a home path as easily as remove
one, and a postcondition that is only true of benign inputs is not a postcondition.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> scrub("built /nowhere/proj/x", aliases={"/nowhere/proj": "$PROJ"})
'built $PROJ/x'
```
