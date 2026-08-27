---
name: openloops-needs-human
description: "Use the moment you are blocked on the human and cannot finish on your own: a secret or API key only they can set; a command only they can run (a deploy, a `sudo`, a step your permissions refuse); access you do not have; a purchase, an approval, a decision only they can make; or a decision ALREADY RECORDED -- an ADR, a convention, a default -- that is now in your way or looks wrong given what you now know. Files the blocker as a `manual-task` GitHub issue in the affected repo, carrying a shell predicate, so the obligation outlives the session instead of dying in a message nobody re-reads and `ol owed` can re-check it later. Triggers on: 'I can't do this without you', 'you'll need to run this', 'this needs your credentials', 'blocked on', 'someone has to decide', 'I don't have access to', 'the ADR says X but', or any point where the honest next step is to hand the work back. File it BEFORE writing the hand-back message, not instead of it. Skip when you could do the thing yourself."
metadata:
  audience: users
---

# needs-human: file the blocker before you hand the work back

When you stop and say "I need you to do X", that obligation exists only in a transcript
the human may never re-read, in a session that is about to end. Nothing tracks it. It is
found again weeks later, or not at all.

A `manual-task` issue is the fix. It is queryable across every repo with one command,
from a terminal or a phone, with every session stopped:

```bash
gh search issues --owner OWNER --label manual-task --state open
```

And with `openloops` installed, `ol owed` lists the same issues and **re-runs the check
each one carries** before showing it — so an ask discharged out of band reads *done*
instead of sitting open for months. That only works if you write the check. It is step 5,
and it is the field that stops the issue from becoming a lie.

So: **the ask goes in an issue first, and in your closing message second.**

Two things are not optional and both are easy to skip:

- **the verify predicate** — step 5. Without it the obligation can never be observed as
  finished, only as still filed;
- **the egress check** — step 6. Everything you write here lands in a repo that may be
  public and outlives the context that made it safe.

## When to file

File when the next step is genuinely not yours:

- a secret, token, API key or credential must be set somewhere you cannot write;
- a command must be run that your permissions refuse, or that needs a password, a
  hardware key, or a browser login;
- access must be granted — an org, a repo, a deploy key, a cloud account, a machine;
- something must be bought, or a plan upgraded;
- an approval or sign-off is required before work can continue;
- a decision is the human's to make and you were not given the grounds to make it;
- a decision that is **already recorded** — an ADR, a convention, a config default, a plan
  — is now blocking you, or looks wrong in light of what you now know.

**That last one is reopening, and you may reopen anything; you may not decide it.** Who
recorded it does not make it more settled — a decision an agent made and a decision a
human made are equally open to being reopened. The bar is "this looks like a blocker, or
looks wrong", not "I can prove it". File, then comply or stop: **never work around a
recorded decision without saying so**, because that leaves the record and the reality
disagreeing, which is worse than either being wrong. Reopening takes five extra fields —
step 4.

**Do not file when you could do it yourself.** A `manual-task` issue that turns out to be
work you were allowed to do teaches the human to stop reading the label, and an ignored
label is worse than none. Try the thing once first. If it fails on permissions,
credentials or access, that failure is your evidence — quote it.

**Asking is not filing, and the difference is whether the loop closes in this session.**
If you need an answer to continue *now* and the human is present, ask. If the answer
requires them to go and do something, or the work stops here either way, the ask outlives
the session and belongs in an issue as well.

**Do not file** for a preference where any reasonable choice works (pick one and say
which), or for a routine review request. Those go in your closing message.

## The procedure

Steps 1–3 decide *where*. Steps 4–6 decide *what goes in it*. Step 7 is one shell call
that writes, scrubs and files. Read to the end of 6 before you run 7.

### 1. Name the affected repo

The affected repo is the one **whose state changes when the ask is discharged** — not
whichever repo you happen to be sitting in. If you are working in `A` and the blocker is
a missing secret on `B`, it is filed on `B`.

```bash
gh repo view --json nameWithOwner -q .nameWithOwner   # from inside a checkout
```

### 2. Decide where you are allowed to file it

Filing a `manual-task` issue means **applying a label**, and anything below `TRIAGE`
cannot. Ask GitHub rather than guessing:

