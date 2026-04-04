#!/usr/bin/env bash
# .claude/hooks/pre-commit-check.sh
#
# PreToolUse hook — runs pre-commit before any `git commit` the agent attempts.
# Receives the Bash tool's input as JSON on stdin.
# Exits non-zero (blocking the commit) if pre-commit finds unfixed violations.

set -euo pipefail

# Extract the bash command from the tool-input JSON.
cmd=$(python3 -c "import json,sys; print(json.load(sys.stdin).get('command',''))" 2>/dev/null || true)

# Only intercept git commit calls.  Pass through everything else.
if ! echo "$cmd" | grep -qE 'git commit'; then
  exit 0
fi

# If --no-verify was explicitly requested, respect it.
if echo "$cmd" | grep -q -- '--no-verify'; then
  exit 0
fi

echo "[pre-commit hook] Running pre-commit before commit…"
pre-commit run --all-files
