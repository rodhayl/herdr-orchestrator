#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_backend"
"/root/.local/bin/agy3" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_backend"   -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave1_backend/prompt.md")"   --model "gemini-3.8-flash-high"   --output-format json   --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave1_backend/schema.json")"   > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave1_backend/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave1_backend/exit_code.txt"
