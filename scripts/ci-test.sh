#!/usr/bin/env bash
# CI-oriented test runner for run-coach-agent (no real LLM).
#
# Usage (from repo root):
#   ./scripts/ci-test.sh
#
# Required env for scenarios (and any DB-backed tests):
#   export TEST_DATABASE_URL="postgresql+asyncpg://postgres:<pass>@localhost:5432/run_coach_test"
#   export ADMIN_DATABASE_URL="postgresql+asyncpg://postgres:<pass>@localhost:5432/postgres"
#
# Unit tests alone do not need Postgres:
#   cd backend && uv run pytest tests/unit -q
#
# Default CI path runs unit + scenarios with ScriptedReasoner (no LLM_API_KEY).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"

cd "$BACKEND"

echo "==> ruff (quick)"
if uv run ruff --version >/dev/null 2>&1; then
  uv run ruff check app tests
else
  echo "    ruff not available via uv; skipping"
fi

if [[ -z "${TEST_DATABASE_URL:-}" || -z "${ADMIN_DATABASE_URL:-}" ]]; then
  echo ""
  echo "ERROR: scenarios need Postgres. Export before running this script:"
  echo "  TEST_DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/run_coach_test"
  echo "  ADMIN_DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/postgres"
  echo ""
  echo "Unit-only (no DB):  uv run pytest tests/unit -q"
  exit 1
fi

echo "==> pytest tests/unit tests/scenarios (ScriptedReasoner, no real LLM)"
uv run pytest tests/unit tests/scenarios -q
