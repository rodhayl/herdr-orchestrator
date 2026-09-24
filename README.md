# AGY-Herdr Software Factory (v8.0.0 — Context Efficiency + Deep Hardening)

A project-local, orchestrator-agnostic autonomous software factory proving that an arbitrary brain/orchestrator can delegate the end-to-end specification, parallel implementation, deterministic verification, and independent audit of complete applications and features across multiple isolated worker identities through Herdr.

---

## 1. What This Factory Proves

1. **Context Efficiency Engine (v8.0.0)**: Delivers 75.1% prompt/context byte reduction with 100.0% required anchor recall, zero orphan requirements, and bounded semantic handoffs ($\le 4,096$ bytes) via the deterministic `ContextCompiler`.
2. **Orchestrator Independence**: Any brain (AGY, Codex, Claude, Droid, human) can orchestrate development by issuing declarative DAG plans or natural-language Goal Specs and executing a standard-library driver.
3. **Generic WorkerAdapter Architecture**: A clean adapter boundary separates factory core orchestration from worker execution. `AgyAdapter`, `DroidAdapter`, `CodexAdapter`, `ClaudeAdapter`, and `OpenCodeAdapter` plug in without rewriting scheduler, state, or Git logic.
4. **Autonomous Goal Controller (Project Autopilot)**: End-to-end autonomous lifecycle (`Goal -> Discovery -> GoalSpec -> Traceable Plan v2 DAG -> Independent Plan Review -> Bounded Revision -> Routing / Execution -> Post-Validation -> Independent Final Audit -> Bounded Remediation -> Complete`).
5. **Durable State Machine & First-Class Attempts**: Explicit canonical states, atomic JSON writes (`atomic_write_json`), append-only event logging (`events.jsonl`), and monotonic attempt isolation (`att-{attempt_id}`).
6. **Reconciliation-Based Resume**: Resuming an interrupted or crashed run (`factory.py resume <run_id>`) inspects reality (Git commits, branches, status files) across Cases A through F, preventing duplicate work, duplicate commits, or duplicate merges.
7. **Deterministic Failure Injection & Conflict Handling**: Inert-in-production failpoints (`FACTORY_TEST_FAILPOINT`) verify crash recovery; explicit merge conflict detection records unmerged diffs and safely executes `git merge --abort`.
8. **Concurrent Run Isolation**: Multiple factory runs operate simultaneously without cross-run ownership contamination or accidental cleanup interference.
9. **Zero Host Pollution**: Strict Python 3 standard library operation—zero external pip packages, no `.venv`, no `sudo`, and zero modification to host configuration.
10. **Certified Multi-Application Reusability**: Successfully built and verified **MiniBoard**, **MiniLinks**, **MiniLinks Favorite/Star**, and genuine real-provider **TreeHash v8** Merkle directory hashing.

---

## 2. Architecture & Boundary

```
                  arbitrary orchestrator
                            |
                            v
                     declarative DAG plan
              (plans/minilinks_v3_favorite.json)
                            |
                            v
                    tools/factory.py
              (DAG Scheduler & State Engine)
                            |
                            v
                      WorkerAdapter
                            |
                       AgyAdapter
                            |
                          Herdr
                   /        |        \
                  v         v         v
                agy3      agy4      agy5
              (backend) (frontend)  (tests)
                  |         |         |
                att-1     att-1     att-1
                   \        |        /
                    \       |       /
                     v      v      v
                   deterministic gates
               (compileall + unittests + smoke)
                            |
                            v
                          agy6
                 (repair / integration)
                            |
                            v
                          agy7
                  (independent audit)
```

### Components
- **Control Plane**: The existing Herdr workspace (`wK`) and pane (`wK:p1`) from which the orchestrator runs.
- **Factory Engine (`tools/factory.py`)**: Python 3 stdlib driver managing task lifecycles, worktrees, Herdr panes, merges, deterministic gates, and resume.
- **Worker Registry (`factory.json`)**: Declarative definitions for each worker identity and future adapter templates.
- **Plan Schema**: Declarative DAG JSON declaring tasks, worker identities, explicit dependencies, allowed paths, context files, and post-validation commands.
- **Worktrees (`.agy-factory/worktrees/`)**: Isolated Git worktrees per run, task, and attempt (`att-{attempt_id}`) where workers modify code without touching the main working tree.
- **Audit & Evidence (`.agy-factory/runs/`)**: Full audit trails of prompts, outputs, diffs, tokens, event logs (`events.jsonl`), and manifest state (`manifest.json`).

---

## 3. Ownership & Isolation Invariant

The factory strictly enforces the ownership boundary:
```python
if resource_id not in owned_resources:
    mutation_forbidden()
```
- Every Herdr workspace or pane created by the factory is recorded immediately in `.agy-factory/state/owned-resources.json` under run-scoped tracking.
- Pre-existing Herdr resources (other projects, active agents) are read-only baseline references and are **never** mutated, stopped, or cleaned up.
- The control plane itself is registered as protected and excluded from cleanup.