```bash
case "$(gh repo view OWNER/REPO --json viewerPermission -q .viewerPermission)" in
  ADMIN|MAINTAIN|WRITE|TRIAGE) echo "can label — file here" ;;
  *)                           echo "cannot label — use the fallback" ;;
esac
```

Three cases, and the rule is the same one each time: **the obligation must be recorded
somewhere the human will actually query, and never posted into a tracker that is
somebody else's channel.**

| The affected repo | What you do |
|---|---|
| the human owns it, or you have `TRIAGE` or better | **File it there.** That is where someone working on this repo will find it. |
| you can only read it, or it has no GitHub remote at all | **File in the fallback repo** (below), with an `**Affected repo:**` line naming the real one, and the affected repo at the start of the title. |
| it belongs to a client, a customer, or another team | **Post nothing in their tracker** — create neither the issue nor the label. File in the fallback repo, then show the human the draft you *would* post in theirs, and post it only once they say so. |

**The fallback repo is one the human nominates, once.** It is where cross-cutting asks go
that have no home of their own: a repo they own, ideally private (so machine-level detail
is safe there), that already carries the `manual-task` label. If you do not know which
repo that is, **ask** — one question now beats an obligation filed where nobody looks.
When you file there because the affected repo would not take it, name that repo in the
body, otherwise the ask is untraceable:

```markdown
**Affected repo:** `OWNER/REPO` — filed here because this account has READ on it and
cannot apply `manual-task` there.
```

and start the title with the affected repo, so the fallback repo's issue list stays
readable: `OWNER/REPO: grant push so the CI fix can be merged`.

The fallback is a fallback, not a default. A blocker with a repo you *can* write to,
filed in the fallback, is a blocker nobody finds when they are working on that repo.

**If the label does not exist yet**, create it — but only in a repo the check above said
you can label:

```bash
[ -n "$(gh label list --repo OWNER/REPO --search manual-task --json name -q '.[].name')" ] \
  || gh label create manual-task --repo OWNER/REPO --color d93f0b \
       --description "Requires the repo owner at the keyboard — agent cannot proceed on its own."
```

Keep the name exactly as above. The label is the query surface — it is what
`gh search issues --label manual-task` and `ol owed` both key on — and a variant spelling
is invisible to both.

### 3. Check you are not filing a duplicate

```bash
gh issue list --repo OWNER/REPO --label manual-task --state open --json number,title,url
```

Two asks are the same when **one action discharges both**. A near-miss in the same area is
not a duplicate — file a new issue.

**If one matches, you comment on it instead of opening a second issue. Nothing else
changes.** A comment is published in the same place as a body, so it takes the same fields
and the same egress check. Keep going through steps 4–6, then swap the last command in
step 7 for the comment form shown there. Say what is *newly* blocked rather than
restating the issue:

```markdown
**Ask:** <unchanged, or the new action if the ask has grown>

**Blocks:** now also blocks <name what it now blocks>.

<details>
<summary>What I found</summary>

<what changed since the issue was filed>
</details>
```

If the ask has grown and the old predicate no longer covers it, say so and give the new
one — a predicate that passes while half the ask is outstanding is worse than none.

### 4. What goes in the body

Four fields are required. Put them at the top, unfolded, in this order.

```markdown
**Ask:** <one line, imperative, the action the human takes>

**Verify:** `<a shell command whose exit status is 0 once the ask is done>`

**Evidence:** <a plain URL, or a commit sha>

**Blocks:** <one line: what stops until this is done. "Nothing" is a valid answer.>

<details>
<summary>What I found</summary>

The failure output, the reasoning, the alternatives you ruled out.
</details>
```

**The title is the ask too** — imperative, under about 70 characters. `Set PYPI_PASSWORD
on the release repo so the publish job can authenticate`, not `CI secrets are not
provisioned`. The title is published exactly as the body is, so it goes through the same
egress check in step 7; do not hand-write it into the `gh` command.

**The Ask line is an action, not a description of the blockage.** The test: could the
human act on that line alone, without reading further?

| No | Yes |
|---|---|
| The publish job fails because the secret is unset. | Set `PYPI_PASSWORD` on `OWNER/REPO` so the publish job can authenticate. |
| We are unsure whether to publish this to PyPI. | Decide: publish `PACKAGE` to PyPI, or keep it GitHub-only. |
| I do not have access to the deployment host. | Add my key to the deploy user on the host, or run `<command>` yourself. |

