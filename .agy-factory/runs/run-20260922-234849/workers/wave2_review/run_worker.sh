#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-234849/wave2_review"
"/root/.local/bin/agy6" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-234849/wave2_review"   -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave2_review/prompt.md")"   --model "gemini-3.8-flash-high"   --output-format json   --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave2_review/schema.json")"   > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave2_review/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234849/workers/wave2_review/exit_code.txt"
