"""Is a ``manual-task`` verify predicate a pure read?

``ol owed`` *executes* the shell command an issue carries, to see whether the ask has
been done since. A question ("what do I owe?") must not have a write effect, but a
predicate is free text from an issue body: one ran ``gh workflow run`` and every
``ol owed`` started a deploy (openloops#43).

:func:`write_effect` is the guard. It returns the reason a command is refused, or
``""`` for one that reads. It is a **guard against honest mistakes, not a sandbox**: a
predicate that hides a write behind a script it calls still runs. What it does see, it
sees as the shell would: the command is split into shell words (:mod:`shlex`), then
into simple commands at unquoted ``|``, ``;``, ``&&``, ``||``, ``&`` and newlines, and
``bash -c``, ``ssh host '...'``, ``eval`` and ``$(...)`` are read by recursing into the
command they carry. So ``--jq 'length > 0'`` is an argument, not a redirect, and
``ssh tw 'rm -rf x'`` is an ``rm``.

``gh`` and ``git`` are **allowlisted** (:data:`GH_READS`, :data:`GIT_READS`): a verb
not known to read is refused. Everything else is denylisted by name
(:data:`MUTATORS`, :data:`SUBCOMMAND_WRITES`, :data:`DEPLOY_MARKERS`). Ambiguity is
refused, never run: the cost of a wrong refusal is one ``?`` row in ``ol owed``; the
cost of a wrong run is a write nobody asked for.

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
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterator, Sequence

__all__ = ["write_effect"]

# --------------------------------------------------------------------------------
# The data: what reads, what writes.

#: ``gh <noun> <verb>`` forms that only read. A noun mapped to ``None`` takes no verb
#: (``gh status``). Any other noun or verb is refused. ``gh api`` is judged on its
#: method and fields instead (:func:`_gh_api_effect`).
GH_READS: dict[str, frozenset[str] | None] = {
    "pr": frozenset({"view", "list", "status", "checks", "diff"}),
    "issue": frozenset({"view", "list", "status"}),
    "run": frozenset({"view", "list"}),
    "workflow": frozenset({"view", "list"}),
    "release": frozenset({"view", "list"}),
    "repo": frozenset({"view", "list"}),
    "search": frozenset({"issues", "prs", "repos", "code", "commits"}),
    "auth": frozenset({"status"}),
    "label": frozenset({"list"}),
    "cache": frozenset({"list"}),
    "secret": frozenset({"list"}),
    "variable": frozenset({"list", "get"}),
    "gist": frozenset({"view", "list"}),
    "ruleset": frozenset({"view", "list", "check"}),
    "status": None,
}
#: Options that may sit between ``gh <noun>`` and its verb, with the value they take.
GH_OPTIONS_WITH_VALUE = frozenset({"-R", "--repo"})
#: ``gh api`` short options taking a value, and long ones (``--x value`` form).
GH_API_SHORT_VALUES = "XfFHqtp"
GH_API_LONG_VALUES = frozenset(
    {"--method", "--field", "--raw-field", "--input", "--header", "--jq"}
    | {"--template", "--preview", "--hostname", "--cache"}
)
GH_API_FIELDS = frozenset({"-f", "-F", "--field", "--raw-field"})
#: HTTP methods that read.
READ_METHODS = frozenset({"GET", "HEAD"})

#: ``git`` verbs that read (``fetch`` writes only refs, and is how a check gets fresh).
GIT_READS = frozenset(
    {"status", "log", "diff", "show", "rev-parse", "ls-remote", "describe", "fetch"}
    | {"ls-files", "cat-file", "merge-base", "rev-list", "show-ref", "for-each-ref"}
)
#: ``git branch`` reads only in these forms; a name after them needs ``--list``.
GIT_BRANCH_LISTS = frozenset(
    {"--list", "-l", "-a", "--all", "-r", "--remotes", "--show-current"}
)
#: ``git remote`` reads with no operand, ``-v``, or one of these subcommands.
GIT_REMOTE_READS = frozenset({"get-url", "show"})
#: Options that may sit before the git verb, with the value they take.
GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree"})

#: ``curl`` short options taking a value (so ``-sXPOST`` and ``-sd x`` parse), and the
#: long ones whose value may be the next word.
CURL_SHORT_VALUES = "ABbCcDdEeFHKmoPQrTtUuwXxYyz"
CURL_LONG_VALUES = frozenset(
    {"--request", "--data", "--data-raw", "--data-binary", "--data-urlencode"}
    | {"--data-ascii", "--json", "--form", "--form-string", "--upload-file"}
    | {"--header", "--output", "--user", "--user-agent", "--write-out", "--url"}
    | {"--max-time", "--connect-timeout", "--cookie", "--cookie-jar", "--proxy"}
)
#: ``curl`` options that send a body even with ``-G`` (which turns ``-d`` into a query).
CURL_UPLOADS = frozenset(
    {"-F", "-T", "--json", "--form", "--form-string", "--upload-file"}
)

#: Commands that change files or processes whatever their arguments.
MUTATORS = frozenset(
    {"rm", "mv", "rmdir", "kill", "pkill", "killall", "tee", "chmod", "chown"}
    | {"truncate", "cp", "touch", "mkdir", "ln", "unlink", "shred", "dd"}
)
#: Commands that write when any of these words is among their arguments.
SUBCOMMAND_WRITES: dict[str, frozenset[str]] = {
    "systemctl": frozenset(
        {"start", "stop", "restart", "reload", "enable", "disable", "kill"}
    ),
    "launchctl": frozenset(
        {"kickstart", "load", "unload", "bootstrap", "bootout", "start", "stop"}
    ),
    **dict.fromkeys(
        ("npm", "uv", "cargo", "twine", "docker"),
        frozenset({"publish", "upload", "push"}),
    ),
    "find": frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint"}),
}
#: A word containing one of these is a deploy or a secret edit, whatever runs it.
DEPLOY_MARKERS = ("cmd-deploy", "deploy.py", "deploy.sh", "tw-deploy", "tw-edit-secret")

#: Words that precede a command without being it.
KEYWORDS = frozenset({"if", "then", "elif", "else", "while", "until", "do", "{", "!"})
#: Commands that run the rest of their arguments as a command. Their own options may
#: take values we do not know, so every later operand is tried as the command word.
WRAPPERS = frozenset(
    {"sudo", "xargs", "env", "nohup", "nice", "time", "timeout", "watch"}
    | {"command", "exec", "builtin"}
)
#: Shells whose ``-c`` argument is a command to read; their options taking a value.
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
SHELL_OPTIONS_WITH_VALUE = frozenset({"-o", "+o", "-O", "+O"})
#: ``ssh`` options taking a value; the first operand after them is the host.
SSH_OPTIONS_WITH_VALUE = frozenset(f"-{letter}" for letter in "BbcDEeFIiJLlmOoPpQRSWw")

#: Characters :mod:`shlex` returns as their own (operator) tokens.
OPERATOR_CHARS = "();<>|&\n"
#: How deep ``bash -c "ssh h 'sh -c ...'"`` nesting is followed before refusing.
MAX_DEPTH = 4

_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

# --------------------------------------------------------------------------------
# The guard.


def write_effect(command: str) -> str:
    """Why *command* is refused as a predicate, or ``""`` if it only reads.

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
    """
    return _check(command or "", depth=0)


def _check(command: str, *, depth: int) -> str:
    if depth > MAX_DEPTH:
        return "nested too deeply to read"
    try:
        tokens = _tokens(command)
    except ValueError:
        return "unparseable"
    for token in tokens:
        for body in _substitutions(token):
            if reason := _check(body, depth=depth + 1):
                return reason
    commands, reason = _simple_commands(tokens)
    if reason:
        return reason
    for words in commands:
        if reason := _command_effect(words, depth=depth):
            return reason
    return ""


def _tokens(command: str) -> list[str]:
    """Shell words, with each run of unquoted operator characters as its own token.

    >>> _tokens("a 'b > c' 2>&1 | d\\ne")
    ['a', 'b > c', '2', '>&', '1', '|', 'd', '\\n', 'e']
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=OPERATOR_CHARS)
    lexer.whitespace = " \t\r"  # a newline separates commands: it is an operator
    lexer.whitespace_split = True
    lexer.commenters = ""  # a `#` word is harmless; eating a line would hide one
    return list(lexer)


