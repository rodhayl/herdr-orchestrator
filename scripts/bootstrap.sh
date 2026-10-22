#!/usr/bin/env bash
# scripts/bootstrap.sh — Idempotent project-local runtime initialization for Herdr Orchestrator
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Herdr Orchestrator — Bootstrapping Project Runtime ==="
echo "Project Root: $PROJECT_ROOT"

mkdir -p "$PROJECT_ROOT/.agy-factory/state"
mkdir -p "$PROJECT_ROOT/.agy-factory/runs"
mkdir -p "$PROJECT_ROOT/.agy-factory/worktrees"
mkdir -p "$PROJECT_ROOT/.agy-factory/tmp"
mkdir -p "$PROJECT_ROOT/.agy-factory/evidence"
mkdir -p "$PROJECT_ROOT/.agy-factory/logs"

OWNED_FILE="$PROJECT_ROOT/.agy-factory/state/owned-resources.json"
if [[ ! -f "$OWNED_FILE" ]]; then
    # The active Herdr client supplies observed control-plane metadata later.
    # Do not seed a fictitious workspace, pane or machine-specific socket.
    cat << 'EOF' > "$OWNED_FILE"
{
  "owned": {
    "workspace_ids": [],
    "pane_ids": [],
    "branches": [],
    "worktrees": []
  },
  "runs": {}
}
EOF
    echo "  [+] Initialized .agy-factory/state/owned-resources.json"
fi

if ! git -C "$PROJECT_ROOT" config user.name >/dev/null 2>&1; then
    git -C "$PROJECT_ROOT" config --local user.name "Herdr Orchestrator"
    echo "  [+] Configured project-local git user.name"
fi
if ! git -C "$PROJECT_ROOT" config user.email >/dev/null 2>&1; then
    git -C "$PROJECT_ROOT" config --local user.email "factory@local"
    echo "  [+] Configured project-local git user.email"
fi

echo "=== Bootstrap Completed Successfully ==="
