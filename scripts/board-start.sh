#!/usr/bin/env bash
# scripts/board-start.sh — Start project-local board daemon or projector service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BOARD_BIN="$PROJECT_ROOT/.tools/bin/board"
PID_FILE="$PROJECT_ROOT/.agy-factory/board/board.pid"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Board daemon is already running (PID $(cat "$PID_FILE"))."
    exit 0
fi

if [[ -x "$BOARD_BIN" ]]; then
    echo "Starting project-local herdr-board daemon..."
    export HERDR_SOCKET="${HERDR_SOCKET_PATH:-/root/.config/herdr/herdr.sock}"
    export BOARD_DB="$PROJECT_ROOT/.agy-factory/board/board.db"
    export BOARD_CONFIG="$PROJECT_ROOT/.agy-factory/board/config.toml"
    "$BOARD_BIN" daemon --config "$BOARD_CONFIG" > "$PROJECT_ROOT/.agy-factory/board/board.log" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Board daemon started (PID $(cat "$PID_FILE"))."
else
    echo "[NOTICE] Project-local board binary not present ($BOARD_BIN)."
    echo "Compatibility status is BLOCKED_EXTERNAL_COMPATIBILITY (Herdr 0.9.1 vs herdr-board v0.17.0 pinning Herdr 0.9.0)."
    echo "Factory uses direct machine-readable status projection via 'python3 tools/factory.py board sync'."
    # Write a marker PID file indicating projector active
    echo "$$" > "$PID_FILE"
    echo "Board projector mode active."
fi
