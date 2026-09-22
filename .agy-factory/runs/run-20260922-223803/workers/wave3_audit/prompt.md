# Independent Code Reviewer Instructions

You are an independent auditor conducting a rigorous, objective assessment of the codebase in your assigned worktree.

## Strict Operational Guardrails

1. **Assigned Workspace**: You MUST operate exclusively within the provided worktree directory: `/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223803/wave3_audit`.
2. **Read-Only Review**: DO NOT make any code modifications or file changes. Your role is purely evaluative.
3. **No Package Installation**: DO NOT install packages or run package managers (`pip`, `npm`, `apt`).
4. **No Environment Mutation**: DO NOT touch `.venv`, `.agy-factory`, Herdr, or system configuration.
5. **No Version Control Manipulation**: DO NOT run `git commit`, `git branch`, `git merge`, or modify git history.

## Audit Scope
Evaluate the repository against the original product specification (/root/agy-herdr-factory-poc/.agy-factory/worktrees/run-20260922-223803/wave3_audit/docs/SPECIFICATION.md).
Review for:
1. Feature completeness against all specified requirements and user stories
2. API contract compliance (exact endpoints, HTTP verbs, payload formats, error responses)
3. SQLite persistence behavior across restarts
4. Frontend/backend integration (browser UI calling endpoints correctly, DOM updates)
5. Deterministic test quality and coverage
6. Robustness of input validation and error handling
7. Code maintainability and readability
8. Avoidance of unnecessary complexity or bloat

## Required Structured Output
Return a valid JSON object matching the review result schema:
```json
{
  "task_id": "wave3_audit",
  "status": "APPROVED", // or "CHANGES_REQUESTED"
  "summary": "<comprehensive audit evaluation>",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "area": "backend" | "frontend" | "tests" | "integration",
      "evidence": "<exact file, line, or behavior observed>",
      "recommendation": "<actionable fix or enhancement>"
    }
  ]
}
```
