#!/usr/bin/env bash
# .claude/hooks/pre-commit-check.sh
#
# PreToolUse hook — runs pre-commit before any `git commit` the agent attempts.
#
# Claude Code passes the tool input as JSON on stdin with the structure:
#   { "tool_input": { "command": "git commit ...", ... }, ... }
#
# Exits non-zero (blocking the commit) if pre-commit finds unfixed violations.

set -euo pipefail

# Extract the bash command from the nested tool_input.command field.
cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null || true)

# Only intercept git commit calls.  Pass through everything else.
if ! echo "$cmd" | grep -qE 'git commit'; then
  exit 0
fi

# If --no-verify was explicitly requested, respect it.
if echo "$cmd" | grep -q -- '--no-verify'; then
  exit 0
fi

# Locate the pre-commit executable — prefer the binary on PATH, fall back to
# running it as a Python module (common when installed in a virtualenv).
if command -v pre-commit &>/dev/null; then
  PRE_COMMIT="pre-commit"
elif python3 -m pre_commit --version &>/dev/null 2>&1; then
  PRE_COMMIT="python3 -m pre_commit"
else
  echo "[pre-commit hook] WARNING: pre-commit not found; skipping check." >&2
  exit 0
fi

echo "[pre-commit hook] Running pre-commit before commit…"
$PRE_COMMIT run --all-files