**Evidence is a plain URL or a sha.** A PR, an issue, a failing run, a commit. **Never a
transcript path, never a session id, never a local file path.** Those rot — session
transcripts are garbage-collected within about a month — and they leak the machine. If
there is no URL, quote the two or three lines of failing output instead, and say where
they came from by repo and repo-relative path.

**Reopening a recorded decision? Five fields go above those four**, and the title starts
with the decision: `Reopen ADR-001: the gate costs more than the thing it gates`.

```markdown
**Decision:** <what was decided, and where — ADR number and link, or file and repo-relative path>

**What changed:** <new evidence, a cost that came out different, or the blocker it now causes>

**Options now:** <the live options as they look today, not as they looked then>

**Recommendation:** <name exactly one option, and why, in a sentence or two>

**Reverse vs keep:** <what unwinding costs, and what living with it costs>
```

**`Recommendation:` is the one you will skip, and it is the one that was asked for by
name.** A reopening with no preferred option hands the human the question *and* the work.
`Verify:` here is normally `none possible — a judgement call`; if the decision record
carries a `status` field, the predicate is that it no longer reads `questioned`.

### 5. Write the verify predicate

This is the field that stops the issue from becoming a lie, and the field `ol owed` runs.

Obligations get discharged **out of band**: someone adds a deploy key in a web UI, pays an
invoice, answers in chat. None of that emits an event anyone is listening to. The issue
then sits open for months describing something that was done in five minutes.

A predicate is good when:

- **its exit status is the answer** — `0` means done, non-zero means not done;
- **it checks the world, not the issue.** `gh issue view N --json state` is not a
  predicate: closing the issue is not doing the thing;
- **anyone can run it** with `gh` authenticated and nothing else. No local paths, no files
  on your machine, no state from this session;
- **it cannot pass by accident.** Prefer an exact match (`grep -qx NAME`) to a substring.

Worked examples, one per ask shape. Run yours before you write it down.

```bash
# A secret now exists on the repo
gh secret list --repo OWNER/REPO --json name -q '.[].name' | grep -qx PYPI_PASSWORD

# A pull request is merged
[ "$(gh pr view 42 --repo OWNER/REPO --json state -q .state)" = MERGED ]

# A version is published to PyPI
curl -fsS https://pypi.org/pypi/PACKAGE/json \
  | python3 -c 'import json,sys; sys.exit(0 if "1.2.3" in json.load(sys.stdin)["releases"] else 1)'

# A DNS record resolves
[ -n "$(dig +short sub.example.com)" ]

# An access grant landed — a deploy key on the repo
[ "$(gh api repos/OWNER/REPO/keys --jq length)" -gt 0 ]
```

**When no predicate is possible, say so in the field.** Some asks leave no observable
artifact: a decision between two designs, a purchase with no public receipt, an approval
given in conversation. Write it out.

```markdown
**Verify:** none possible — a judgement call with no observable artifact. Close by hand once decided.
```

**Never invent one.** A predicate that passes trivially is worse than an absent one: it
closes a live obligation silently, and the count is the whole product.

**Prose is not a predicate.** Only the command in the `**Verify:**` field is ever run.
A code span anywhere else in the body — in `**Ask:**`, in the `What I found` block, in a
comment — is illustration, and running it would execute a command nobody meant as a
check. Whatever reads this issue back must take the `**Verify:**` field and nothing else;
so must you, if you are ever the one reading it.

**Do not close the issue on your own judgement.** If you later find the predicate passes,
you may close it, quoting the command and its output in a closing comment. If you merely
believe it is done and the predicate does not pass, comment with what you saw and leave it
open for the human.

### 6. The egress rules — mandatory, and only partly automated

Two rules, deliberately asymmetric. They are the rules `openloops.egress` implements
(`scrub`, `find_credentials`, `CredentialFound`). Do not invent a second version of them.
Step 7 runs them over **both the title and the body**.

**Paths are rewritten, never a reason to stop.** A path is an identifier, not a secret.

- this machine's home → `~`;
- a home that is not this machine's — a server's, a CI runner's, a colleague's → `~other`,
  which keeps the tail and drops the identity;
