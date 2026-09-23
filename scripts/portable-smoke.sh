#!/usr/bin/env bash
# scripts/portable-smoke.sh — Clean-room portability rehearsal from committed Git content
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "================================================================================"
echo "AGY-Herdr Software Factory (v4.0.0) — Portable Clean-Checkout Smoke Test"
echo "================================================================================"

TMP_CHECKOUT="$(mktemp -d /tmp/factory-portable-smoke-XXXXXX)"
echo "Created temporary clean checkout directory: $TMP_CHECKOUT"

cleanup() {
    echo "Cleaning up temporary checkout: $TMP_CHECKOUT"
    rm -rf "$TMP_CHECKOUT"
}
trap cleanup EXIT

# 1. Export committed Git content only (zero uncommitted files, zero local runtime artifacts)
cd "$PROJECT_ROOT"
CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "Exporting commit $CURRENT_COMMIT to clean sandbox..."
git archive HEAD | tar -x -C "$TMP_CHECKOUT"

# Verify excluded runtime directories do not exist in clean sandbox
for d in .tools .agy-factory .venv; do
    if [[ -d "$TMP_CHECKOUT/$d" ]]; then
        echo "ERROR: Disallowed runtime directory $d leaked into clean checkout!"
        exit 1
    fi
done

cd "$TMP_CHECKOUT"

echo -e "\n[Step 1/6] Running doctor in clean checkout..."
./scripts/doctor.sh

echo -e "\n[Step 2/6] Running update package check in clean checkout..."
./scripts/update-package.sh --check

echo -e "\n[Step 3/6] Running bootstrap in clean checkout..."
./scripts/bootstrap.sh

echo -e "\n[Step 4/6] Running deterministic verification suite in clean checkout..."
./scripts/verify.sh

echo -e "\n[Step 5/6] Running board startup, sync, and shutdown in clean checkout..."
./scripts/board-start.sh
python3 tools/factory.py board sync
./scripts/board-stop.sh

echo -e "\n[Step 6/6] Confirming no machine-specific absolute path dependencies..."
if grep -rn "/root/agy-herdr-factory-poc" "$TMP_CHECKOUT/scripts/" 2>/dev/null; then
    echo "ERROR: Hardcoded repository path found in scripts!"
    exit 1
fi

echo -e "\n================================================================================"
echo "PORTABLE SMOKE TEST PASSED: Clean checkout executes successfully with zero prior state!"
echo "================================================================================"
