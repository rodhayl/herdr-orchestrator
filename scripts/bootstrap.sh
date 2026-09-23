#!/usr/bin/env bash
# scripts/bootstrap.sh — Idempotent project-local runtime initialization for AGY-Herdr Software Factory
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== AGY-Herdr Software Factory — Bootstrapping Project Runtime ==="
echo "Project Root: $PROJECT_ROOT"

# 1. Create project runtime directories
mkdir -p "$PROJECT_ROOT/.agy-factory/state"
mkdir -p "$PROJECT_ROOT/.agy-factory/runs"
mkdir -p "$PROJECT_ROOT/.agy-factory/board"
mkdir -p "$PROJECT_ROOT/.agy-factory/worktrees"
mkdir -p "$PROJECT_ROOT/.agy-factory/tmp"
mkdir -p "$PROJECT_ROOT/.tools/bin"
mkdir -p "$PROJECT_ROOT/.tools/cargo-home"
mkdir -p "$PROJECT_ROOT/.tools/cargo-target"

# 2. Initialize project-local board configuration
BOARD_CONFIG="$PROJECT_ROOT/.agy-factory/board/config.toml"
if [[ ! -f "$BOARD_CONFIG" ]]; then
    cat << 'EOF' > "$BOARD_CONFIG"
# Project-local herdr-board configuration
# Managed by AGY-Herdr Software Factory v4.0.0

[server]
host = "127.0.0.1"
port = 7331
socket_path = ".agy-factory/board/board.sock"
database_path = ".agy-factory/board/board.db"

[kanban]
columns = [
    "Backlog",
    "Ready",
    "Running",
    "Blocked",
    "Review",
    "Done",
    "Failed"
]
authority = "factory"
auto_dispatch = false
EOF
    echo "  [+] Initialized project-local board config: .agy-factory/board/config.toml"
else
    echo "  [*] Project-local board config already present."
fi

# 3. Initialize mapping.json if absent
BOARD_MAPPING="$PROJECT_ROOT/.agy-factory/board/mapping.json"
if [[ ! -f "$BOARD_MAPPING" ]]; then
    echo "{}" > "$BOARD_MAPPING"
    echo "  [+] Initialized .agy-factory/board/mapping.json"
fi

# 4. Verify ownership state file exists
OWNED_FILE="$PROJECT_ROOT/.agy-factory/state/owned-resources.json"
if [[ ! -f "$OWNED_FILE" ]]; then
    cat << EOF > "$OWNED_FILE"
{
  "control_plane": {
    "workspace_id": "wK",
    "pane_id": "wK:p1",
    "tab_id": "wK:t1",
    "cwd": "$PROJECT_ROOT",
    "herdr_socket": "/root/.config/herdr/herdr.sock"
  },
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

# 5. Ensure project-local git author identity is set without modifying global config
if ! git config user.name >/dev/null 2>&1; then
    git config user.name "AGY Factory"
    echo "  [+] Configured project-local git user.name"
fi
if ! git config user.email >/dev/null 2>&1; then
    git config user.email "factory@local"
    echo "  [+] Configured project-local git user.email"
fi

echo "=== Bootstrap Completed Successfully ==="
