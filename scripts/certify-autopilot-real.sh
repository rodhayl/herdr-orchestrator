#!/usr/bin/env bash
# scripts/certify-autopilot-real.sh — Real-Provider Project Autopilot End-to-End Certification Runner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FACTORY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_PROJECT="/root/treehash-project"

echo "================================================================================"
echo "AGY-Herdr Software Factory (v7.0.0) — Real Provider Autopilot Certification"
echo "Target Project: $TARGET_PROJECT"
echo "================================================================================"

# Enforce no test harness simulation during real verification
unset FACTORY_TEST_HARNESS || true
export FACTORY_REAL_ONLY=1

echo -e "\n[1. Preflight Diagnostics & Authentication Verification]"
if ! agy models | grep -q "gemini-3.8-flash"; then
    echo "  [FAIL] AGY authentication failed or model gemini-3.8-flash unavailable." >&2
    exit 1
fi
echo "  [OK] AGY CLI authenticated with live model catalog."

echo -e "\n[2. Setting Up Isolated External Target Project: $TARGET_PROJECT]"
rm -rf "$TARGET_PROJECT"
mkdir -p "$TARGET_PROJECT"
cd "$TARGET_PROJECT"

git init -b main
git config user.name "TreeHash Autopilot"
git config user.email "autopilot@treehash.local"

# Write initial README.md
cat <<'EOF' > README.md
# TreeHash

Deterministic Merkle Directory Hashing Utility and Python Library.
EOF

# Initialize starter project policy
python3 "$FACTORY_DIR/tools/factory.py" --project-root "$TARGET_PROJECT" project init --name "TreeHash"

# Write production real-only policy
cat <<'EOF' > factory.project.json
{
  "project_name": "TreeHash",
  "version": "1.0.0",
  "execution_policy": {
    "mode": "real_only",
    "planner_model": "gemini-3.8-flash-high",
    "plan_reviewer_profile": "agy-audit-high",
    "final_auditor_profile": "agy-audit-high"
  },
  "routing_overrides": {
    "task_core_impl": "agy-backend-high",
    "task_cli_impl": "agy-backend-high",
    "task_unit_tests": "agy-tests-medium"
  },
  "limits": {
    "max_tasks": 10,
    "max_plan_revisions": 2,
    "max_remediation_rounds": 2,
    "max_retries_per_task": 2,
    "max_task_duration_seconds": 600
  },
  "allowed_paths": [
    "**"
  ],
  "forbidden_paths": [
    ".git/**",
    "*.key",
    "*.secret",
    ".env"
  ]
}
EOF

# Write TreeHash Goal Specification
cat <<'EOF' > GOAL.md
# TreeHash — Deterministic Merkle Directory Hashing Utility

Build a deterministic cryptographic directory and Merkle tree hashing utility and Python library using Python 3 standard library only.

## Requirements

1. R1: Content SHA-256 Hashing — Deterministic file content SHA-256 hashing.
2. R2: Merkle Node Hashing — Directory Merkle node hashing using sorted child entries: hash(sorted(name + ":" + child_hash)).
3. R3: Empty Directory Handling — Empty directories must have a deterministic canonical empty-node hash.
4. R4: Symlink Handling — Configurable symlink behavior (--follow-symlinks vs default --no-follow-symlinks).
5. R5: Ignore Patterns — Automatically ignore .git, __pycache__, *.pyc, and optional .treehashignore patterns.
6. R6: Lexicographical Ordering — Deterministic canonical lexicographical path sorting regardless of filesystem traversal order.
7. R7: CLI Compute — CLI command `treehash compute <path>` (or `python3 -m treehash compute <path>`) computes and prints the root tree hash.
8. R8: CLI Formatting — Output formats: `--format text` (default, printing root hash) and `--format json` (full Merkle manifest).
9. R9: CLI Verify — CLI command `treehash verify <path> <manifest.json>` verifying an existing directory against a manifest (exit code 0 on match, 1 on mismatch).
10. R10: Python Library API — Python library module exporting `compute_tree_hash(path, ...)` and `verify_tree_hash(path, manifest, ...)`.
11. R11: Error Handling — Clean error handling, reporting errors to stderr and exiting with non-zero exit codes on missing paths or errors.
12. R12: Unit Test Suite — Comprehensive deterministic test suite in `tests/` passing 100% under `python3 -m unittest discover -s tests -v`.

## Constraints & Policy

Constraints: Python 3 standard library only (hashlib, os, sys, pathlib, argparse, json, unittest).
Non-goals: Do not use external packages, pip dependencies, or remote network operations.
EOF

