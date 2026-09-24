#!/usr/bin/env bash
# scripts/benchmark-context.sh — Reproducible Context Efficiency Benchmark (v7 vs v8)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
python3 "$SCRIPT_DIR/benchmark_context.py" "$@"
