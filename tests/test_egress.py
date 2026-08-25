"""Egress rules. Every credential fixture is built by concatenation at runtime.

That is not stylistic: ``tests/test_egress_repo.py`` scans every tracked file in this
repository with the same patterns, so a literal credential in a test would be a
violation of the rule the test exists to prove.
"""

import pytest

from openloops.egress import (
    FOREIGN_HOME,
    CredentialFound,
    apply_aliases,
    default_aliases,
    find_absolute_paths,
    find_credentials,
    rewrite_paths,
    scan,
    scrub,
)

HOME = "/Us" + "ers/someone"


def make(kind: str) -> str:
    """A credential-shaped string, assembled so no literal exists in this file."""
    return {
        "aws": "AK" + "IA" + "B" * 16,
        "github": "gh" + "p_" + "A" * 36,
        "github_pat": "github" + "_pat_" + "B" * 30,
        "anthropic": "sk-" + "ant-" + "C" * 30,
        "openai": "sk-" + "D" * 30,
        "slack": "xo" + "xb-" + "1" * 20,
        "google": "AI" + "za" + "E" * 35,
        "pem": "-----BEG" + "IN RSA PRIVATE KEY-----",
        "assignment": 'api_key = "' + "aB3" * 8 + '"',
        "unquoted": "GITHUB_TOKEN=" + "z9Q" * 8,
        "jwt": "eyJ" + "a" * 20 + ".eyJ" + "b" * 20 + ".sig",
        "npm": "npm_" + "a" * 36,
        "gitlab": "glpat-" + "a" * 24,
        "huggingface": "hf_" + "a" * 34,
        "stripe": "sk_live_" + "a" * 24,
        "sendgrid": "SG." + "a" * 22 + "." + "b" * 22,
        "url_password": "postg" + "res://user:" + "s3cretpw99" + "@host/db",
    }[kind]


@pytest.mark.parametrize(
    "kind",
    [
        "aws", "github", "github_pat", "anthropic", "openai", "slack", "google", "pem",
        "assignment", "unquoted", "jwt", "npm", "gitlab", "huggingface", "stripe",
        "sendgrid", "url_password",
    ],
)
def test_every_credential_shape_raises(kind):
    with pytest.raises(CredentialFound) as exc:
        scrub("some text " + make(kind))
    assert exc.value.pattern_name
    # The exception must never carry the secret itself.
    assert make(kind) not in str(exc.value)


def test_the_exception_names_where_without_quoting_what():
    with pytest.raises(CredentialFound) as exc:
        scrub(make("github"), where="session abc")
    assert "session abc" in str(exc.value)
    assert exc.value.offset == 0


@pytest.mark.parametrize(
    "text",
    [
        "the password is on the sticky note",
        "token: the one we talked about",
        "set SECRET_NAME in the environment",
        "sha256: " + "a" * 64,
        "look at commit " + "f" * 40,
        "AKIA is a prefix people mention",
        "https://user@github.com/x.git",
        "see https://example.com/a/b/c",
        "my_token: see the design doc",
    ],
)
def test_ordinary_prose_does_not_raise(text):
    assert scrub(text) == text


def test_paths_are_rewritten_not_raised():
    assert scrub(HOME + "/proj/x.py", aliases={HOME: "~"}) == "~/proj/x.py"


def test_longest_alias_wins():
    aliases = {HOME: "~", HOME + "/proj": "$PP"}
    assert apply_aliases(HOME + "/proj/x", aliases) == "$PP/x"


def test_an_alias_only_matches_at_a_path_boundary():
    """A sibling whose name merely starts with the alias must not be half-rewritten."""
    out = apply_aliases(HOME + "2/proj/x", {HOME: "~"})
    assert out == HOME + "2/proj/x"


@pytest.mark.parametrize(
    "path",
    ["/ro" + "ot/py/x", "/Us" + "ers/nobody/x", "/ho" + "me/runner/work/x"],
)
def test_a_home_that_is_not_this_one_is_rewritten_not_left(path):
    """A transcript from an ssh session names that machine's home, not this one's."""
    out = scrub(path)
    assert out.startswith(FOREIGN_HOME)
    assert "/Us" + "ers/" not in out and "/ro" + "ot" not in out


@pytest.mark.parametrize(
    "encoded",
    ["-Us" + "ers-someone-Dropbox-x", "-ho" + "me-runner-work", "-ro" + "ot-py-proj"],
)
def test_the_dash_encoded_form_of_a_home_path_is_rewritten_too(encoded):
    """Claude Code encodes a cwd into a directory name; the result is still a home path."""
    out = scrub(encoded)
    assert out.startswith(FOREIGN_HOME)
    assert find_absolute_paths(out, aliases={}) == []


def test_this_machines_encoded_home_becomes_a_tilde():
    from pathlib import Path

    encoded = str(Path.home()).replace("/", "-").replace("_", "-").replace(".", "-")
    assert scrub(encoded + "-proj-x").startswith("~")


def test_an_alias_cannot_synthesise_a_home_path_that_survives():
    """`scrub` rewrites, then checks its own output — so a bad alias cannot slip one in."""
    out = scrub("built $PP/x", aliases={"$PP": "/Us" + "ers/nobody/proj"})
    assert find_absolute_paths(out, aliases={}) == []
    assert out.startswith("built " + FOREIGN_HOME)


def test_default_aliases_rewrite_the_real_home():
    from pathlib import Path

    text = str(Path.home() / "somewhere")
    assert scrub(text) == "~/somewhere"
    assert set(default_aliases().values()) == {"~"}
    assert len(default_aliases()) == 2, "the literal home and its dash-encoded form"


def test_find_helpers_report_rather_than_raise():
    """Detection must still SEE a home path — that is what the repo audit needs."""
    assert find_credentials("clean") == []
    assert find_credentials(make("aws"))[0][0] == "aws_access_key_id"
    assert find_absolute_paths(HOME + "/x", aliases={}) == [(HOME, 0)]
    assert find_absolute_paths(HOME + "/x", aliases={HOME: "~"}) == []


def test_scan_accumulates_every_problem_instead_of_stopping_at_the_first():
    problems = scan(HOME + "/x " + make("github"), aliases={}, where="f.md")
    assert len(problems) == 2
    assert all(p.startswith("f.md:") for p in problems)
    assert make("github") not in " ".join(problems)
