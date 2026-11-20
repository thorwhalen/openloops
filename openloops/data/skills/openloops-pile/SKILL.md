---
name: openloops-pile
description: "The owner's capture pile (one GitHub issue per thing they said to Siri, 'Add to My Pile', in a private pile repo): say what is on it, clarify each item into where it belongs (a loop via `ol remind`, an idea via `ideadump`, an issue in the repo that owns it, work handed to a session, or dropped with a reason), and take care of one item end to end. Proposes first, acts only on the owner's yes, signs every comment with the agent's name and session link. Use on 'what's on my pile', 'tell me about my pile', 'go through my pile', 'dispatch my pile', 'triage my pile', 'take care of pile item N', 'work on that pile item', 'process my captures', 'empty my inbox' (the GTD In list), and for a session handed a pile item ('report progress on the pile item'). Not for capturing (the Siri Shortcut or a new issue on the pile repo) nor for reminders asked for directly (openloops-remind)."
metadata:
  audience: agents
  decided: "2026-11-20: capture into a private GitHub issue pile; triage on demand, never automatic; openloops reads and plans, the caller writes (ADR-014); every agent comment signed with name + session link"
---

# openloops-pile: say what's there, clarify it, take care of it

The **pile** is GTD's *In* list: the owner says "Hey Siri, add to my pile", and the capture lands as one issue labelled `pile` in a private repo. Nothing happens to it until someone asks. Three asks, one core (`ol pile*`, ADR-014):

| The owner says | You do |
|---|---|
| "what's on my pile", "tell me about my pile" | §1, read-only |
| "go through / dispatch / triage my pile" | §1, §2, §3 for every item |
| "take care of pile item N", "work on that one" | §2, §3 for that item, then §4 |

## 1. See it (read-only)

```bash
ol pile                 # oldest first: number, age, hint, the words
ol pile-show N          # one item with its comments: who handled it, where it went
```

Summarise in a few lines: the count, the oldest age, and one short line per item. The pile repo is `OPENLOOPS_PILE_REPO`, else `<gh login>/_pile`. Its README holds the owner's **routing map** (hint label → repo); read it before routing: `gh api "repos/$(ol pile -j | jq -r .repo)/readme" -q .content | base64 -d`. The repo is private and so is the README: nothing from either goes into a public repo.

## 2. Read and propose

The body is raw speech-to-text. **Never edit it**: it is the source. Read it as the owner meant it. Package names are the usual casualties ("zoe dal" is `zodal`, "cross nest" is `crowsnest`): check a guess with `projreg search "<word>"` or `rg -il <stem> "$PTH_FILEPATH"`, and say which words you resolved. `ol pile-propose` gives a free first guess per item (loop / idea / issue / ask). Replace it with your reading.

| It is | kind | the plan needs |
|---|---|---|
| a step the owner will do, at a time | `loop` | `--title`, `--when` (the openloops-remind skill's table and `--reveal` rule) |
| a step the owner will do, no time | `loop` | `--title` (listed on Next, never pushed) |
| work for a repo | `issue` | `--target-repo`, `--title`, `--issue-body` (see privacy) |
| work an agent should do now | `issue` or `work`, then §4 | `--reason` names who takes it |
| an idea for later | `idea` | `--tags`; the words go verbatim |
| unclear | `ask` | `--reason` = the one question; the item stays, labelled `needs-owner` |
| done already, duplicate, noise | `done` / `drop` | `--reason` = the evidence, or why |

Show one table, one row per item, with your recommendation in every row, then one question with a default: "Go with these? (yes / change N)". **Nothing happens before that yes.** On voice: the count, then one item per sentence, five at most.

**Privacy.** The pile is private; a destination may be public. `plan` checks the target's visibility. A public issue gets only your `--issue-body`, written so any user of that package could read it: the technical ask only, never the dictation, a person, a client or why the owner wants it. The pile item links to it, never the reverse.

## 3. Act on the yes: plan, then run the steps

```bash
ol pile-plan N <kind> --reading "<your reading, resolved words included>" [kind's options] > plan.json
```

The plan is signed: `Agent:` is `--by` (default `OPENLOOPS_AGENT`, else this Claude Code session), and `Claude-Session:` is this session's link (on public repos the name only). **Use your crowsnest name for `--by`** when you have one (`<name>@<home>`). Run the steps in order. Whatever the first step produced (an issue URL, a loop id, an idea id) replaces `{result}` in later steps:

| op | run |
|---|---|
| `remind` | `ol remind "<title>" [--when W] [--reveal] --source <source>` → the loop id |
| `idea` | `ideadump add "<words>" --title … --summary … --tags … --source <source>` → the idea id |
| `create_issue` | `gh issue create -R <repo> --title "<title>" --body-file <body in a file>` → the URL |
| `comment` | `gh issue comment <number> -R <repo> --body-file <body in a file>` |
| `labels` | `gh issue edit <number> -R <repo> --add-label <each add> --remove-label <each remove>` |
| `close` | `gh issue close <number> -R <repo> --reason "<reason>"` |

Bodies go through `--body-file` (a file in your scratch directory), never inline on the command line: the dictation is data, not shell. Report to the owner in a few lines: how many went where, which wait on them (`needs-owner`), and the pile's count now.

## 4. Take care of an item: hand it to a session

After the owner's yes, the item goes to the session that will develop it:

1. Route it (`issue` in the owning repo when there is one), or plan `work` with `--reason "handed to <session name>"`: the item stays open, labelled `working`.
2. Hand it off with the **crowsnest-dispatch** skill: the brief names the pile item URL, the routed issue, and §5 below as the reporting rule.

## 5. When you are the session working on a pile item

Post progress where the owner will look for it, signed, so the idea's development traces back to you:

```bash
ol pile-sign "<what you did, found or decided, and why>" --by <your name> > note.md
gh issue comment <N> -R <pile repo> --body-file note.md
```

Sign the routed issue's comments the same way (on a public repo, `ol pile-sign … --public`: the name only). When it is finished, `ol pile-plan N done --reason "<evidence: PR, commit, link>"` and run the steps.

## Nudges

`ol pile-nudge` (every six hours once `ol install-pile-nudge-job` is installed) keeps one reminder pending while any item is older than three days: "Pile: 4 waiting, oldest 6d" at 09:00. It never acts on an item, and nothing else runs on capture.

## Capture, for completeness

The Shortcut "Add to My Pile" posts `{title, body, labels: ["pile", <hint>]}` with a token scoped to the pile repo's issues and adds the hint as a last body line (`— pile: <hint>`). Its name is its Siri phrase. A short one ("Pile it") was not recognised by voice (2026-11-20). An agent piles only what the owner said, never its own ideas.
