#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/backend_tests/att-1"
"/root/.local/bin/agy5" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/backend_tests/att-1" \
  -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/backend_tests/att-1/prompt.md")" \
  --model "gemini-3.8-flash-high" \
  --output-format json \
  --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/backend_tests/att-1/schema.json")" \
  > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/backend_tests/att-1/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/backend_tests/att-1/exit_code.txt"
