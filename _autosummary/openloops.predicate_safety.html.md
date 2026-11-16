# openloops.predicate_safety

Is a `manual-task` verify predicate a pure read?

`ol owed` *executes* the shell command an issue carries, to see whether the ask has
been done since. A question (“what do I owe?”) must not have a write effect, but a
predicate is free text from an issue body: one ran `gh workflow run` and every
`ol owed` started a deploy (openloops#43).

[`write_effect()`](#openloops.predicate_safety.write_effect) is the guard. It returns the reason a command is refused, or
`""` for one that reads. It is a **guard against honest mistakes, not a sandbox**: a
predicate that hides a write behind a script it calls still runs. What it does see, it
sees as the shell would: the command is split into shell words ([`shlex`](https://docs.python.org/3/library/shlex.html#module-shlex)), then
into simple commands at unquoted `|`, `;`, `&&`, `||`, `&` and newlines, and
`bash -c`, `ssh host '...'`, `eval` and `$(...)` are read by recursing into the
command they carry. So `--jq 'length > 0'` is an argument, not a redirect, and
`ssh tw 'rm -rf x'` is an `rm`.

`gh` and `git` are **allowlisted** (`GH_READS`, `GIT_READS`): a verb
not known to read is refused. Everything else is denylisted by name
(`MUTATORS`, `SUBCOMMAND_WRITES`, `DEPLOY_MARKERS`). Ambiguity is
refused, never run: the cost of a wrong refusal is one `?` row in `ol owed`; the
cost of a wrong run is a write nobody asked for.

```pycon
>>> write_effect('gh workflow run deploy.yml --repo o/r')
'gh workflow run'
>>> write_effect('gh pr view 3 --json state -q .state | grep -q MERGED')
''
>>> write_effect('curl -s -d a=b https://example.com/x')
'curl with a request body (-d)'
>>> write_effect('test -f ~/.config/x && echo ok > /dev/null')
''
>>> write_effect("gh run list --created '>2026-09-10' -q length")
''
>>> write_effect("ssh tw 'rm -rf /srv/x'")
'rm'
```

### Functions

| [`write_effect`](#openloops.predicate_safety.write_effect)(command)   | Why *command* is refused as a predicate, or `""` if it only reads.   |
|--------------------------------------------------------------------------|----------------------------------------------------------------------|

### openloops.predicate_safety.write_effect(command)

Why *command* is refused as a predicate, or `""` if it only reads.

```pycon
>>> write_effect('gh pr -R o/r merge 3')
'gh pr merge'
>>> write_effect('gh api repos/o/r/pulls/3 --jq "length > 0"')
''
>>> write_effect('echo x 2>err.log')
'redirect into err.log'
>>> write_effect('git -C ~/x log -1')
''
>>> write_effect("echo 'unbalanced")
'unparseable'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
