# Orchestrator Integration Guide (v3.0.0)

## Overview

The AGY-Herdr Software Factory is an orchestrator-agnostic framework for delegating arbitrary software development workflows across multiple isolated worker identities through Herdr.

The factory architecture enforces a clean separation of concerns:
- **The Orchestrator is the Brain**: An arbitrary LLM, human operator, or autonomous agent (e.g. AGY, Codex, Droid, Claude, Hermes) decides *what* to build by declaring or generating DAG execution plans.
- **The Factory Core is the Scheduler**: `tools/factory.py` manages the DAG graph, state machine transitions, attempt isolation, atomic persistence, and deterministic verification.
- **The WorkerAdapter is the Invocation Boundary**: A generic adapter boundary decouples core scheduling from worker CLI mechanics. `AgyAdapter` is the certified production adapter.
- **The Execution Substrate is Herdr**: Herdr provides isolated terminal panes, workspaces, and Git worktrees without host environment mutation.
- **The Workers are Tool Identities**: Individual worker CLI instances (`agy`, `agy2`, ..., `agy7`) execute specific tasks within constrained workspaces.
- **The Durable State is Project-Local Files**: All operational state, run events (`events.jsonl`), manifests (`manifest.json`), and ownership registries reside deterministically within `.agy-factory/`.

```
        arbitrary brain / orchestrator
                     |
                     v
             declarative DAG plan
                     |
                     v
             tools/factory.py
         (DAG Scheduler & Engine)
                     |
                     v
               WorkerAdapter
                     |
                AgyAdapter
                     |
                Herdr Server
         /           |           \
        v            v            v
     worker 1     worker 2     worker 3
     (att-1)      (att-1)      (att-1)
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
2. Validate a plan DAG before dispatching:
   ```bash
   python3 tools/factory.py validate-plan plans/minilinks_v3_favorite.json
   ```
3. Invoke the Python standard library driver:
   ```bash
   python3 tools/factory.py run plans/minilinks_v3_favorite.json
   ```
4. If interrupted or crashed, resume execution deterministically:
   ```bash
   python3 tools/factory.py resume <run-id>
   ```
   The engine automatically reconciles on-disk Git commits, branches, and status markers across Cases A through F.
5. Query execution status and machine-readable Kanban projections:
   ```bash
   python3 tools/factory.py status --json
   python3 tools/factory.py status --json --run <run-id>
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
2. **Attempt Isolation**:
   Every worker attempt runs in a dedicated Git worktree and branch (`factory/<run-id>/<task-id>/att-<attempt_id>`). Retries increment the attempt counter, preserving full attempt history.
3. **Path Guardrails**:
   Commits are only accepted if all changed files match the task's allowed glob patterns and pass symlink security inspection.
4. **Deterministic Integration Gates**:
   Worker success requires passing deterministic tests (`compileall`, `unittest`, functional smoke tests) executed by the driver outside the worker pane. LLM judgment is never accepted as a substitute for deterministic code verification.
5. **Merge Conflict Abort**:
   If a merge conflict occurs during parallel branch integration, the engine moves the task to `CONFLICTED`, captures conflict diffs, and executes `git merge --abort` immediately, leaving the repository in a clean state.
6. **Host Cleanliness**:
   No global packages, sudo commands, or system-wide modifications are permitted. Zero external pip or npm packages are required. Python standard library is used throughout.

---

## Roadmap: v4 Integration Contract

The v4 iteration scope is fixed:
1. `DroidAdapter` will be added as the second production `WorkerAdapter`.
2. Deterministic capability-based routing will select workers dynamically.
3. `nelsonPires5/herdr-board` will integrate as a one-way Kanban projection reading the machine-readable JSON contract (`status --json`).
