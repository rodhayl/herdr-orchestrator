#!/bin/bash
set -o pipefail
cd "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave0_spec"
"/root/.local/bin/agy2" --mode accept-edits --add-dir "/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave0_spec"   -p "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave0_spec/prompt.md")"   --model "gemini-3.8-flash-high"   --output-format json   --json-schema "$(< "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave0_spec/schema.json")"   > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave0_spec/output.json" 2>&1
echo $? > "/root/agy-herdr-factory-poc/.agy-factory/runs/run-20260922-231244/workers/wave0_spec/exit_code.txt"
