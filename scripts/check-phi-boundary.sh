#!/usr/bin/env bash
# Fail the build if any code outside the allowlist calls the Anthropic
# client directly (i.e. bypasses the PHI boundary in phi/boundary.py).
#
# Allowed files:
#   backend/tools/claude_api.py — the single retrying wrapper; its
#     call_claude_with_retry routes through phi.boundary.to_external_llm.
#
# Test files (*test*.py) are allowed to reference messages.create for
# mocking in unit tests.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ALLOWED_FILE="backend/tools/claude_api.py"

# Find offenders: anthropic client instantiations or messages.create calls
# in non-test backend code, excluding the allowlist.
violations=$(
  grep -RIn --include='*.py' \
    --exclude='test_*.py' \
    --exclude='*_test.py' \
    --exclude='conftest.py' \
    -E '(messages\.create|anthropic\.(AsyncAnthropic|Anthropic)\()' \
    backend/ \
    | grep -v "^${ALLOWED_FILE}:" \
    | grep -v -E '^backend/phi/' \
    || true
)

if [ -n "$violations" ]; then
  echo "ERROR: PHI boundary bypass detected."
  echo "All calls to the Anthropic client must go through"
  echo "phi.boundary.to_external_llm (wrapped by tools/claude_api.py)."
  echo ""
  echo "Offending lines:"
  echo "$violations"
  exit 1
fi

echo "OK: PHI boundary intact (no direct Anthropic client calls outside ${ALLOWED_FILE})."
