#!/usr/bin/env bash
# scripts/verify.sh — Comprehensive provider-free deterministic test runner for Herdr Orchestrator
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Deterministic verification must not execute provider metadata/auth probes.
export FACTORY_PROVIDER_PROBES=0

cd "$PROJECT_ROOT"

VERIFY_HEAD_BEFORE="$(git rev-parse HEAD)"
VERIFY_STATUS_BEFORE="$(git status --porcelain=v1 --untracked-files=all)"

echo "================================================================================"
echo "Herdr Orchestrator (v9.0.0) — Deterministic Verification Matrix"
echo "================================================================================"

echo -e "\n[Suite 1/5] Factory Core, Control UI & State Machine Tests..."
python3 -m unittest discover -s factory_tests -v

echo -e "\n[Suite 2/5] MiniBoard Unit Tests..."
python3 -m unittest discover -s tests -v

echo -e "\n[Suite 3/5] MiniBoard End-to-End Smoke Test..."
python3 scripts/smoke_test.py

echo -e "\n[Suite 4/5] MiniLinks Unit & Persistence Tests..."
python3 -m unittest discover -s examples/minilinks/tests -v

echo -e "\n[Suite 5/5] MiniLinks End-to-End Smoke Test..."
python3 examples/minilinks/scripts/smoke_test.py

VERIFY_HEAD_AFTER="$(git rev-parse HEAD)"
VERIFY_STATUS_AFTER="$(git status --porcelain=v1 --untracked-files=all)"
if [[ "$VERIFY_HEAD_AFTER" != "$VERIFY_HEAD_BEFORE" ]]; then
    echo "ERROR: deterministic verification changed Git HEAD ($VERIFY_HEAD_BEFORE -> $VERIFY_HEAD_AFTER)." >&2
    exit 1
fi
if [[ "$VERIFY_STATUS_AFTER" != "$VERIFY_STATUS_BEFORE" ]]; then
    echo "ERROR: deterministic verification changed tracked/untracked Git status." >&2
    diff -u <(printf '%s\n' "$VERIFY_STATUS_BEFORE") <(printf '%s\n' "$VERIFY_STATUS_AFTER") || true
    exit 1
fi

echo -e "\n================================================================================"
echo "SUCCESS: All 5 deterministic test suites passed with zero failures/errors and preserved Git state!"
echo "================================================================================"