> [!IMPORTANT]
> **Security Boundary Notice**: Factory path guardrails enforce Git allowlists, expected target files, and symlink escape checks before committing. They operate at the application/commit gate and do **not** constitute an OS kernel sandbox.

---

## 4. Worker Registry & Readiness

| Worker Identity | Script / Binary | Profile Home | Capabilities | Adapter | Default Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `agy` | `/root/.local/bin/agy` | `/root/.agy_home` | general, orchestration | `agy` | Primary CLI (control plane) |
| `agy2` | `/root/.local/bin/agy2` | `/root/.agy2_home` | planning, specification | `agy` | Product Specification |
| `agy3` | `/root/.local/bin/agy3` | `/root/.agy3_home` | implementation, backend, database | `agy` | Backend / SQLite Storage |
| `agy4` | `/root/.local/bin/agy4` | `/root/.agy4_home` | implementation, frontend | `agy` | Frontend UI (HTML/CSS/JS) |
| `agy5` | `/root/.local/bin/agy5` | `/root/.agy5_home` | implementation, testing | `agy` | Test Suite & Smoke Harness |
| `agy6` | `/root/.local/bin/agy6` | `/root/.agy6_home` | review, repair, integration | `agy` | Integration Quality & Repair |
| `agy7` | `/root/.local/bin/agy7` | `/root/.agy7_home` | review, audit, evaluation | `agy` | Independent Final Audit |

### Future Worker Family Readiness (v4 Scope)
The `WorkerAdapter` interface decouples the factory core from worker CLI mechanics. The v4 iteration is fixed: adding `DroidAdapter` and deterministic capability-based routing alongside one-way `nelsonPires5/herdr-board` projection.

---

## 5. Usage & Operations

### Validating a Plan
Validates DAG integrity, duplicate task IDs, unknown workers, missing dependencies, cycles, and unsafe path escapes before execution:
```bash
python3 tools/factory.py validate-plan plans/minilinks_v3_favorite.json
```

### Running a Plan
Executes the declarative orchestration DAG end-to-end:
```bash
python3 tools/factory.py run plans/minilinks_v3_favorite.json
```

### Resuming an Interrupted Run
Resumes an interrupted or partial factory run, reconciling reality against on-disk commits and artifacts:
```bash
python3 tools/factory.py resume run-<timestamp>
```

### Checking Status (CLI and JSON)
Inspects active and past runs, task states, and owned resources:
```bash
python3 tools/factory.py status
```

Machine-readable JSON projection for Kanban / automated tooling:
```bash
python3 tools/factory.py status --json
python3 tools/factory.py status --json --run run-<timestamp>
```

### Safe Cleanup
Removes only project-owned Herdr workspaces, Git worktrees, and ephemeral scratch files:
```bash
python3 tools/factory.py cleanup
```

### Running Factory Self-Tests
Runs the comprehensive 35-test unit suite verifying DAG execution, adapter lookup, timeout isolation, failpoints, merge conflict aborts, symlink escapes, and status projections:
```bash
python3 -m unittest discover -s factory_tests -v
```

---

## 6. Built Applications

### 1. MiniBoard (`./`)
Local single-user Kanban task board:
- **Backend**: Python 3 `http.server` with `sqlite3` persistence (`app/server.py`, `app/database.py`).
- **Frontend**: Vanilla responsive HTML/CSS/JS with TODO, DOING, and DONE columns (`web/`).
- **Tests**: 34 passing unit tests (`tests/test_api.py`, `tests/test_persistence.py`) and 12-step standalone smoke verification (`scripts/smoke_test.py`).
- **Verification**: `python3 -m unittest discover -s tests -v` (34/34 passing), `python3 scripts/smoke_test.py` (12/12 steps passing).

### 2. MiniLinks (`examples/minilinks/`)
Local single-user bookmark manager with certified Favorite/Star feature:
- **Specification**: `examples/minilinks/SPEC.md` authored by `agy2`.
- **Backend**: Python 3 `http.server` with `sqlite3` store, `/health`, search filtering `?q=`, favorite filtering `?favorites=true`, and boolean SQLite table migration (`examples/minilinks/app/`).
- **Frontend**: Vanilla responsive HTML/CSS/JS with search, star toggle buttons (★/☆), favorite filters, modal dialogs, and toast notifications (`examples/minilinks/web/`).
- **Tests**: 30 passing unit tests (`examples/minilinks/tests/`) and 12-step standalone smoke verification (`examples/minilinks/scripts/smoke_test.py`).
- **Audit**: Independent audit by `agy7` produced `APPROVED` status with 0 critical, 0 major findings.
- **Verification**: `python3 -m unittest discover -s examples/minilinks/tests -v` (30/30 passing), `python3 examples/minilinks/scripts/smoke_test.py` (12/12 steps passing).
