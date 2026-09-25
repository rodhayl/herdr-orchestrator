#!/usr/bin/env bash
# scripts/verify.sh — Comprehensive provider-free deterministic test runner for AGY-Herdr Software Factory
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "================================================================================"
echo "AGY-Herdr Software Factory (v9.0.0) — Deterministic Verification Matrix"
echo "================================================================================"

echo -e "\n[Suite 1/5] Factory Core & State Machine Tests..."
python3 -m unittest discover -s factory_tests -v

echo -e "\n[Suite 2/5] MiniBoard Unit Tests..."
python3 -m unittest discover -s tests -v

echo -e "\n[Suite 3/5] MiniBoard End-to-End Smoke Test..."
python3 scripts/smoke_test.py

echo -e "\n[Suite 4/5] MiniLinks Unit & Persistence Tests..."
python3 -m unittest discover -s examples/minilinks/tests -v

echo -e "\n[Suite 5/5] MiniLinks End-to-End Smoke Test..."
python3 examples/minilinks/scripts/smoke_test.py

echo -e "\n================================================================================"
echo "SUCCESS: All 5 deterministic test suites passed with zero failures or errors!"
echo "================================================================================"