# Commit initial state to ensure clean repository
git add -A
git commit -m "chore: initial TreeHash repository setup"

echo "  [OK] Isolated target repository initialized and committed at $TARGET_PROJECT"

echo -e "\n[3. Executing Fully Autonomous Goal Controller (real_only mode)]"
cd "$FACTORY_DIR"
python3 "$FACTORY_DIR/tools/factory.py" --project-root "$TARGET_PROJECT" goal run --goal-file "$TARGET_PROJECT/GOAL.md" --real-only

echo -e "\n[4. Verifying Autopilot State and Certification Guard]"
# Find goal ID
GOAL_ID=$(python3 -c "import pathlib, json
goals = list((pathlib.Path('$TARGET_PROJECT') / '.agy-factory' / 'goals').glob('goal-*'))
if not goals:
    print('')
else:
    print(goals[0].name)
")

if [[ -z "$GOAL_ID" ]]; then
    echo "  [FAIL] No goal state found in $TARGET_PROJECT/.agy-factory/goals" >&2
    exit 1
fi

REPORT_JSON=$(python3 "$FACTORY_DIR/tools/factory.py" --project-root "$TARGET_PROJECT" goal report "$GOAL_ID")
FINAL_PHASE=$(echo "$REPORT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('phase'))")
RUN_ID=$(echo "$REPORT_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('run_id'))")

echo "  Goal ID:     $GOAL_ID"
echo "  Run ID:      $RUN_ID"
echo "  Final Phase: $FINAL_PHASE"

if [[ "$FINAL_PHASE" != "COMPLETE" ]]; then
    echo "  [FAIL] Autopilot goal did not reach COMPLETE phase (current: $FINAL_PHASE)" >&2
    exit 1
fi

echo "  [+] Checking real-provider certification guard for run $RUN_ID..."
python3 "$FACTORY_DIR/tools/factory.py" --project-root "$TARGET_PROJECT" certify guard "$RUN_ID"

echo -e "\n[5. Deterministic Unit Tests Execution in Target Project]"
cd "$TARGET_PROJECT"
python3 -m unittest discover -s tests -v

echo -e "\n[6. Functional Smoke Testing of TreeHash CLI]"
TEST_DIR=$(mktemp -d /tmp/treehash-smoke-XXXXXX)
mkdir -p "$TEST_DIR/sub"
echo "file A" > "$TEST_DIR/a.txt"
echo "file B" > "$TEST_DIR/sub/b.txt"

echo "  [+] Computing text hash..."
HASH_TEXT=$(python3 -m treehash compute "$TEST_DIR" --format text)
echo "      TreeHash Root: $HASH_TEXT"

echo "  [+] Computing JSON manifest..."
python3 -m treehash compute "$TEST_DIR" --format json > "$TEST_DIR/manifest.json"

echo "  [+] Verifying manifest match..."
python3 -m treehash verify "$TEST_DIR" "$TEST_DIR/manifest.json"
echo "      Verification match PASSED (exit code 0)"

echo "  [+] Verifying tamper detection (mismatch)..."
echo "tampered" >> "$TEST_DIR/a.txt"
if python3 -m treehash verify "$TEST_DIR" "$TEST_DIR/manifest.json" >/dev/null 2>&1; then
    echo "  [FAIL] Tampered tree unexpectedly passed verification!" >&2
    rm -rf "$TEST_DIR"
    exit 1
else
    echo "      Tamper detection PASSED (exit code 1 on mismatch)"
fi
rm -rf "$TEST_DIR"

echo -e "\n[7. Exporting Autopilot Certification Bundle]"
mkdir -p "$FACTORY_DIR/certification/v7"
python3 -c "import pathlib, json
evidence = {
    'certification_id': 'v7-autopilot-treehash-real',
    'certified_at': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
    'target_project': '$TARGET_PROJECT',
    'goal_id': '$GOAL_ID',
    'run_id': '$RUN_ID',
    'status': 'REAL_PROVIDER_CERTIFIED',
    'phase': '$FINAL_PHASE',
    'report': json.loads('''$REPORT_JSON''')
}
with open('$FACTORY_DIR/certification/v7/autopilot-real-certification.json', 'w', encoding='utf-8') as f:
    json.dump(evidence, f, indent=2)
"

echo "================================================================================"
echo "CERTIFICATION SUCCESS: Project Autopilot completed end-to-end with genuine providers!"
echo "Bundle: $FACTORY_DIR/certification/v7/autopilot-real-certification.json"
echo "================================================================================"