def _is_operator(token: str) -> bool:
    # A quoted word made only of operator characters (`'>'`) looks the same after
    # shlex; reading it as an operator can only over-refuse.
    return bool(token) and all(char in OPERATOR_CHARS for char in token)


def _simple_commands(tokens: Sequence[str]) -> tuple[list[list[str]], str]:
    """Split *tokens* at operators, dropping redirects: ``(commands, refusal)``.

    An output redirect is refused unless it goes to ``/dev/null`` or another fd.
    """
    commands: list[list[str]] = [[]]
    stream = iter(tokens)
    for token in stream:
        current = commands[-1]
        if not _is_operator(token):
            current.append(token)
            continue
        is_output = ">" in token and ">(" not in token
        is_input = "<" in token and "<(" not in token
        if not (is_output or is_input):  # | ; && || & newline ( ) <( >(
            commands.append([])
            continue
        target = next(stream, "")
        if current and current[-1].isdigit():
            current.pop()  # the fd in `2>x` is not an argument
        fd_dup = token.endswith("&") and (target.isdigit() or target == "-")
        if is_output and target != "/dev/null" and not fd_dup:
            return [], f"redirect into {target or 'nothing'}"
    return [words for words in commands if words], ""


def _substitutions(token: str) -> list[str]:
    """The commands inside ``$(...)`` and backticks in one (double-quoted) word.

    >>> _substitutions('state=$(gh pr view 3) and `date`')
    ['date', 'gh pr view 3']
    """
    bodies = token.split("`")[1::2]
    start = token.find("$(")
    while start != -1:
        depth, end = 0, len(token)
        for end in range(start + 1, len(token)):
            depth += {"(": 1, ")": -1}.get(token[end], 0)
            if depth == 0:
                break
        bodies.append(token[start + 2 : end])
        start = token.find("$(", end)
    return bodies


