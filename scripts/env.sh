#!/usr/bin/env bash
# scripts/env.sh — Process-local environment configuration for AGY-Herdr Factory
# Source this file: source scripts/env.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Herdr socket and binary defaults
export HERDR_BIN_PATH="${HERDR_BIN_PATH:-$(which herdr 2>/dev/null || echo "/root/.local/bin/herdr")}"
export HERDR_SOCKET_PATH="${HERDR_SOCKET_PATH:-/root/.config/herdr/herdr.sock}"

# Project-local tools directories
export FACTORY_TOOLS_DIR="$PROJECT_ROOT/.tools"
export FACTORY_BOARD_RUNTIME="$PROJECT_ROOT/.agy-factory/board"
export CARGO_HOME="${FACTORY_TOOLS_DIR}/cargo-home"
export CARGO_TARGET_DIR="${FACTORY_TOOLS_DIR}/cargo-target"

# Prepend project-local bin to PATH if it exists
if [[ -d "${FACTORY_TOOLS_DIR}/bin" ]]; then
    export PATH="${FACTORY_TOOLS_DIR}/bin:$PATH"
fi
