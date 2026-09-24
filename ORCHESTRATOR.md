# Orchestrator Integration Guide (v8.0.0 — Context Efficiency + Deep Hardening)

## Overview

The AGY-Herdr Software Factory is an orchestrator-agnostic framework for delegating arbitrary software development workflows across multiple isolated worker identities through Herdr.

In **v8.0.0 (Context Efficiency + Deep Hardening)**, the orchestration pipeline is supercharged with a deterministic `ContextCompiler`, achieving 75.1% context byte reduction, 100% required anchor recall, zero orphan requirements, and bounded semantic handoffs:

```
               USER / EXTERNAL BRAIN
                       |
                       v
                 HIGH-LEVEL GOAL
                       |
                       v
                Goal Controller
                       |
          +------------+-------------+
          |                          |
          v                          v
   Project Policy               Goal Spec
          |                          |
          +------------+-------------+
                       |
                       v
                 Planner Profile
                       |
                       v
              Requirements + DAG
                       |
                       v
              Deterministic Gates
                       |
                       v
                Plan Reviewer
                       |
                       v
              Approved DAG Plan v2
                       |
                       v
            Deterministic Routing
                       |
                       v
              FactoryOrchestrator
                       |
           +-----------+-----------+
           |                       |
           v                       v
       Worker 1                 Worker 2
  (Isolated Worktree)      (Isolated Worktree)
           |                       |
           +-----------+-----------+
                       |
                       v
         Deterministic Validations
                       |
                       v
            Independent Final Audit
                       |
                       v
               Finished Project
```

---

## Operating Boundary & Contract

### 1. High-Level Project Autopilot (v7 Recommended Mode)

To run autonomous project autopilot on an external or local repository:

```bash
# Initialize project policy in target repository
python3 tools/factory.py --project-root /path/to/target-project project init --name "MyProject"

# Run project doctor check
python3 tools/factory.py --project-root /path/to/target-project project doctor

# Execute autonomous goal controller
python3 tools/factory.py --project-root /path/to/target-project goal run --goal-file /path/to/GOAL.md --real-only

# If interrupted or halted, resume durably from last phase without duplicate task execution
python3 tools/factory.py --project-root /path/to/target-project goal resume --goal-id <goal-id>

# Query goal progress and validation/audit report
python3 tools/factory.py --project-root /path/to/target-project goal report --goal-id <goal-id>
```

### 2. Low-Level DAG Execution (Backward-Compatible Engine Mode)

An orchestrator interfacing directly with DAG plans can also invoke the core engine:

```bash
# Validate plan traceability and structure
python3 tools/factory.py validate-plan plans/my_plan.json

# Execute DAG plan
python3 tools/factory.py run plans/my_plan.json

# Reconcile interrupted run
python3 tools/factory.py resume <run-id>
```

---

## Safety and Isolation Invariants

When operating the factory, every orchestrator must uphold these invariants:

1. **Ownership Invariant**:
   ```python
   if resource_id not in owned_resources:
       mutation_forbidden()
   ```
   Never target, inspect destructively, or clean up any Herdr pane, workspace, or session that was not explicitly created during the active factory run. The orchestrator's own pane/workspace is registered as `control_plane` and is strictly protected.

2. **Target Isolation**:
   The factory operates cleanly on external projects without writing artifacts into the target repository's committed tree. All runtime state resides in `<project_root>/.agy-factory/`.

3. **Dirty Git Fail-Closed Guard**:
   Target repositories must be clean Git working trees before autopilot begins execution.

4. **Attempt Isolation**:
   Every worker attempt runs in a dedicated Git worktree and branch (`factory/<run-id>/<task-id>/att-<attempt_id>`). Retries increment the attempt counter, preserving full attempt history.

5. **Traceability & Validation Contracts**:
   Every task in an approved plan must specify `satisfies` referencing acceptance criteria and define non-empty, safe deterministic `validations`.

6. **Certification Provenance Invariant**:
   `execution_mode` is strictly tracked as `REAL`, `MOCK`, `TRANSPORT_ONLY`, or `UNKNOWN`. Only genuine provider executions with verifiable binary identities, non-fixture executables, and authentic output hashes can achieve `REAL_PROVIDER_CERTIFIED`.

7. **Host Cleanliness**:
   No global packages, sudo commands, or system-wide modifications are permitted. Zero external pip or npm packages are required. Python 3 standard library is enforced throughout.
