# Orchestrator Integration Guide (v2.0.0)

## Overview

The AGY-Herdr Software Factory is an orchestrator-agnostic framework for delegating software development workflows across multiple isolated worker identities through Herdr.

The factory architecture enforces a clean separation of concerns:
- **The Orchestrator is the Brain**: An arbitrary LLM, human operator, or autonomous agent (e.g. AGY, Codex, Droid, Claude, Hermes) decides *what* to build by declaring or generating execution plans.
- **The Execution Substrate is Herdr**: Herdr manages isolated terminal panes, workspaces, and Git worktrees without host environment mutation.
- **The Workers are Tool Identities**: Individual worker CLI instances (e.g. `agy`, `agy2`, ..., `agy7`, and future adapters like Codex or Droid) execute specific tasks within constrained workspaces.
- **The Durable State is Project-Local Files**: All operational state, run events, manifests, and ownership registries reside deterministically within the project root under `.agy-factory/`.

```
        arbitrary brain / orchestrator
                     |
                     v
             declarative plan JSON
                     |
                     v
             tools/factory.py
                     |
                     v
                Herdr Server
         /           |           \
        v            v            v
      worker 1     worker 2     worker 3
     (worktree A) (worktree B) (worktree C)
        \            |            /
         v           v           v
           machine-readable results
                     |
                     v
         deterministic validation
                     |
                     v
         integrated git commit
```

---

## Operating Boundary & Contract

An orchestrator interfacing with this factory only needs to:
1. Read `factory.json` to inspect available worker capabilities and configured models.
2. Validate a plan before dispatching:
   ```bash
   python3 tools/factory.py validate-plan plans/minilinks.json
   ```
3. Invoke the Python standard library driver:
   ```bash
   python3 tools/factory.py run plans/minilinks.json
   ```
4. If interrupted, resume execution deterministically:
   ```bash
   python3 tools/factory.py resume <run-id>
   ```
5. Inspect execution status and audit trails:
   ```bash
   python3 tools/factory.py status
   ```
6. Trigger resource cleanup when appropriate:
   ```bash
   python3 tools/factory.py cleanup
   ```

No private agent memory, session state, or conversational context is required to resume, audit, or operate the factory.

---

## Safety and Isolation Invariants

When operating the factory, every orchestrator must uphold these invariants:
1. **Ownership Invariant**:
   ```python
   if resource_id not in owned_resources:
       mutation_forbidden()
   ```
   Never target, inspect destructively, or clean up any Herdr pane, workspace, or session that was not explicitly created during the active factory run. The orchestrator's own pane/workspace is registered as `control_plane` and is strictly protected.
2. **Path Guardrails**:
   Workers operate only inside their isolated worktree (`.agy-factory/worktrees/<run-id>/<task-id>/`). Commits are only accepted if all changed files match the task's allowed glob patterns.
3. **Deterministic Integration Gates**:
   Worker success requires passing deterministic tests (`compileall`, `unittest`, functional smoke tests) executed by the driver outside the worker pane. LLM judgment is never accepted as a substitute for deterministic code verification.
4. **Host Cleanliness**:
   No global packages, sudo commands, or system-wide modifications are permitted. Zero external pip or npm packages are required. Python standard library is used throughout.

---

## Extending with Future Worker Adapters

Future workers (e.g. Codex, Droid, Freebuff) can be registered in `factory.json` without altering the core orchestration driver. Each new adapter requires:
- **Command Adapter**: Path to the executable binary or wrapper.
- **Capabilities**: Supported operations (`implementation`, `review`, `planning`, `testing`, `backend`, `frontend`, `database`).
- **Invocation Protocol**: How the driver feeds prompts and collects structured outputs (e.g. CLI flags, JSON stdin/stdout).
- **Result Parser**: Parser translating worker output into `schemas/worker-result.schema.json` or task-specified schema.
