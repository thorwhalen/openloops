# openloops.job

The periodic job: launchd runs `ol sync`, writes, and exits. No daemon.

ADR-003’s decision, applied to digests. A resident process would have to be kept alive,
and when it dies its output latches at whatever it last wrote — a confident, months-old
answer with nothing scheduled to correct it. A `StartInterval` job is self-healing by
construction: a tick that crashes is repaired by the next one, and the only thing to
supervise is launchd itself.

The environment is captured at install time and pinned into the plist, because launchd
hands a job a nearly empty environment. The interpreter is invoked directly rather than
by console-script name, for the same reason: a name resolved against a minimal `PATH`
is a lottery whose losing ticket is a job that dies instantly, every tick, silently.

macOS only. On Linux the equivalent is a systemd user timer or a crontab line running
the same command, and [`install()`](#openloops.job.install) says so rather than pretending.

### Module Attributes

| [`DFLT_LABEL`](#openloops.job.DFLT_LABEL)        | launchd job label.                                 |
|--------------------------------------------------------------------|----------------------------------------------------|
| [`DFLT_INTERVAL`](#openloops.job.DFLT_INTERVAL)     | Seconds between ticks.                             |
| [`RECEIVER_LABEL`](#openloops.job.RECEIVER_LABEL)    | launchd label of the board-receiver job (ADR-011). |
| [`RECEIVER_INTERVAL`](#openloops.job.RECEIVER_INTERVAL) | Seconds between receiver ticks.                    |

### Functions

| [`install`](#openloops.job.install)(\*[, label, interval, dry_run])        | Install (or replace) the periodic sync job.                                  |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`install_receiver`](#openloops.job.install_receiver)(work_dir, \*[, dry_run])      | Install (or replace) the board-receiver job.                                 |
| [`receiver_job_spec`](#openloops.job.receiver_job_spec)(work_dir, \*[, claude, ...]) | The receiver job as data: program arguments, environment, plist.             |
| [`uninstall`](#openloops.job.uninstall)(\*[, label])                         | Unload the job and remove its plist.                                         |
| [`job_status`](#openloops.job.job_status)(\*[, label, env_file])              | Installed? loaded? and — the question that matters — when did it last write? |
| [`plist_xml`](#openloops.job.plist_xml)(\*, label, program_args, env, ...)   | The launchd property list, as text.                                          |

### openloops.job.DFLT_INTERVAL *= 900*

Seconds between ticks. A digest is a record of what a session said, so being a
quarter of an hour behind costs nothing; running every few seconds would cost a
full scan of the transcript directory for no gain.

### openloops.job.DFLT_LABEL *= 'openloops.sync'*

launchd job label. Also the plist filename and the log filename.

### openloops.job.RECEIVER_INTERVAL *= 300*

Seconds between receiver ticks. A tick that finds nothing pending costs a few HTTP
calls and no model, so this can be as short as the phone board’s latency wants.

### openloops.job.RECEIVER_LABEL *= 'openloops.board-receiver'*

launchd label of the board-receiver job (ADR-011).

### openloops.job.install(, label='openloops.sync', interval=900, dry_run=False)

Install (or replace) the periodic sync job. Returns the paths it wrote.

A smoke run follows the bootstrap, because a job that cannot start produces exactly
the same silence as a job with nothing to do.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### openloops.job.install_receiver(work_dir, , dry_run=False, \*\*kwargs)

Install (or replace) the board-receiver job. Returns the paths it wrote.

`kwargs` are those of [`receiver_job_spec()`](#openloops.job.receiver_job_spec). A dry run builds and returns the
plist without touching launchd and without requiring the credentials file.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### openloops.job.job_status(, label='openloops.sync', env_file=PosixPath('~/.config/openloops/board-receiver.env'))

Installed? loaded? and — the question that matters — when did it last write?

`launchctl list` says the job is registered, which is not the same as the job
doing anything. The cache’s modification time is the only evidence that a tick
completed, so it is reported alongside. For the receiver, `last_check` is the
last tick whose check succeeded (a stamp beside *env_file*) and `last_write` the
last tick that had work (its log).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`object`](https://docs.python.org/3/builtins/functions.html#object)]

### openloops.job.plist_xml(, label, program_args, env, interval, log_path, working_dir=None)

The launchd property list, as text. Pure, so it can be tested on any platform.

```pycon
>>> xml = plist_xml(label='x', program_args=['a'], env={'HOME': '/h'},
...                 interval=60, log_path=Path('/tmp/x.log'))
>>> '<key>StartInterval</key>' in xml and '<integer>60</integer>' in xml
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### openloops.job.receiver_job_spec(work_dir, , claude=None, model='sonnet', max_budget_usd=1.0, allowed_tools='Bash(gh:\*) Bash(curl:\*) Bash(python3:\*) Bash(crowsnest:\*) Bash(mkdir:\*) Bash(date:\*) Bash(set:\*) Bash(umask:\*) Bash(source:\*) Bash(jq:\*) Bash(cat:\*) Bash(ls:\*) Bash(shasum:\*) Bash(vm_stat:\*) Bash(sysctl:\*) Read Write Edit Glob Grep Skill', env_file=PosixPath('~/.config/openloops/board-receiver.env'), interval=300, label='openloops.board-receiver', require_claude=True)

The receiver job as data: program arguments, environment, plist. Pure but for
looking up where `claude` and `node` are, so it can be tested anywhere.

The job runs `python -m openloops.receiver_tick`, which asks the board store
whether anything is pending and only then replaces itself with `claude -p` and the
packaged receiver prompt. The credentials stay in *env_file*; nothing about them
is in the plist, the arguments or the environment (`PASSED_THROUGH` names none).
With `require_claude=False` (a dry run) a missing `claude` is shown as a bare
name instead of refused.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`object`](https://docs.python.org/3/builtins/functions.html#object)]

### openloops.job.uninstall(, label='openloops.sync')

Unload the job and remove its plist. Idempotent.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
