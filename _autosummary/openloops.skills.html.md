# openloops.skills

The agent-facing surface: two skills, one subagent, and the command that installs them.

The `ol` command is plumbing. What most people actually want is an agent that knows
how to use the plumbing and tells them what matters – “what is being done, and what
needs my attention?” – without their ever typing `ol owed`. That agent is a file:
a `SKILL.md` an agent host loads when the question comes up. So openloops ships three
of them, inside the package, and this module is how they get from the wheel to the host.

| `openloops`             | the **read** skill. Runs the three commands, and<br/>synthesises rather than pastes. The one to load.                                                                  |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `openloops-needs-human` | the **capture** skill. Without something filing<br/>`manual-task` issues, `ol owed` reads an empty<br/>list forever – which is the state a stranger<br/>installs into. |
| `openloops-sweep`       | a subagent: the same sweep in a fresh context,<br/>returning a page instead of three screens of output.                                                                |

**Nothing here is openloops-specific machinery.** A skill is a markdown file in a
directory an agent host reads; installing one is a symlink. The whole module is a
hundred lines because that is genuinely all it is, and the alternative – a copy of
each skill pasted into every user’s config – is a copy that goes stale the first time
`pip install -U openloops` lands.

Two decisions worth stating, because both are the kind that get quietly reversed:

**A symlink, not a copy.** The point is that upgrading the package upgrades the skill.
Copying is the *fallback*, taken only where symlinks are unavailable (Windows without
Developer Mode, where creating one needs a privilege an ordinary process lacks), and
the plan says which happened rather than pretending they are the same thing.

**Nothing already there is ever overwritten.** A destination holding something that is
not ours reads `conflict`: it is reported, not replaced, and `force=True` is the
only way past. Someone’s hand-written skill of the same name is theirs, and silently
eating it would be a worse failure than not installing at all.

This is deliberately *not* in [`openloops.tools`](openloops.tools.html.md#module-openloops.tools). That module is the list every
surface dispatches from – an MCP server, an HTTP endpoint – and “symlink files into
this machine’s agent config” is not an operation a remote surface could honestly offer.
It belongs beside [`openloops.job`](openloops.job.html.md#module-openloops.job), the other installer, which the CLI also wraps
directly.

```pycon
>>> skills_dir().name, agents_dir().name
('skills', 'agents')
>>> sorted(asset.name for asset in bundled())
['openloops', 'openloops-needs-human', 'openloops-sweep']
```

### Module Attributes

| [`HOST_ENV_VAR`](#openloops.skills.HOST_ENV_VAR)   | Where Claude Code keeps skills and subagents, and the variable that relocates it.   |
|-----------------------------------------------------------------|-------------------------------------------------------------------------------------|

### Functions

| [`agents_dir`](#openloops.skills.agents_dir)()                                  | The bundled subagent definitions, inside the installed package.                   |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`bundled`](#openloops.skills.bundled)()                                     | Every skill and subagent this package ships, sorted by name.                      |
| [`host_dir`](#openloops.skills.host_dir)([target])                            | The agent host's config directory: `target`, `CLAUDE_CONFIG_DIR`, or `~/.claude`. |
| [`install_skills`](#openloops.skills.install_skills)(\*[, target, only, copy, ...]) | Make the bundled skills and subagent visible to an agent host.                    |
| [`skills_dir`](#openloops.skills.skills_dir)()                                  | The bundled skills directory, inside the installed package.                       |

### Classes

| [`Asset`](#openloops.skills.Asset)(kind, name, source)   | One installable thing: a skill directory or a subagent file.   |
|------------------------------------------------------------------------------|----------------------------------------------------------------|

### *class* openloops.skills.Asset(kind, name, source)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One installable thing: a skill directory or a subagent file.

`name` is what the host will call it, and it is the file or folder name too –
the agent-skill spec requires the folder name to equal the skill’s `name:`, so
deriving one from the other cannot drift.

#### destination(host)

Where this asset goes under *host*.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.skills.HOST_ENV_VAR *= 'CLAUDE_CONFIG_DIR'*

Where Claude Code keeps skills and subagents, and the variable that relocates it.
Honoured rather than reimplemented: a user who has moved their config has done so
for a reason, and an installer that ignores it writes to a directory nobody reads.

### openloops.skills.agents_dir()

The bundled subagent definitions, inside the installed package.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### openloops.skills.bundled()

Every skill and subagent this package ships, sorted by name.

Discovered from the directories rather than listed here: a list would be a second
place to update, and the one that gets forgotten.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Asset`](#openloops.skills.Asset)]

### openloops.skills.host_dir(target=None)

The agent host’s config directory: `target`, `CLAUDE_CONFIG_DIR`, or `~/.claude`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

```pycon
>>> import os
>>> host_dir('/somewhere/else').name
'else'
```

### openloops.skills.install_skills(, target=None, only=None, copy=False, force=False, dry_run=False)

Make the bundled skills and subagent visible to an agent host. Idempotent.

Links each one into `target` (default: `CLAUDE_CONFIG_DIR` or `~/.claude`) so
that upgrading the package upgrades the skill. `copy=True` takes a copy instead,
which is also what happens by itself where symlinks are unavailable.

Returns the plan it carried out – one row per asset, each carrying its verdict and
the reason for it. `dry_run=True` returns the same plan having touched nothing,
which is the only way to see what a run would do *before* it does it.

Nothing that is already there is overwritten: an occupied destination reads
`conflict` and is left exactly as it was until `force=True`.

`only=` installs a subset by name. The case it exists for: you already have your
own capture skill, adapted to your own fleet, and a second one competing for the same
triggers is worse than either alone – so take the reader and the subagent and leave
the capture skill out.

* **Return type:**
  dict[str, Any]

```pycon
>>> plan = install_skills(target='/nonexistent/host', only=['openloops'], dry_run=True)
>>> [row['name'] for row in plan['actions']]
['openloops']
```

```pycon
>>> plan = install_skills(target='/nonexistent/host', dry_run=True)
>>> plan['counts']['install'], plan['dry_run']
(3, True)
>>> sorted({row['action'] for row in plan['actions']})
['install']
```

### openloops.skills.skills_dir()

The bundled skills directory, inside the installed package.

`Path(__file__).parent` rather than a configured root, so this answers correctly
from a wheel, an editable install, a zip and a virtualenv without being told which.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
