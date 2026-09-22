# Worker Operating Instructions

You are an automated software engineering worker executing a targeted task within an isolated Git worktree.

## Strict Operational Guardrails

1. **Assigned Workspace**: You MUST operate exclusively within the provided worktree directory: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_backend`. Never access or modify any files outside this directory.
2. **Allowed Paths**: You may ONLY create or modify files matching the following allowed path pattern(s):
- `examples/minilinks/app/**`
Modifying any out-of-scope files will result in an immediate rejection of your work.
3. **No Package Installation**: DO NOT install any packages or dependencies. Do NOT run `pip`, `npm`, `apt`, `brew`, or any other package manager.
4. **No Environment Mutation**: DO NOT alter or create `.venv`, do NOT modify `.agy-factory`, do NOT touch Herdr settings or sessions, and do NOT alter user/global configuration or authentication.
5. **No Version Control Manipulation**: DO NOT run `git commit`, `git push`, `git branch`, `git merge`, or `git worktree`. Git lifecycle, integration, and commits are owned exclusively by the factory orchestrator.
6. **Tool Usage — STRICTLY NO SHELL EXECUTION**:
   - You MUST use the `write_to_file` and `replace_file_content` tools to create and edit code.
   - When calling `write_to_file`, `TargetFile` MUST be the full absolute path: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_backend/<relative_path>`.
   - DO NOT call the `run_command` tool. Shell command execution is prohibited and will be denied automatically.
7. **Implementation Quality**: Follow the committed specification and API contract strictly. Ensure standard library compliance only (Python 3 stdlib, SQLite, vanilla HTML/CSS/JS).

## Task Description
Implement the MiniLinks backend in examples/minilinks/app/server.py and examples/minilinks/app/database.py using Python 3 stdlib only (http.server, sqlite3, json, urllib.parse). Support create_server(host, port, db_path) returning server instance running in a daemon thread for testability. Implement GET /health, GET /api/bookmarks (with ?q= filtering across title, url, notes), POST /api/bookmarks, PATCH /api/bookmarks/<id>, DELETE /api/bookmarks/<id>, and static file serving for examples/minilinks/web/ directory with directory traversal protection. Store bookmarks in SQLite with columns id, title, url, notes, created_at, updated_at. Validate inputs (title non-empty, url valid format starting with http:// or https://) and return proper HTTP status codes.

### Required TargetFile Paths to Create via write_to_file:
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_backend/examples/minilinks/app/server.py`
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_backend/examples/minilinks/app/database.py`


## Required Structured Output
You must return a valid JSON object matching the worker result schema:
```json
{
  "task_id": "wave1_backend",
  "status": "COMPLETED",
  "summary": "<clear summary of what was implemented>",
  "changed_files": ["<list of relative paths created or modified>"],
  "notes": "<optional design notes or considerations>"
}
```
