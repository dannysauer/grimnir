# Design: how does an AI agent help train models?

> **Summary:** The owner expects to work with an AI agent, such as Claude or
> ChatGPT, to train and compare models, and has raised an MCP interface as
> the way to do it. The leading option is a small MCP server in front of
> Freki with its own scoped token, built after Freki gains the endpoints any
> interface would need. What an agent may do without a person approving it
> is still open.

## Record

| Field | Value |
| --- | --- |
| Date | 2026-11-15 |
| Status | Draft |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Related | Review epic [#102](https://github.com/dannysauer/grimnir/issues/102); API gaps [#118](https://github.com/dannysauer/grimnir/issues/118), [#108](https://github.com/dannysauer/grimnir/issues/108); model path [#103](https://github.com/dannysauer/grimnir/issues/103), [#104](https://github.com/dannysauer/grimnir/issues/104); auth [#5](https://github.com/dannysauer/grimnir/issues/5), [#86](https://github.com/dannysauer/grimnir/issues/86); [sensing roadmap](2026-11-15-sensing-roadmap.md); [ML pipeline](../architecture/ml-pipeline.md) |

## Problem

Training a useful model takes many rounds: look at the data, pick features
and settings, train, read the results, compare, repeat. An agent can do most
of that if it can see the data's coverage and drive training.

Today it can't. A code review on 2026-11-15
([#102](https://github.com/dannysauer/grimnir/issues/102)) found these gaps in
Freki, and they'd block a person with `curl` as much as an agent:

- Nothing answers "what data do I have?" There's no summary by room,
  receiver, or day, and labels can be listed only by "last N minutes".
- A job spec accepts a `model_type` that Nornir ignores and a free-form
  `hyperparams` object passed straight to scikit-learn. A bad value fails
  only after the full data export.
- A finished job has no link to the model it produced, and neither jobs nor
  models can be fetched by id.
- A model's metrics are accuracy and macro F1 on a leaky split. There's no
  confusion matrix, no per-class score, and no record of which data it saw.
- Errors are prose in a `detail` string, and some bad inputs return `500`.
- Models are pickles, and Völva runs whatever is active. An agent that can
  upload or activate a model can run code in Völva
  ([#103](https://github.com/dannysauer/grimnir/issues/103)).

If nothing changes, an agent can queue a job and read two numbers. That
isn't enough to help.

## Goals and non-goals

Goals:

- An agent can inspect the dataset, run experiments, and compare results
  without a person relaying each step.
- An agent can't read where people are, upload executable artifacts, or put
  a model into service unnoticed.
- The same capabilities are available to a person and to the dashboard.

Non-goals:

- Letting an agent label data. Labels are ground truth from a person.
- Choosing features or models. See the
  [sensing roadmap](2026-11-15-sensing-roadmap.md).
- General authentication for Freki, though this work depends on it
  ([#5](https://github.com/dannysauer/grimnir/issues/5)).

## Requirements in scope

- `GRM-033`: training and inference reach data only through Freki. An agent
  interface is held to the same rule.
- `GRM-030`, `GRM-031`, `GRM-032`: the existing secret and claim-token checks
  on model upload and job control.
- `GRM-014`: at most one active model.
- `GRM-020`: a queued job goes to at most one daemon.

This work needs requirements that don't exist yet, on what an agent's
credential may and may not reach. They should be added to the requirements
page when the scopes are agreed.

## Constraints

- [Train and infer in separate services that reach data only through Freki](../adrs/2026-04-18-ml-services-use-freki-api.md).
- [Gate machine-only ML writes with optional shared secrets](../adrs/2026-04-18-shared-secrets-for-ml-writes.md).
  That record is a stopgap and says so. A shared secret can't tell an agent
  from a trainer.
- Stored strings reach the agent's context. Receiver names arrive in
  unauthenticated UDP packets, and room names, label notes, and job errors
  are free text. Any of them can carry instructions aimed at the agent.
- The data is sensitive: it shows where people are, and later when they
  sleep.

## Options

### Keep the current approach

The agent uses Freki's HTTP API directly, from a session that can reach the
network.

It needs no new code. It also gives the agent everything Freki serves,
including live presence, with no way to grant less, and the gaps above
remain.

### Fill the gaps in Freki, and stop there

Add to Freki what any interface needs: a dataset summary, a typed and
validated job spec with discoverable options, job and model lookup by id, a
job-to-model link, stored evaluation results, stable error codes, and a
working activation. The agent still calls HTTP, guided by `/openapi.json`.

Every other option needs this work, so it isn't wasted. It leaves scoping to
whatever general authentication Freki gets.

### A separate MCP server in front of Freki

A small Python service that speaks MCP to the agent and HTTP to Freki. It
holds its own token and exposes a short list of tools, such as:

- `dataset_summary`: rows by room, receiver, and day, with gaps and class
  balance
- `list_options`: the feature sets and model types a job may name, with
  their ranges
- `submit_experiment`: a declarative, validated job with capped resources
- `get_experiment` and `compare_experiments`: status, metrics, and the
  confusion matrix
- `propose_activation`: a request a person approves in the dashboard

It returns ids and numbers, and strips or length-caps free text. It doesn't
expose model upload or download, raw CSI, training-data export, labels, or
predictions.

The server is the place where "what may an agent do" is written down and
enforced. It costs a fifth service to deploy and keep in step with Freki.

### MCP inside Freki

Mount the same tools in the Freki process.

There's one less service and no second hop. But the agent's surface would
share a process and a database role with everything it isn't supposed to
reach, and the separation would rest on route-level checks in a service that
has none today.

### Dataset snapshots and a coding agent

Export a versioned snapshot of the training set to a file, and let a coding
agent work on it directly: write feature code, run experiments, and open
pull requests.

This is the only option where the agent can invent a feature that isn't
already in the menu, which is most of the early work in the sensing roadmap.
It has no place in the running system, though. The snapshot leaves Freki's
control, and whatever the agent trains still has to get back in through a
path that doesn't execute an untrusted pickle.

## Comparison

| | Keep current | Fill Freki gaps | Separate MCP server | MCP inside Freki | Snapshots and a coding agent |
| --- | --- | --- | --- | --- | --- |
| Agent can see data coverage | No | Yes | Yes | Yes | Yes |
| Agent can compare experiments | No | Yes | Yes | Yes | Yes, locally |
| Agent can try new feature code | No | No | No | No | Yes |
| Agent kept away from presence data | No | Only with scoped auth in Freki | Yes | Depends on route checks | Yes, if the snapshot has none |
| Agent can't cause code to run in Völva | No | No, until models aren't pickles | Yes | Depends on route checks | No, until models aren't pickles |
| Honors `GRM-033` | Yes | Yes | Yes | Yes | Yes, through an export endpoint |
| New service to run | No | No | Yes | No | No |

## Recommendation

Fill the gaps in Freki first, then put a separate MCP server in front of it.
Use snapshots and a coding agent for feature research, with the results
coming back as reviewed code, not as uploaded models.

I'm confident about the first step, because every option depends on it.

Authentication is deferred for the proof of concept
([record](../adrs/2026-11-27-defer-authentication.md)), so on the home network
the MCP server's scoping is a guard against mistakes, not a security
boundary: an agent that can reach the MCP server can usually reach Freki too.
That's acceptable for a proof of concept, and the scopes in that record are
the ones the MCP server's credential will carry once authentication lands.

Two things should be settled before an agent gets a credential. Models
shouldn't be pickles, or uploads should be signed by the trainer and checked
by Völva. And activation should need a person.

## Open questions

- **Which agent, running where?** A hosted assistant reaching into the home
  network is a different problem from a coding agent on a laptop. The owner
  decides.
- **May an agent activate a model?** The draft says no, it proposes and a
  person approves. The owner decides.
- **How is the MCP server authenticated to the agent, and to Freki?**
  Deferred with the rest of authentication. The MCP server asks for the
  `ml:train` scope and nothing broader.
- **What replaces pickled models?** A spike comparing ONNX and skops on the
  current random forest would answer whether either is a drop-in.
- **How large is a dataset snapshot?** The reviewer's estimate is about 1 GB
  per labeled hour with five receivers in the current format. Measure one.
- **Does a snapshot count as leaving the house?** It holds raw CSI, from
  which presence can be derived later. The owner decides where it may live.

## Outcome

Open. Changes of direction so far:

- 2026-11-27: authentication is deferred for the proof of concept, with named
  scopes for later ([record](../adrs/2026-11-27-defer-authentication.md)). The
  owner also asked for plain-language progress updates while training runs;
  the [training workbench](2026-11-27-training-workbench.md) doc covers those,
  and an agent interface would read the same job events.
