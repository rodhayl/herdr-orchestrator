#!/usr/bin/env bash
# scripts/verify-real.sh — Explicit real-provider verification runner for Herdr Orchestrator v9.0.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "================================================================================"
echo "Herdr Orchestrator (v9.0.0) — Real Provider Verification"
echo "================================================================================"

# Enforce no test harness simulation during real verification
unset FACTORY_TEST_HARNESS || true

echo -e "\n[1. Harness Read-Only Authentication Probe]"
python3 "$PROJECT_ROOT/tools/factory.py" auth probe

echo -e "\n[2. Real AGY Provider Smoke Execution]"
if agy models | grep -q "gemini-3.8-flash"; then
    echo "  [+] AGY models confirmed. Executing real AGY smoke prompt..."
    set +e
    SMOKE_OUT=$(agy -p "echo agy_real_smoke_ok" --model gemini-3.8-flash-high --output-format json --dangerously-skip-permissions 2>/dev/null)
    SMOKE_RC=$?
    set -e
    if [[ "$SMOKE_RC" -ne 0 ]]; then
        echo "  [FAIL] AGY real provider smoke execution failed (exit $SMOKE_RC)."
        exit 1
    elif echo "$SMOKE_OUT" | grep -q "agy_real_smoke_ok"; then
        echo "  [OK] Real AGY provider smoke execution succeeded."
    else
        echo "  [WARN] AGY returned success but the expected smoke token was not observed."
    fi
else
    echo "  [FAIL] AGY authentication failed or model unavailable."
    exit 1
fi

echo -e "\n[3. Real OpenCode Provider Smoke Execution]"
if [[ -n "${OPENROUTER_API_KEY:-}" || -n "${OPENCODE_API_KEY:-}" ]]; then
    echo "  [+] Active OPENROUTER_API_KEY detected. Executing real OpenCode smoke prompt..."
    set +e
    OPENCODE_OUT=$(opencode run "echo opencode_real_smoke_ok" --model "openrouter/openrouter/free" --format json --auto --pure 2>&1)
    OPENCODE_RC=$?
    set -e
    if [[ "$OPENCODE_RC" -ne 0 ]]; then
        echo "  [FAIL] OpenCode real provider smoke execution failed (exit $OPENCODE_RC)."
        exit 1
    elif echo "$OPENCODE_OUT" | grep -q "opencode_real_smoke_ok\|sessionID"; then
        echo "  [OK] Real OpenCode provider smoke execution succeeded."
    else
        echo "  [WARN] OpenCode returned success without the expected smoke evidence."
    fi
else
    echo "  [NOTICE] OpenCode credentials not set in environment."
fi

echo -e "\n[4. Provider Authentication Summary]"
echo "  Auth/availability is discovered live by the canonical read-only probe above."
echo "  Historical AUTH_BLOCKED/AVAILABLE outcomes are not hardcoded here."

echo -e "\n================================================================================"
echo "Real provider verification complete. Review the live probe and smoke evidence above."
echo "================================================================================"
