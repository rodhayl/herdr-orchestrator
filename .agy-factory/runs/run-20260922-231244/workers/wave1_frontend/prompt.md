# Worker Operating Instructions

You are an automated software engineering worker executing a targeted task within an isolated Git worktree.

## Strict Operational Guardrails

1. **Assigned Workspace**: You MUST operate exclusively within the provided worktree directory: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_frontend`. Never access or modify any files outside this directory.
2. **Allowed Paths**: You may ONLY create or modify files matching the following allowed path pattern(s):
- `examples/minilinks/web/**`
Modifying any out-of-scope files will result in an immediate rejection of your work.
3. **No Package Installation**: DO NOT install any packages or dependencies. Do NOT run `pip`, `npm`, `apt`, `brew`, or any other package manager.
4. **No Environment Mutation**: DO NOT alter or create `.venv`, do NOT modify `.agy-factory`, do NOT touch Herdr settings or sessions, and do NOT alter user/global configuration or authentication.
5. **No Version Control Manipulation**: DO NOT run `git commit`, `git push`, `git branch`, `git merge`, or `git worktree`. Git lifecycle, integration, and commits are owned exclusively by the factory orchestrator.
6. **Tool Usage — STRICTLY NO SHELL EXECUTION**:
   - You MUST use the `write_to_file` and `replace_file_content` tools to create and edit code.
   - When calling `write_to_file`, `TargetFile` MUST be the full absolute path: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_frontend/<relative_path>`.
   - DO NOT call the `run_command` tool. Shell command execution is prohibited and will be denied automatically.
7. **Implementation Quality**: Follow the committed specification and API contract strictly. Ensure standard library compliance only (Python 3 stdlib, SQLite, vanilla HTML/CSS/JS).

## Task Description
Implement the MiniLinks web frontend in examples/minilinks/web/index.html, examples/minilinks/web/style.css, and examples/minilinks/web/app.js. Responsive single-user bookmark manager. Allow creating bookmarks (title, url, notes), search input to filter bookmarks dynamically, edit modal/form to update bookmarks, delete action with confirmation, and notification feedback. Interface directly with /api/bookmarks endpoints using standard fetch API.

### Required TargetFile Paths to Create via write_to_file:
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_frontend/examples/minilinks/web/index.html`
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_frontend/examples/minilinks/web/style.css`
- `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-231244/wave1_frontend/examples/minilinks/web/app.js`


## Required Structured Output
You must return a valid JSON object matching the worker result schema:
```json
{
  "task_id": "wave1_frontend",
  "status": "COMPLETED",
  "summary": "<clear summary of what was implemented>",
  "changed_files": ["<list of relative paths created or modified>"],
  "notes": "<optional design notes or considerations>"
}
```
