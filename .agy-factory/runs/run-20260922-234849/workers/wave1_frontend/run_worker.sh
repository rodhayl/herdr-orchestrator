#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-234849/wave1_frontend"
"/root/.local/bin/agy4" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-234849/wave1_frontend"   -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave1_frontend/prompt.md")"   --model "gemini-3.8-flash-high"   --output-format json   --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave1_frontend/schema.json")"   > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave1_frontend/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave1_frontend/exit_code.txt"