def _command_effect(words: Sequence[str], *, depth: int) -> str:
    """Why one simple command (a list of words) is refused, or ``""``."""
    words = _strip_prefix(words)
    if not words:
        return ""
    for marker in DEPLOY_MARKERS:
        if any(marker in word for word in words):
            return f"deploy ({marker})"
    name, args = os.path.basename(words[0]), list(words[1:])
    if name in WRAPPERS:
        for i, word in enumerate(args):
            if not word.startswith("-") and (
                reason := _command_effect(args[i:], depth=depth)
            ):
                return reason
        return ""
    if name in SHELLS:
        script = _shell_script(args)
        return _check(script, depth=depth + 1) if script else ""
    if name == "ssh":
        host_at = _operand_index(args, 0, SSH_OPTIONS_WITH_VALUE)
        return _check(" ".join(args[host_at + 1 :]), depth=depth + 1)
    if name == "eval":
        return _check(" ".join(args), depth=depth + 1)
    if name in MUTATORS:
        return name
    for word in args:
        if word in SUBCOMMAND_WRITES.get(name, ()):
            return f"{name} {word}"
    if name == "sed" and _sed_in_place(args):
        return "sed -i"
    if name == "gh":
        return _gh_effect(args)
    if name == "git":
        return _git_effect(args)
    if name == "curl":
        return _curl_effect(args)
    return ""


def _strip_prefix(words: Sequence[str]) -> Sequence[str]:
    """Drop leading shell keywords and ``VAR=value`` assignments."""
    i = 0
    while i < len(words) and (words[i] in KEYWORDS or _ASSIGNMENT.match(words[i])):
        i += 1
    return words[i:]


def _operand_index(args: Sequence[str], start: int, with_value: frozenset) -> int:
    """Index of the first non-option word at or after *start*, skipping option values.

    >>> _operand_index(['-R', 'o/r', 'view', '3'], 0, frozenset({'-R'}))
    2
    """
    i = start
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        i += 2 if args[i] in with_value else 1
    return i


def _options(
    args: Sequence[str], *, short_values: str, long_values: frozenset
) -> Iterator[tuple[str | None, str | None]]:
    """``(option, value)`` for each option, ``(None, word)`` for each operand.

    Short options cluster, getopt-style, so ``-sXGET`` is ``-s`` then ``-X GET``.

    >>> list(_options(['-sXGET', '--data=a', 'u'], short_values='X', long_values=frozenset()))
    [('-s', None), ('-X', 'GET'), ('--data', 'a'), (None, 'u')]
    """
    stream = iter(args)
    for arg in stream:
        if arg == "--":
            yield from ((None, rest) for rest in stream)
        elif arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if eq:
                yield name, value
            else:
                yield name, next(stream, "") if name in long_values else None
        elif arg.startswith("-") and len(arg) > 1:
            for i, letter in enumerate(arg[1:], start=1):
                if letter in short_values:
                    yield f"-{letter}", arg[i + 1 :] or next(stream, "")
                    break
                yield f"-{letter}", None
        else:
            yield None, arg


