#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/frontend/att-2"
"/root/.local/bin/agy4" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260923-043032/frontend/att-2" \
  -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/frontend/att-2/prompt.md")" \
  --model "gemini-3.8-flash-high" \
  --output-format json \
  --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/frontend/att-2/schema.json")" \
  > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/frontend/att-2/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260923-043032/workers/frontend/att-2/exit_code.txt"
