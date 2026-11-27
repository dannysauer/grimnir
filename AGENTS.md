# Grimnir agent instructions

Grimnir infers room-level presence in a house from Wi-Fi channel state
information captured by ESP32-S3 boards. This file holds the rules for
working in the repository. What the system is and how it works lives in
`docs/`, not here.

## Design documents

Read these before changing the system's behavior:

1. [`docs/architecture/overview.md`](docs/architecture/overview.md) for what
   the system is and how the parts fit
2. [`docs/architecture/quality-attributes.md`](docs/architecture/quality-attributes.md)
   for the requirements it has to keep
3. Accepted ADRs in [`docs/adrs/`](docs/adrs/README.md) for decisions a change
   has to respect

Load the rest as the task needs it:

| Working on | Read |
| --- | --- |
| Tables, migrations, labels, retention | [`docs/architecture/data-model.md`](docs/architecture/data-model.md) |
| Features, training, inference | [`docs/architecture/ml-pipeline.md`](docs/architecture/ml-pipeline.md) |
| Freki endpoints | [`docs/api-reference.md`](docs/api-reference.md) |
| Muninn packets or the Geri parser | [`docs/udp-wire-protocol.md`](docs/udp-wire-protocol.md) |
| Metrics | [`docs/metrics-reference.md`](docs/metrics-reference.md) |
| Compose, Helm, Ansible, database setup | [`docs/deployment.md`](docs/deployment.md) |
| Firmware builds | [`docs/firmware-build-and-flash.md`](docs/firmware-build-and-flash.md) |
| Repository layout, commands, tool versions | [`docs/monorepo.md`](docs/monorepo.md) |

When documents disagree, an Accepted ADR wins over a living page, and a living
page wins over a Proposed ADR or an open design doc. Issues define the scope of
current work but never override an Accepted ADR. Report a conflict instead of
silently resolving it.

Living pages describe the current state. When a change alters behavior, update
the affected living pages and reference pages in the same change, and put the
history in an ADR, an evidence receipt, or the commit message. Don't add dated
notes or "previously" asides to a living page.

Tests that verify a requirement name its ID, such as `GRM-001`, in a comment,
so the requirement can be traced to its proof.

`.trellis.yaml` records where each kind of document lives.

## Work tracking

- GitHub issues are the only tracker. There is no `TODO.md`.
- Substantial work starts with an issue. Split broad work into an epic with
  sub-issues.
- An issue that carries out a decision links the ADR. A decision made while
  working on an issue gets an ADR; it doesn't live only in the issue thread.
- An open choice with several real options gets a design doc under
  `docs/design/` before anyone builds it.
- Close an issue when its change lands on `main`.

## Documentation checklist

When a change adds or alters a capability, environment variable, dependency,
endpoint, packet field, table, or metric, update in the same change:

1. The living page or reference page that describes it
2. `README.md`, if the quick start or component list changes
3. `.env.example`, the Helm `values.yaml`, and `values.schema.json`, if
   configuration changes
4. The service's `pyproject.toml`, with a pinned version, for a new dependency
5. The requirement's `Verified by` entry, if a test that cites it moves

## Python conventions

- Python 3.12. Tool versions are pinned in `.tool-versions` for `asdf`.
- Each service is a package with its own `pyproject.toml` and the `hatchling`
  build backend. Pin dependencies to exact versions.
- `asyncio` throughout. The services use asyncpg at runtime; only the
  migration runner uses psycopg2.
- Type annotations on every function signature, and
  `from __future__ import annotations` at the top of every file.
- Docstrings on public functions and classes. No mutable default arguments.

Style follows the Google guides vendored under `docs/style-guides/google/`:
`pyguide.md` for Python, `shellguide.md` for shell, `cppguide.html` for the
firmware's C where its rules apply to C, `htmlcssguide.html`, and
`jsguide.html`. That directory is a git subtree. Don't edit it by hand;
update it with:

```bash
git subtree pull --prefix=docs/style-guides/google \
  https://github.com/google/styleguide.git gh-pages --squash
```

## Logging

Every Python service logs one JSON object per line through structlog
(`GRM-040`). Copy the configuration block from an existing service's
`main.py`; it routes standard-library logging through the same JSON renderer.

- Event names use dot notation, such as `db.batch_inserted`.
- Pass data as keyword arguments: `log.info("job.claimed", job_id=job_id)`.
  Don't format values into the event name.
- uvicorn access logs stay off. Prometheus covers request metrics.

## Commits

Every commit uses Conventional Commits: `<type>(<scope>): <description>`.
The release workflow reads commit messages to pick the next version, and a
commit that doesn't match releases nothing.

| Type | Use for | Release today |
| --- | --- | --- |
| `feat` | A new user-visible feature | minor |
| `fix` | A bug fix | patch |
| `chore` | Maintenance, dependencies, tooling | patch |
| `docs` | Documentation only | none |
| `refactor` | A change with no behavior change | none |
| `perf` | A performance improvement | none |
| `test` | Adding or fixing tests | none |
| `ci` | CI changes only | none |

The workflow releases only on `feat`, `fix`, and `chore`. A change of another
type that should ship has to ride with one of those, until
[#77](https://github.com/dannysauer/grimnir/issues/77) is fixed.

`BREAKING CHANGE:` in the commit body is meant to cause a major bump. The
scope is optional and usually names the component, such as `fix(freki):`.

## Pre-commit

Every commit has to pass `pre-commit run --all-files`. Don't pass
`--no-verify` unless the owner asks for it. `.pre-commit-config.yaml` lists
the hooks: file hygiene, ruff, ruff-format, shellcheck, detect-secrets,
actionlint, and the action-pinning check.

Install the tools with `asdf install`, then `pre-commit install`.

`.claude/settings.json` runs the same hooks before any `git commit` that
Claude Code attempts. pre-commit.ci also runs them on every pull request and
pushes its fixes to the branch. `check-yaml` skips
`bifrost/helm/grimnir/templates/`, because Helm's `{{ }}` syntax isn't valid
YAML.

## GitHub Actions

Third-party actions are pinned to full release tags, such as
`actions/checkout@v6.0.2`. A pre-commit hook catches a bare floating tag such
as `@v4`, though not every form
([#83](https://github.com/dannysauer/grimnir/issues/83)). Never commit a
floating tag. The
[accepted record](docs/adrs/2026-04-19-pin-actions-to-release-tags.md) has the
reasoning, and a
[proposed record](docs/adrs/2026-11-15-pin-actions-to-commit-shas.md) would
replace it with commit SHAs. Follow the accepted one until the proposal is
accepted.

Before changing an action's version, check the tag on the action's own
releases page.

## Container builds

Build service images from the repository root, because each Dockerfile copies
and installs `mimir/` first:

```bash
docker build -f freki/Dockerfile -t grimnir/freki .
```

## Secrets

Never commit Wi-Fi credentials, database URLs that contain a password, shared
secrets, kubeconfigs, or `firmware/config.local.h` (`GRM-034`).
