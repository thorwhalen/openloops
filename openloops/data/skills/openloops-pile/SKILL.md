---
name: openloops-pile
description: "Go through the owner's capture pile (one GitHub issue per thing they said to Siri or typed on the go, in a private pile repo) and clarify each item into where it belongs: a loop in openloops (`ol remind`), an idea (`ideadump`), an issue in the repo that owns it, or dropped with a reason. Proposes a table first, acts only after the owner says yes, and closes each pile item with a comment saying where it went. Use on 'dispatch my pile', 'go through my pile', 'triage my pile', 'what's in my pile', 'process my captures', 'empty my inbox' (the GTD In list), 'clarify my captures', 'what did I pile'. Not for capturing a new item (that is the Siri Shortcut, or `gh issue create` on the pile repo) and not for reminders the owner asks for directly (openloops-remind)."
metadata:
  audience: agents
  decided: "2026-11-20: capture into a private GitHub issue pile, triage on demand by an agent, no GitHub Actions; the pile is GTD's In list and feeds openloops loops rather than sitting beside them"
---

# openloops-pile: empty the In list, one clarified item at a time

The **pile** is GTD's *In* list. The owner throws things into it from anywhere ("Hey Siri, pile it", a dictated sentence, an optional routing hint), and it lands as one issue in a private repo. Your job is the *clarify* step: decide what each item is and move it to the place that will hold it. The pile only works if it is emptied, and if nothing in it is ever lost: every item ends either somewhere else, with a link, or dropped with a reason.

## 0. Find the pile

```bash
PILE="${OPENLOOPS_PILE_REPO:-$(gh api user -q .login)/_pile}"
gh issue list -R "$PILE" --label pile --state open --limit 100 --json number,title,body,labels,createdAt,url
```

The pile repo's own `README.md` holds the owner's **routing map**: which hint label goes to which repo or corpus, and any standing rules. Read it first (`gh api "repos/$PILE/readme" -q .content | base64 -d`). It is private, so it may name clients and projects; nothing from it goes into a public repo.

Labels: `pile` = captured, not yet triaged. A **hint** label (`inbox`, `equerry`, `cosmograph`, ...) is the owner's routing guess at capture time; a hint is a guess, not an order. The Shortcut also writes the hint as a last body line (`— pile: <hint>`), in case the label was dropped. `needs-owner`, `routed`, `dropped` are the outcomes below.

## 1. Read each item as dictation

The body is raw speech-to-text. **Never edit the issue body**: it is the source. Read it the way the owner meant it:

- Package and project names are the usual casualties ("zoe dal" is `zodal`, "cross nest" is `crowsnest`, "dole" is `dol`). Check a guess against the fleet: `projreg search "<word>"`, `priv pkg list-packages | rg -i <stem>`, or `rg -il <stem> "$PTH_FILEPATH"`.
- Say which words you resolved, so a wrong guess is visible ("'cross nest' read as crowsnest").
- If one slip changes the meaning and you cannot tell, it is a question for the owner (step 3), not a guess.

## 2. Clarify: what is it?

David Allen's question, then the place:

| It is | It goes to | How |
|---|---|---|
| A step **the owner** will do, with a time | a loop that pushes at that time | `ol remind "<title>" --when <when> --source <pile issue url>` (the openloops-remind skill: its `--when` table and its `--reveal` rule) |
| A step the owner will do, no time | a loop on Next, listed, never pushed | `ol remind "<title>" --source <pile issue url>` |
| Work for **an agent or a repo** | an issue in the repo that owns it | `gh issue create -R <owner/repo> ...` with your reading, linking the pile item (see the privacy rule below) |
| An **idea** for later, not a commitment | ideadump | `ideadump add "<the dictation, verbatim>" --title ... --summary "<your reading>" --source <pile issue url>` |
| Something to keep, not to do (a fact, a link) | reference, where the owner keeps such things | name the place you propose; ask once if there is none |
| Already done, a duplicate, or noise | dropped | close with the reason |

One pile item may become two things (an idea *and* a next step); say so.

**The privacy rule.** The pile is private; the destination may not be. Check `gh repo view <repo> --json visibility -q .visibility`. For a **public** repo, write the issue in terms any user of that package could read: the technical ask only, never the raw dictation, a person, a client, or why the owner wants it. The full words stay in the pile item, which you link only from the private side (comment on the pile item with the new issue's URL; do not link the pile from the public issue). Prefer creating a new issue to `gh issue transfer`: a transfer moves the raw words, and GitHub refuses private-to-public transfers anyway.

**Do not dispatch work from here.** Routing an item to a repo files an issue; whether a session picks it up is the owner's call (or the lookout's, through the crowsnest-dispatch skill, when the owner says "and get someone on it").

## 3. Propose, then act on one "yes"

Never act on a pile item before the owner has seen the plan. Show one table, one row per item, a recommendation in every row:

```
#  | said (short)                       | reading                         | proposed
12 | "remind me to call the zoe dal..." | call about zodal release, Fri   | ol remind, Fri 2026-11-27 09:00
13 | "idea a podcast about..."          | podcast idea on agent fleets    | ideadump, tags: podcast, fleet
14 | "cosmograph the label overlap..."  | label overlap bug in cosmograph | issue in <repo> (public: technical text only)
```

Then one short question with a default: "Go with all of these? (yes / change N)". The owner's "yes" covers the table as shown; a change to one row does not reopen the others. For an item you cannot place, say so in its row with your best guess and mark it `needs-owner`: it stays in the pile, labelled, with your question as a comment, and the rest proceed.

**Voice (bosun):** read the count, then one item at a time, each as one sentence with its proposed place, and take "yes", "skip" or a correction per item. Five at a time at most; the rest wait for next time.

## 4. Close the loop on each item

After the destination exists, on the pile item:

```bash
gh issue comment <n> -R "$PILE" --body "<reading, one or two lines>. Resolved words: <...>. → <link to the loop id / issue url / idea id>"
gh issue edit <n> -R "$PILE" --remove-label pile --add-label routed
gh issue close <n> -R "$PILE" --reason completed
```

A drop is the same with `dropped`, `--reason "not planned"`, and the reason in the comment ("duplicate of #9", "done already: <evidence>"). **Never close an item without a comment**: a silent drop is the one failure the trusted system cannot survive (openloops' GTD trust rules: never drop silently, every agent-made item traces to its source, done needs evidence).

Then report to the owner in a few lines: how many items went where, which ones wait on them (`needs-owner`), and the pile's count now.

## Capture, for completeness

The owner captures with an Apple Shortcut that `POST`s to `https://api.github.com/repos/<pile>/issues` with `{title, body, labels: ["pile", <hint>]}`, using a fine-grained token scoped to the pile repo with Issues read and write only. An agent that needs to pile something the owner said (not something it thought of) does the same with `gh issue create -R "$PILE" --label pile --title ... --body ...`. Agents do not pile their own ideas: a proposal from an agent goes on the board or in an issue, marked as a proposal.
