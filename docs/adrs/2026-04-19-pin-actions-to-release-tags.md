# ADR: Pin GitHub Actions to full release tags

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-19 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | How workflow files under `.github/workflows/` reference third-party actions. Excludes Docker base images and Python dependencies. |
| Related | [#33](https://github.com/dannysauer/grimnir/issues/33), [#83](https://github.com/dannysauer/grimnir/issues/83); commit `82df419`; proposed replacement [2026-11-15](2026-11-15-pin-actions-to-commit-shas.md) |
| Implementation | `.github/workflows/*.yml`, the `github-action-full-semver-pins` hook in `.pre-commit-config.yaml` |

## Business driver

Workflows referenced actions by floating major tag, such as `@v4`. A floating
tag changes under the workflow without a commit, so a build can change
behavior with nothing in the repository's history to explain it.

## Constraints

- Renovate opens the pull requests that update action versions.
- The rule has to be checkable before a commit lands.

## Decision

**Y statement:** We will reference every third-party action by its full
release tag, such as `actions/checkout@v6.0.2`, because a floating major tag
moves without a commit, so each action upgrade arrives as a reviewable change.

- A `uses:` entry for a third-party action MUST name a full `vX.Y.Z` tag.
- A floating major tag such as `@v4` MUST NOT be committed.

A pre-commit hook rejects a `uses:` reference that ends in anything other than
a full version tag.

## Consequences

- A tag is still mutable. Whoever controls the action's repository can move
  `v6.0.2` to different code.
- `renovate.json5` sets `pinDigests: true`, which asks Renovate to rewrite the
  same lines to commit SHAs, so the repository states two pin rules
  ([#83](https://github.com/dannysauer/grimnir/issues/83)).
- The hook checks only the end of the line. It rejects a bare SHA or a bare
  floating tag, but a reference followed by a comment, or one that uses a
  sub-path such as `owner/repo/path@v4`, isn't checked at all. Renovate's
  `@<sha> # vX.Y.Z` form passes without the rule ever looking at it.

## Alternatives considered

### Keep floating major tags

This was the state before the change. It's the least work, and it lets
upstream change what CI runs without a commit here.

### Pin to commit SHAs

Not recorded as considered in #33. It's the subject of the proposed
[replacement](2026-11-15-pin-actions-to-commit-shas.md).
