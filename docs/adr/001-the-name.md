---
status: accepted
date: 2026-08-25
---

# ADR-001 — The name, and two collisions accepted on purpose

## Context

`openloops` is free on PyPI and describes what the tool is about. It is also taken twice
elsewhere, in ways a search will find before it finds this: **OpenLoops** is an
established particle-physics one-loop amplitude library, and **openloops** is a
browser-history tool that groups your browsing into what you were trying to do — an
adjacent product using the same metaphor, in a different distribution channel.

Separately, the name is eighteen characters long. The project's own kill criterion is
that the read path stops being reached daily, and typing cost is a real contributor to
that.

## Options

**Keep `openloops` for everything, command included.** One name to remember, and
eighteen characters on the surface whose typing cost is a named risk.

**Rename outright to something short and unambiguous.** Buys a clean name everywhere,
at the price of a name that describes nothing and is undiscoverable — which makes the
public half of the goal worse in order to fix the private half.

**Split the two.** A distribution name must be discoverable and descriptive; a command
name must be cheap to type. Those demands pull in opposite directions and do not have to
be met by the same string.

## Decision

**The project, the repository, the PyPI distribution and the import package are all
`openloops`. The console script is `ol`** — the project's initials, so the mapping is
guessable from the install command alone and nothing new has to be memorised.

**Both collisions are accepted deliberately and named in the README.** A reader who
searches the name will find a physics library first; being told that up front costs
nothing and prevents the impression of an oversight. Neither collision blocks
`pip install openloops`.

## Consequences

`ol` is short enough to be typed reflexively, which is the point. It is also short
enough to collide with a local alias on some machines; that is the user's to resolve,
and the module remains runnable as `python -m openloops`.

## Confirmation

- `pip install openloops` puts an `ol` executable on PATH.
- `python -c "import openloops"` succeeds.
- The README contains a paragraph naming both collisions.
