#!/usr/bin/env bash
# scripts/board.sh — Wrapper for herdr-board projector and status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 "$PROJECT_ROOT/tools/factory.py" board "$@"
