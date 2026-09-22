#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-234033/wave1_tests"
"/root/.local/bin/agy5" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-234033/wave1_tests"   -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234033/workers/wave1_tests/prompt.md")"   --model "gemini-3.8-flash-high"   --output-format json   --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234033/workers/wave1_tests/schema.json")"   > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234033/workers/wave1_tests/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-234033/workers/wave1_tests/exit_code.txt"
