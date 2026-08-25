"""Synthetic transcript builders.

Every fixture in this suite is invented. Nothing here is lifted from a real session,
because the package's own egress rule binds its tests as tightly as its code — a
reproduction pasted into a public repository is exactly how a token gets published.
"""

from __future__ import annotations

import json
from pathlib import Path

TS = "2026-01-0{d}T{h:02d}:00:00.000Z"


def stamp(day: int = 1, hour: int = 0) -> str:
    return TS.format(d=day, h=hour)


def user(text: str, *, at: str, cwd: str = "/w/demo", branch: str = "main", **extra):
    return {
        "type": "user",
        "sessionId": extra.pop("session", "s1"),
        "cwd": cwd,
        "gitBranch": branch,
        "timestamp": at,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        **extra,
    }


def assistant(text: str = "", *, at: str, model: str = "test-model", blocks=None, **extra):
    content = list(blocks) if blocks is not None else []
    if text:
        content.append({"type": "text", "text": text})
    return {
        "type": "assistant",
        "sessionId": extra.pop("session", "s1"),
        "cwd": extra.pop("cwd", "/w/demo"),
        "gitBranch": extra.pop("branch", "main"),
        "timestamp": at,
        "message": {"role": "assistant", "model": model, "content": content},
        **extra,
    }


def tool_use(name: str, tool_id: str):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": {}}


def tool_result(tool_id: str, *, at: str, **extra):
    return {
        "type": "user",
        "sessionId": extra.pop("session", "s1"),
        "timestamp": at,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}],
        },
        **extra,
    }


def compact_summary(text: str, *, at: str, **extra):
    return {
        "type": "user",
        "sessionId": extra.pop("session", "s1"),
        "timestamp": at,
        "isCompactSummary": True,
        "message": {
            "role": "user",
            "content": "This session is being continued from a previous conversation "
            "that ran out of context. The summary below covers the earlier portion of "
            "the conversation.\n\nSummary:\n" + text,
        },
        **extra,
    }


def recap(text: str, *, at: str, session: str = "s1"):
    """Claude Code's own end-of-turn recap record."""
    return {
        "type": "system",
        "subtype": "away_summary",
        "content": text,
        "timestamp": at,
        "sessionId": session,
        "isSidechain": False,
    }


def error_banner(text: str, *, at: str, session: str = "s1"):
    """A turn whose text is a usage-limit or connection notice, not the assistant's."""
    return {
        "type": "assistant",
        "sessionId": session,
        "timestamp": at,
        "message": {
            "role": "assistant",
            "model": "test-model",
            "stop_reason": "stop_sequence",
            "content": [{"type": "text", "text": text}],
        },
    }


def ai_title(text: str, *, session: str = "s1"):
    return {"type": "ai-title", "aiTitle": text, "sessionId": session}


def custom_title(text: str, *, session: str = "s1"):
    return {"type": "custom-title", "customTitle": text, "sessionId": session}


def pr_link(number: int, repo: str, *, at: str, session: str = "s1"):
    return {
        "type": "pr-link",
        "prNumber": number,
        "prRepository": repo,
        "prUrl": f"https://example.invalid/{repo}/pull/{number}",
        "timestamp": at,
        "sessionId": session,
    }


def closed_session(session: str = "s1") -> list[dict]:
    """A session whose last turn reads as a close-out."""
    return [
        custom_title("demo", session=session),
        ai_title("Fix the widget and ship it", session=session),
        user("fix the widget", at=stamp(1, 9), session=session),
        assistant("Fixed and merged. Nothing is pending.", at=stamp(1, 10), session=session),
    ]


def asking_session(session: str = "s2") -> list[dict]:
    """A session whose last turn puts a question to the human."""
    return [
        user("do the thing", at=stamp(1, 9), session=session),
        assistant(
            "I fixed the parser. Do you want me to land it, or leave the PR open?",
            at=stamp(1, 10),
            session=session,
        ),
    ]


def interrupted_session(session: str = "s3") -> list[dict]:
    """A session that stops with the human's prompt unanswered."""
    return [
        user("start", at=stamp(1, 9), session=session),
        assistant("Working on it.", at=stamp(1, 10), session=session),
        user("and now do the other thing", at=stamp(1, 11), session=session),
    ]


def write_transcripts(root: Path, sessions: dict[str, list[dict]], *, project="-w-demo"):
    """Lay out sessions the way Claude Code does: one JSONL per session id."""
    proj = Path(root) / project
    proj.mkdir(parents=True, exist_ok=True)
    for key, records in sessions.items():
        path = proj / f"{key}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return proj
