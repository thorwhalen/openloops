# Classify open items for the owner's phone task board

## Owner context (fill this in before handing the brief out)

The owner is away from their desk, on a **phone**. They can use a mobile browser and apps (GitHub Mobile etc.) and talk to Claude Code sessions on these machines through Remote Control: `<machine names, and which owners' work runs on each>`. Out of bounds: `<e.g. anything needing the Mac>`. Repository paths for prompts: `<how a repo maps to a local checkout, e.g. $PP/<letter>/<repo>>`.

You get a batch file (JSON list of candidate GitHub issues/PRs). For **each** item, read it and write one record. Write the full list of records as a JSON array to the output path you were given. Return only a 3-line summary (counts per tier, anything odd). Never return the records in your reply.

## How to read an item

`gh issue view <number> -R <repo> --json state,body,comments,labels --jq '{state, body: .body[0:7000], comments: [.comments[-4:][] | {author: .author.login, body: .body[0:1500]}]}'` (for PRs use `gh pr view ... --json state,body,comments,reviewDecision,mergeable,statusCheckRollup,isDraft,files --jq ...`, trim the same way; for statusCheckRollup only keep conclusions). Do the reads in a shell loop to save turns. **Strictly read-only**: never comment, close, label, merge or approve anything. Never write anything outside your output file.

## Record shape (all keys present; use null / [] when not applicable)

```json
{
  "id": "acme/widget#260",
  "url": "https://github.com/acme/widget/issues/260",
  "kind": "issue",                       // or "pr"
  "org": "acme", "repo": "widget",
  "title": "<original title>",
  "ask": "One plain-language line: what the owner has to do. Imperative, <= 120 chars.",
  "tier": "tap",                         // tap | browser | session | physical | mac-only
  "minutes": 2,                          // honest estimate for the owner's own time
  "links": [{"label": "npm: trusted publisher settings", "url": "https://..."}],
  "decision": {"question": "...", "options": ["A: ...", "B: ..."], "recommendation": "B, because ..."},
  "prompt": "Paste-ready prompt for a Claude session, or a shell command (session tier only)",
  "machine": "<machine>",                // where a session item runs, from Owner context; null if none
  "unblocks": ["what finishing this unblocks: issue ids or short phrases"],
  "pattern": "npm-trusted-publisher",    // controlled vocabulary below
  "pattern_key": "widget",           // e.g. the npm/PyPI package name or service; null if none
  "status": "open",                      // open | likely-done | not-for-user | stale
  "note": "<= 200 chars: caveats, e.g. which comment says it is half-done"
}
```

### Tiers
- `tap`: answer a decision with a comment, or approve/merge a PR, under ~2 minutes on GitHub Mobile.
- `browser`: a web console on the phone browser: npm, PyPI, GitHub settings, cloud consoles, creating an API key on some service.
- `session`: have a Claude session on one of the owner's machines do it, or run a command there (including ssh-style server chores, deploys, runs of a live check with a key already on the server).
- `physical`: record audio/video, test on a device, listen to or look at something and judge it.
- `mac-only`: needs the Mac (macOS app, desktop Claude app, Keychain, files only on the Mac, local Mac hardware).
If an item needs two steps (e.g. create a key in a browser, then a session stores it and runs a check), pick the tier of the step the owner does by hand (`browser`), and put the session part in `prompt`.

### `decision`
For decisions only. Copy the options and the recommendation **from the issue or its comments**; if the issue gives options but no recommendation, set recommendation to null — do not invent one. null for non-decisions.

### `links` — deep links, never navigation instructions
The exact page where the action happens. Known patterns:
- npm package settings (trusted publisher / publishing access / 2FA requirement): `https://www.npmjs.com/package/<pkg>/access` (scoped: `https://www.npmjs.com/package/@scope/name/access`)
- npm org / scope: `https://www.npmjs.com/org/<scope>`; create an org: `https://www.npmjs.com/org/create`; npm tokens: `https://www.npmjs.com/settings/<npm-user>/tokens` (only if the issue names the npm user)
- PyPI trusted publisher, existing project: `https://pypi.org/manage/project/<name>/settings/publishing/`; new project (pending publisher): `https://pypi.org/manage/account/publishing/`
- GitHub: repo Actions secrets `https://github.com/<o>/<r>/settings/secrets/actions`; variables `.../settings/variables/actions`; environments `.../settings/environments`; Pages `.../settings/pages`; Actions settings `.../settings/actions`; PR review `https://github.com/<o>/<r>/pull/<n>/files`; a specific comment's URL when the decision is in a comment.
- Any service console URL the issue names (ElevenLabs, Hugging Face tokens `https://huggingface.co/settings/tokens`, Shopify, Etsy, Cloudflare, Hetzner, Google Cloud, etc.): give the most specific page you can justify.
Always include the issue/PR itself as the last link (label "Issue" or "PR").

### `prompt` (session tier, else null)
Self-contained, paste-ready, starts with what to do and names the issue URL, e.g. `On <machine>, in <repo checkout>: install the updated script per <issue URL>, run its Verify line, and comment the result on the issue.` Use the repository paths from "Owner context". `machine`: the machine that context names for the item's owner, unless the issue says otherwise. Never put a secret value into a prompt; say "the key I'll paste" instead.

### `pattern` vocabulary (pick one)
`npm-trusted-publisher` (configure OIDC trusted publishing on an existing package), `npm-first-publish` (a package that does not exist on npm yet needs a first publish / token), `npm-scope` (claim/create an npm org or scope), `npm-other`, `pypi-trusted-publisher`, `pypi-release`, `api-key` (create an account/key on a service and hand it over), `github-settings` (secrets, pages, actions, billing, repo settings), `server-chore` (run/install/deploy/approve on a server), `decision` (pick an option / give a go-ahead), `review-pr`, `merge-bot-pr` (dependabot-style bumps), `record` (record audio/video of yourself), `device-test` (try something on a phone/device), `listen-look` (judge audio/visuals), `live-check` (run something once with a real paid key/account), `purchase`, `mac-only`, `other`.

### `status`
- `likely-done`: a comment or the state shows the ask was done; say which in `note`.
- `not-for-user`: the item is labelled/title-matched but actually is agent work with nothing for the owner (common for items found by title "Decide…" without the manual-task label, and for PRs that only an agent needs to land: e.g. green CI, no review requested, nothing asked of the owner — but an open PR whose only remaining step is a human approve/merge counts as `open`).
- `stale`: very old and probably moot; say why.
- otherwise `open`.

### Rules
- Organisations the owner marked read-only for agents: still classify their items (the owner acts there by hand).
- Privacy: titles and asks may be private, fine. **Never copy a secret, token, password or key value** into any field.
- Be concise; the board is read on a phone.

The record shape is openloops' `Task` schema (`openloops.tasks.TASK_FIELDS`); `ol board-classify --enriched` merges these records over the heuristic ones and fixes any value outside a vocabulary to a safe default, so stay inside the vocabularies above.
