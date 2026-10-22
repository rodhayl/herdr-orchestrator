#!/usr/bin/env bash
# scripts/portable-smoke.sh — Clean-room portability rehearsal from committed Git content
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Clean-room validation must not invoke provider CLIs, including metadata/auth probes.
export FACTORY_PROVIDER_PROBES=0

echo "================================================================================"
echo "Herdr Orchestrator (v9.0.0) — Portable Clean-Checkout Smoke Test"
echo "================================================================================"

TMP_CHECKOUT="$(mktemp -d /tmp/factory-portable-smoke-XXXXXX)"
echo "Created temporary clean checkout directory: $TMP_CHECKOUT"

cleanup() {
    echo "Cleaning up temporary checkout: $TMP_CHECKOUT"
    rm -rf "$TMP_CHECKOUT"
}
trap cleanup EXIT

# 1. Clone committed Git content to clean sandbox (zero uncommitted files, zero untracked artifacts)
cd "$PROJECT_ROOT"
CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "Cloning commit $CURRENT_COMMIT to clean sandbox..."
git clone "$PROJECT_ROOT" "$TMP_CHECKOUT"

# A clean clone must contain no pre-existing Factory runtime state.
if [[ -e "$TMP_CHECKOUT/.agy-factory" ]]; then
    echo "ERROR: Factory runtime directory .agy-factory leaked into clean checkout!"
    exit 1
fi
for d in .tools .venv; do
    if [[ -e "$TMP_CHECKOUT/$d" ]]; then
        echo "ERROR: Disallowed local directory $d leaked into clean checkout!"
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

echo -e "\n[Step 5/6] Validating profile catalog and Herdr Orchestrator UI sources..."
python3 tools/factory.py profile validate
python3 -m py_compile tools/factory_ui.py

echo -e "\n[Step 6/6] Confirming no machine-specific absolute path dependencies..."
if grep -rn --exclude="portable-smoke.sh" "$PROJECT_ROOT" "$TMP_CHECKOUT/scripts/" 2>/dev/null; then
    echo "ERROR: Hardcoded repository path found in scripts!"
    exit 1
fi

echo -e "\n================================================================================"
echo "PORTABLE SMOKE TEST PASSED: Clean checkout executes successfully with zero prior state!"
echo "================================================================================"