- the dash-encoded form of a home path is just as identifying and gets rewritten too.
  Coding agents turn `/`, `_` and `.` into `-` when they encode a working directory into
  a directory name, and that form appears throughout transcripts.

**`scrub` rewrites home paths and nothing else. Every other absolute path is yours.**
This is the part that is easy to get wrong, because `scrub` returns cleanly either way. A
path rooted anywhere but a home directory — a system config, a log, a mount, a scratch
dir — reaches GitHub exactly as you typed it. So step 7 adds its own check and **refuses
to file while one is left**, naming each. Replace them and re-run the block. The one case
where the match is not a local path at all — a URL path, an API route, a line of quoted
config caught by the pattern — is what `NEEDS_HUMAN_PATHS_REVIEWED=1` in front of
`python3` is for; use it only after reading the list.

What to write instead:

| instead of | write |
|---|---|
| a path inside a checkout | `owner/repo` plus the repo-relative path |
| a path on a server or a runner | the role, not the location — "the platform config on the deploy host" |
| a system path that *is* the name of the thing (an nginx config, a unit file) | keep it, but never next to a hostname, an IP, or a username |
| a scratch or temp path | drop it. It will not exist tomorrow and it names nothing a reader needs. |

Better than rewriting anything: **do not put a path in at all.** Name the repo by
`owner/repo` and the file by its repo-relative path. That says everything a reader needs
and leaks nothing.

**Credentials make you stop.** On anything credential-shaped — a vendor-prefixed token
(a `ghp_`/`sk-ant-`/`AKIA`/`glpat-`/`xox`/`pypi-`/`hf_` prefix), a JWT, a private-key
block, a `KEY = <long opaque value>` assignment, a password inside a URL's authority —
**raise it with the human and refuse to file until they hand you safe wording.**

Do not redact it. Do not mask it. Do not write `<REDACTED>` and file anyway. A silent
redaction hides the fact that a secret was one keystroke from being published, which is
the fact somebody needs. And **never quote the matched text** — not in the issue, not in a
comment, not in your message to the human. Say what kind of thing it was, and where.

**If there is no human in the session to raise it with** — an unattended run — do not
file that draft and do not file a masked version of it. Rewrite the ask so the
credential-shaped text is not needed at all; you almost never have to quote a secret to
ask someone to set one. Re-run the block, file only if it now passes, say in the issue
that the draft was rewritten because it contained credential-shaped text, and say the
same in your closing message. The point of the rule is that nobody finds out silently.

Also on you, and *not* covered by `openloops.egress`: **no hostnames or internal URLs, no
personal contact details.** Use `example.com` in illustrations.

### 7. Write it, scrub it, file it — ONE Bash call

**Run this block top to bottom in a single Bash call.** Shell variables do not survive
between calls in most agent harnesses — `D` set in one call is empty in the next, which
scrubs nothing and files an empty body. Nothing here needs a second call; do not split it.

Fill in `REPO`, the title and the body. Both heredocs are quoted (`<<'TITLE'`, `<<'BODY'`),
so `$`, backticks and `!` inside them stay literal — write your verify predicate exactly
as it should appear. Replace every `<...>` placeholder; the block refuses to file while one
is left. Filing in the fallback repo (step 2)? Add the `**Affected repo:**` line above the
`**Ask:**` line.

