# ADR: Pin GitHub Actions to commit SHAs

## Record

| Field | Value |
| --- | --- |
| Date | 2026-11-15 |
| Status | Proposed |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | How workflow files under `.github/workflows/` reference third-party actions. Excludes Docker base images and Python dependencies. |
| Supersedes | [Pin GitHub Actions to full release tags](2026-04-19-pin-actions-to-release-tags.md), once accepted |
| Related | [#83](https://github.com/dannysauer/grimnir/issues/83), [#3](https://github.com/dannysauer/grimnir/issues/3) |
| Implementation | [#83](https://github.com/dannysauer/grimnir/issues/83) |
| Revisit when | #83 is picked up, or Renovate opens its first digest-pin pull request. |

## Business driver

The release workflows hold a token that can push container images and Helm
charts to `ghcr.io`. They run third-party actions referenced by tag, and a tag
can be moved to different code by whoever controls that action's repository.
The repository also states two rules: `renovate.json5` asks Renovate to pin
actions to digests, and the accepted record and its pre-commit hook ask for
`vX.Y.Z` tags. The hook doesn't check a line that ends in a comment, so it
enforces neither rule on the form Renovate writes
([#83](https://github.com/dannysauer/grimnir/issues/83)).

## Constraints

- Renovate has to keep opening update pull requests without hand edits.
- A person reading a workflow should still see which version is in use.
- The rule has to be checkable before a commit lands.

## Decision

**Y statement:** We will reference every third-party action by its full
commit SHA, followed by a comment that carries the full semantic version,
because a SHA can't be moved to different code the way a tag can, so the code
CI runs with publish rights changes only through a reviewed commit.

A pinned reference looks like this, where the SHA is the commit the `v6.0.2`
tag pointed to when it was pinned:

```yaml
- uses: actions/checkout@<40-character-commit-sha> # v6.0.2
```

- A `uses:` entry for a third-party action MUST name a 40-character commit
  SHA.
- The same line MUST end with a `# vX.Y.Z` comment, which is the form
  Renovate reads and updates.
- A tag or branch reference MUST NOT be committed.

Accepting this record means replacing the `github-action-full-semver-pins`
hook with one that enforces the SHA-and-comment form, and keeping
`pinDigests: true` in `renovate.json5`.

## Consequences

- Renovate's `pinDigests` setting and the pre-commit rule agree, which closes
  the conflict in #83.
- Workflow lines get longer, and the version a person reads is a comment that
  only Renovate keeps honest.
- Local reusable workflows, such as `./.github/workflows/chart-release.yml`,
  aren't third-party and stay as paths.

## Alternatives considered

### Keep the current approach

Full release tags are readable and already enforced. They stay mutable, and
the conflict with `pinDigests` stays unresolved until one side changes.

### Keep tags and turn off digest pinning in Renovate

This resolves #83 in the other direction with a one-line change. It gives up
the protection against a moved tag, on workflows that publish images.
