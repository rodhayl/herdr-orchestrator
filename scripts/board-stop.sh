#!/usr/bin/env bash
# scripts/board-stop.sh — Stop project-local board daemon or projector service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PID_FILE="$PROJECT_ROOT/.agy-factory/board/board.pid"

if [[ -f "$PID_FILE" ]]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping board service (PID $PID)..."
        kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    echo "Board service stopped."
else
    echo "No board service PID file found."
fi
