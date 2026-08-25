# Architecture decision records

These restate the decisions openloops is built on, with the evidence that produced them
left where it belongs. The reasoning is here; the fleet statistics, incident records and
session identifiers that motivated it are not, and never will be — see
[ADR-003](003-the-public-private-boundary.md).

| ADR | Decides | Status |
|---|---|---|
| [ADR-001](001-the-name.md) | The name, and two collisions accepted on purpose | accepted |
| [ADR-002](002-what-the-first-release-contains.md) | What v0.1.0 contains, and what is withheld | accepted |
| [ADR-003](003-the-public-private-boundary.md) | The public/private boundary and the egress rule | accepted |
| [ADR-004](004-loop-state-not-process-state.md) | Loop state, not process state | accepted |
| [ADR-005](005-a-digest-is-dated-never-current.md) | A digest is dated, never current | accepted |
| [ADR-006](006-a-periodic-job-not-a-daemon.md) | A periodic job, not a daemon | accepted |
| [ADR-007](007-the-two-seams.md) | The two seams, and what is deliberately not one | accepted |

## Where these came from

openloops was designed before it was built, in a private repository that stays private.
That repository holds the research, the measurements, the incident that produced
[ADR-005](005-a-digest-is-dated-never-current.md), and eighteen ADRs of which these
seven are the ones a user of the package needs. It is not published, because publishing
it would mean publishing a lot of somebody's private working life.

The consequence for contributors is stated in
[ADR-003](003-the-public-private-boundary.md) and worth repeating here: **this repository
cannot accept a bug report containing a real transcript.** Reproductions must be
synthetic, as every fixture in `tests/` is.