```bash
REPO=OWNER/REPO                # from step 2 — the repo you are allowed to file in
D=$(mktemp -d)

cat > "$D/title.txt" <<'TITLE'
<the ask, imperative, under ~70 characters>
TITLE

cat > "$D/body.md" <<'BODY'
**Ask:** <one line, imperative>

**Verify:** `<command whose exit status is 0 once the ask is done>`

**Evidence:** <a plain URL, or a sha>

**Blocks:** <one line, or "Nothing">

<details>
<summary>What I found</summary>

<the failure output, the reasoning, the alternatives you ruled out>
</details>
BODY

# Egress check. Rewrites title and body IN PLACE on success; on a credential it changes
# nothing, exits non-zero, and the `||` below stops the filing.
python3 - "$D" <<'PY' || { echo "REFUSED — fix the draft, then re-run this whole block."; exit 1; }
import os, re, sys
from pathlib import Path
import openloops.egress as e

d = Path(sys.argv[1])
aliases = e.default_aliases()
#: What `scrub` does NOT touch: an absolute path that is not one of the home roots.
OTHER_ABS = re.compile(r"(?<![\w~.:/-])/(?!/)[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+")

clean = {}
for name in ("title.txt", "body.md"):
    try:
        clean[name] = e.scrub((d / name).read_text(), aliases=aliases, where=name)
    except e.CredentialFound as exc:
        sys.exit(f"REFUSE: {exc}\nAsk the human for safe wording; do not redact and file.")

if "**Verify:**" not in clean["body.md"]:
    sys.exit("REFUSE: the body has no `**Verify:**` field. Add one — a shell command "
             "whose exit status is 0 once the ask is done, or the literal words "
             "`none possible` and why (step 5).")

#: Angle-bracket placeholders copied out of the template and never filled in. Cheap to
#: check and the commonest way a hurried filing goes out empty of content.
#: A space inside the brackets is what separates a placeholder from `<details>`,
#: `<summary>` or a type like `Dict<str, int>` (excluded by the lookbehind).
stub = re.compile(r"(?<!\w)<[a-z][^<>\n]*\s[^<>\n]*>")
holes = [f"  {name}: {m.group(0)}"
         for name, text in clean.items() for m in stub.finditer(text)]
if holes:
    sys.exit("REFUSE: unfilled template placeholders:\n" + "\n".join(holes)
             + "\nWrite the real text and re-run this block.")

left = [f"  {name}:{n}  {m.group(0).rstrip('.,;:')}"
        for name, text in clean.items()
        for n, line in enumerate(text.splitlines(), 1)
        for m in OTHER_ABS.finditer(line)]
if left and not os.environ.get("NEEDS_HUMAN_PATHS_REVIEWED"):
    sys.exit("REFUSE: absolute paths `scrub` does not rewrite (step 6):\n"
             + "\n".join(left)
             + "\nReplace each one — a repo-relative path, or the role rather than the "
               "location — and re-run this block. If you have checked and none of them is "
               "a local path (a URL path, an API route, a line of quoted config), re-run "
               "with NEEDS_HUMAN_PATHS_REVIEWED=1 in front of `python3`.")

for name, text in clean.items():   # nothing is overwritten until every check has passed
    tmp = d / (name + ".tmp")
    tmp.write_text(text)
    tmp.replace(d / name)
PY

gh issue create --repo "$REPO" --label manual-task \
  --title "$(cat "$D/title.txt")" --body-file "$D/body.md"
```

**Commenting on a duplicate instead (step 3)?** Same block, one line different: put the
comment in `$D/body.md`, put anything in `$D/title.txt` (it is not published), and end with

```bash
gh issue comment N --repo "$REPO" --body-file "$D/body.md"
```

Four things the block will not let you do: publish after a credential match, publish a
body with no `**Verify:**` field, publish an absolute path `scrub` could not rewrite, and
publish an unfilled `<...>` placeholder. Each exits non-zero, leaves the draft untouched,
and stops before `gh` runs.

**`python3` must be the interpreter that has `openloops` installed.** Usually it is.
Check before you rely on it, from the directory you will run the block in — an
interpreter resolved from a temp directory or a system path is often a different one:

```bash
python3 -c 'import openloops' && echo "the egress check will run"
```

If that fails, the block will fail on `ModuleNotFoundError: openloops` and leave your
draft untouched. Use whichever interpreter you installed openloops with in place of
`python3`. If you cannot get the import to work at all, apply the rules of step 6 by
eye rather than skipping them — they are the rules, and the code is only the enforcement.

If `gh issue create` errors on the label, check whether an issue was created anyway before
retrying, so you do not file the same ask twice.

## After filing

Put the issue URL in your closing message, on one line, next to the ask. The issue is
where the obligation lives; the message is how the human learns today that it exists.

Do not also write a handoff file, a TODO comment, or a roadmap note about the same ask.
One record, one place.

**Optional, if the human wants to count agent-filed asks separately** from ones they
opened by hand: agree on a fixed marker — an HTML comment such as `<!-- needs-human -->`
as the body's last line — and put it in every body and every comment. It renders as
nothing, carries no information about the machine or the session, and is the only thing
that distinguishes the two, since `gh issue create` runs under the human's own
credentials either way. Nothing in `openloops` reads it; the label and the `**Verify:**`
field are what it keys on.
