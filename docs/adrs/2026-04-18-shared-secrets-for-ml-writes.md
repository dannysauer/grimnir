# ADR: Gate machine-only ML writes with optional shared secrets

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-18 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | Who may upload models and drive training-job state. Excludes authentication for people and for every other Freki endpoint. |
| Related | [#27](https://github.com/dannysauer/grimnir/issues/27), [#29](https://github.com/dannysauer/grimnir/issues/29), [#86](https://github.com/dannysauer/grimnir/issues/86); commits `e88c271` and `962cf5e` |
| Implementation | `freki/src/freki/ml_auth.py`, `freki/src/freki/routers/models.py`, `freki/src/freki/routers/training_jobs.py`, `nornir/src/nornir/freki_client.py` |
| Revisit when | Freki gets general authentication ([#5](https://github.com/dannysauer/grimnir/issues/5)). |

## Business driver

Völva unpickles whichever model Freki marks active, so anyone who can upload
a model can run code inside Völva
([#29](https://github.com/dannysauer/grimnir/issues/29)). Training-job state
had no owner either: any caller could complete or fail another daemon's job
([#27](https://github.com/dannysauer/grimnir/issues/27)). Freki has no
authentication at all, and designing it properly is its own piece of work.

## Constraints

- The dashboard is used from a phone on the home network with no login.
- Nornir is the only legitimate caller of the affected endpoints.

## Decision

**Y statement:** We will gate model upload and Nornir's control writes behind
two optional shared-secret headers, and bind each running job to a per-claim
token, because those are the writes that lead to code execution or corrupt job
state, so the worst holes close without waiting for general authentication.

`MODEL_UPLOAD_SHARED_SECRET` guards `POST /api/models` through the
`X-Grimnir-Model-Upload-Secret` header. `ML_CONTROL_SHARED_SECRET` guards the
daemon heartbeat and the job claim, heartbeat, complete, and fail calls
through `X-Grimnir-ML-Control-Secret`.

- When a secret is configured, Freki MUST reject the guarded calls that lack
  the matching header.
- Freki MUST reject a job heartbeat, complete, or fail call that doesn't carry
  the claiming daemon's id and claim token.
- This is a stopgap. It MUST NOT be treated as Freki's authentication design.

## Consequences

- Both secrets default to unset, and unset means open. A default install
  accepts model uploads from anyone on the network.
- `PUT /api/predictions/current`, model activation, job creation, and job
  cancellation aren't guarded
  ([#86](https://github.com/dannysauer/grimnir/issues/86),
  [#5](https://github.com/dannysauer/grimnir/issues/5)).
- A shared secret proves the caller knows the secret, not which daemon it is.

## Alternatives considered

### Keep the endpoints open

That was the state before these commits, and it left a path from "can reach
Freki" to "can run code in Völva."

### Authenticate all of Freki first

Issue #5 lists a reverse proxy with basic auth, OIDC, and mutual TLS as
candidates. None was chosen, and waiting for that choice would have left the
upload path open in the meantime.

### Stop unpickling models

Issue #29 is about pickle deserialization itself. A model format that can't
execute code would remove the risk at its source, but nothing in the record
shows it was evaluated.
