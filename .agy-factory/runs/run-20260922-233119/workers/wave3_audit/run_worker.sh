#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-233119/wave3_audit"
"/root/.local/bin/agy7" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-233119/wave3_audit"   -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-233119/workers/wave3_audit/prompt.md")"   --model "gemini-3.8-flash-high"   --output-format json   --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-233119/workers/wave3_audit/schema.json")"   > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-233119/workers/wave3_audit/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-233119/workers/wave3_audit/exit_code.txt"
