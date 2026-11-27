# ADR: Defer authentication for the proof of concept, behind one seam

## Record

| Field | Value |
| --- | --- |
| Date | 2026-11-27 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | Whether Freki and the services that call it authenticate during the proof of concept, and how new endpoints are written so authentication can be added later. Excludes which authentication method is eventually chosen. |
| Related | [#5](https://github.com/dannysauer/grimnir/issues/5), [#103](https://github.com/dannysauer/grimnir/issues/103), [#86](https://github.com/dannysauer/grimnir/issues/86); [Gate machine-only ML writes with optional shared secrets](2026-04-18-shared-secrets-for-ml-writes.md); [agent training interface](../design/2026-11-15-agent-training-interface.md) |
| Revisit when | Freki becomes reachable from outside the home network, an AI agent is given its own credential, or Grimnir starts storing sleep, respiration, or identity data. |

## Business driver

The goal for the next stretch of work is a working proof of concept: room
location that holds up, a better training workflow, and a start on sleep.
Authentication is real work, and the owner judges the home network secure
enough to run without it for now.

Leaving it out entirely has a cost later, though. Every endpoint written
without a place for a permission check is one more to revisit, and an agent
interface needs scoped access from the start.

## Constraints

- Grimnir runs only on the home network.
- The optional shared secrets for model upload and Nornir's control writes
  stay as they are.
- An agent interface, when it arrives, needs narrower access than a person
  at the dashboard.

## Decision

**Y statement:** We will run the proof of concept without authentication,
but route every Freki endpoint through one dependency that names the scope
the endpoint needs, because adding authentication later should mean
changing that dependency rather than every route, so the proof of concept
moves fast without making the later work larger.

The scopes, named now so routes can declare them:

| Scope | Covers |
| --- | --- |
| `presence:read` | Current predictions and the prediction stream |
| `csi:read` | Raw CSI streams, history, and the training-data export |
| `labels:write` | Rooms, labels, and future annotations |
| `ml:train` | Creating, cancelling, and reading training jobs and their results |
| `ml:control` | Nornir's daemon and job-control calls, and model upload |
| `ml:activate` | Putting a model into service |
| `admin` | Anything else that changes configuration |

Until authentication exists, the dependency grants every scope to every
caller.

- A new Freki route MUST declare its scope through the shared dependency.
- Freki MUST NOT be exposed beyond the home network while this record is
  Accepted.
- Grimnir MUST NOT store sleep, respiration, or identity data while this
  record is Accepted.

## Consequences

- Anyone on the home network can read presence and drive training, as they
  can today. #103 stays open as the record of the risk.
- The CORS wildcard on Freki still lets a web page in a home browser reach
  the API. Removing it costs nothing and isn't authentication, so #103 can
  still drop it.
- Adding the dependency to existing routes is a small, mechanical change.
  It's tracked in [#5](https://github.com/dannysauer/grimnir/issues/5).
- The last rule means sleep work stops at importing ground truth into a
  development database until authentication lands. Sleep data reveals more
  than room presence does.

## Alternatives considered

### Authenticate now

Issue #5 lists a reverse proxy with basic auth, OIDC, and mutual TLS. Any of
them would close #103's path from the network to code execution. It would
also come first in a queue where the owner wants a proof of concept, so it
was rejected for now.

### Defer authentication with no seam

This is the least work today. Every route written in the meantime would need
revisiting, and an agent interface would have nowhere to hang narrower
access.
