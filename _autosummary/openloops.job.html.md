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

| [`DFLT_LABEL`](#openloops.job.DFLT_LABEL)    | launchd job label.     |
|----------------------------------------------------------------|------------------------|
| [`DFLT_INTERVAL`](#openloops.job.DFLT_INTERVAL) | Seconds between ticks. |

### Functions

| [`install`](#openloops.job.install)(\*[, label, interval, dry_run])      | Install (or replace) the periodic sync job.                                  |
|-----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`uninstall`](#openloops.job.uninstall)(\*[, label])                       | Unload the job and remove its plist.                                         |
| [`job_status`](#openloops.job.job_status)(\*[, label])                      | Installed? loaded? and — the question that matters — when did it last write? |
| [`plist_xml`](#openloops.job.plist_xml)(\*, label, program_args, env, ...) | The launchd property list, as text.                                          |

### openloops.job.DFLT_INTERVAL *= 900*

Seconds between ticks. A digest is a record of what a session said, so being a
quarter of an hour behind costs nothing; running every few seconds would cost a
full scan of the transcript directory for no gain.

### openloops.job.DFLT_LABEL *= 'openloops.sync'*

launchd job label. Also the plist filename and the log filename.

### openloops.job.install(, label='openloops.sync', interval=900, dry_run=False)

Install (or replace) the periodic sync job. Returns the paths it wrote.

A smoke run follows the bootstrap, because a job that cannot start produces exactly
the same silence as a job with nothing to do.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### openloops.job.job_status(, label='openloops.sync')

Installed? loaded? and — the question that matters — when did it last write?

`launchctl list` says the job is registered, which is not the same as the job
doing anything. The cache’s modification time is the only evidence that a tick
completed, so it is reported alongside.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`object`](https://docs.python.org/3/builtins/functions.html#object)]

### openloops.job.plist_xml(, label, program_args, env, interval, log_path)

The launchd property list, as text. Pure, so it can be tested on any platform.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> xml = plist_xml(label='x', program_args=['a'], env={'HOME': '/h'},
...                 interval=60, log_path=Path('/tmp/x.log'))
>>> '<key>StartInterval</key>' in xml and '<integer>60</integer>' in xml
True
```

### openloops.job.uninstall(, label='openloops.sync')

Unload the job and remove its plist. Idempotent.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