def _shell_script(args: Sequence[str]) -> str:
    """The ``-c`` command of a shell invocation, or ``""`` if it runs none we can see."""
    stream = iter(args)
    for arg in stream:
        if arg in SHELL_OPTIONS_WITH_VALUE:
            next(stream, None)
        elif arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            return next(stream, "")
        elif not arg.startswith(("-", "+")):
            return ""  # a script file: not read, like any other program
    return ""


def _sed_in_place(args: Sequence[str]) -> bool:
    return any(
        arg.startswith("--in-place")
        or (arg.startswith("-") and not arg.startswith("--") and "i" in arg[1:])
        for arg in args
    )


def _gh_effect(args: Sequence[str]) -> str:
    noun_at = _operand_index(args, 0, GH_OPTIONS_WITH_VALUE)
    if noun_at >= len(args):
        return ""  # `gh --version`
    noun = args[noun_at]
    if noun == "api":
        return _gh_api_effect(args[noun_at + 1 :])
    if noun not in GH_READS:
        return f"gh {noun}"
    reads = GH_READS[noun]
    if reads is None:
        return ""
    verb_at = _operand_index(args, noun_at + 1, GH_OPTIONS_WITH_VALUE)
    verb = args[verb_at] if verb_at < len(args) else ""
    return "" if verb in reads else f"gh {noun} {verb}".rstrip()


def _gh_api_effect(args: Sequence[str]) -> str:
    """``gh api`` reads unless it sets a write method, or sends fields without ``GET``.

    ``gh api graphql`` is always a POST; it reads unless the query is a mutation.
    """
    method, fields, endpoint = "", [], ""
    options = _options(
        args, short_values=GH_API_SHORT_VALUES, long_values=GH_API_LONG_VALUES
    )
    for option, value in options:
        if option in ("-X", "--method"):
            method = (value or "").upper()
        elif option in GH_API_FIELDS:
            fields.append(value or "")
        elif option == "--input":
            return "gh api --input"
        elif option is None and not endpoint:
            endpoint = value or ""
    if endpoint == "graphql":
        if any("mutation" in arg.lower() for arg in args):
            return "gh api graphql mutation"
        if any(field.startswith("query=@") for field in fields):
            return "gh api graphql query from a file"
        return ""
    if method and method not in READ_METHODS:
        return f"gh api -X {method}"
    if fields and not method:
        return "gh api with fields (a POST)"
    return ""


def _git_effect(args: Sequence[str]) -> str:
    verb_at = _operand_index(args, 0, GIT_OPTIONS_WITH_VALUE)
    if verb_at >= len(args):
        return ""  # `git --version`
    verb, rest = args[verb_at], args[verb_at + 1 :]
    options = {arg for arg in rest if arg.startswith("-")}
    operands = [arg for arg in rest if not arg.startswith("-")]
    if verb in GIT_READS:
        return ""
    if verb == "branch" and options <= GIT_BRANCH_LISTS:
        if not operands or options & {"--list", "-l"}:
            return ""
    if verb == "remote" and options <= {"-v", "--verbose"}:
        if not operands or operands[0] in GIT_REMOTE_READS:
            return ""
    return f"git {verb}"


def _curl_effect(args: Sequence[str]) -> str:
    method, data, upload, as_query = "", "", "", False
    options = _options(
        args, short_values=CURL_SHORT_VALUES, long_values=CURL_LONG_VALUES
    )
    for option, value in options:
        if option in ("-X", "--request"):
            method = (value or "").upper()
        elif option in ("-G", "--get"):
            as_query = True
        elif option in CURL_UPLOADS:
            upload = upload or option
        elif option == "-d" or (option or "").startswith("--data"):
            data = data or option
    if method and method not in READ_METHODS:
        return f"curl -X {method}"
    if upload:
        return f"curl with an upload ({upload})"
    if data and not as_query:
        return f"curl with a request body ({data})"
    return ""
