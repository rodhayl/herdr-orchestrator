# AGY-Herdr Software Factory (v2.0.0)

A project-local, orchestrator-agnostic autonomous software factory demonstrating that an arbitrary brain/orchestrator can delegate the end-to-end specification, parallel implementation, deterministic verification, and independent audit of complete applications across multiple isolated worker identities through Herdr.

---

## 1. What This Factory Proves

1. **Orchestrator Independence**: Any brain (AGY, Codex, Claude, Droid, human) can orchestrate development by issuing declarative plan JSONs and executing a standard library driver.
2. **Infrastructure Reusability without Disruption**: The user's pre-existing Herdr server, sessions, and workspaces act as the execution substrate without creating separate sessions or mutating existing panes.
3. **Multi-Worker Identity Delegation**: Distinct worker identities (`agy`, `agy2`, ..., `agy7`) with separate private authentication profiles are dispatched to specialized roles.
4. **True Concurrency**: Multiple workers operate in parallel within isolated Git worktrees and Herdr workspaces with overlapping timestamps.
5. **Deterministic Integration**: Code quality and correctness are gated strictly by standard library compilation and test suites, not LLM opinion.
6. **Zero Host Pollution**: Strict standard library Python implementation—no `pip` installs outside local `.venv`, no `sudo`, and zero modification to host configuration.
7. **Multi-Application Reusability**: The factory core builds completely unrelated applications (**MiniBoard** and **MiniLinks**) purely from declarative plans without engine code modifications.

---

## 2. Architecture & Boundary

```
                  arbitrary orchestrator
                            |
                            v
                     declarative plan
                    (plans/minilinks.json)
                            |
                            v
                    tools/factory.py
                            |
                            v
                          Herdr
                   /        |        \
                  v         v         v
                agy3      agy4      agy5
              (backend) (frontend)  (tests)
                  |         |         |
                WT-A      WT-B      WT-C
                   \        |        /
                    \       |       /
                     v      v      v
                   deterministic gate
               (compileall + unittests + smoke)
                            |
                            v
                          agy6
                 (repair / quality review)
                            |
                            v
                          agy7
                  (independent audit)
```

### Components
- **Control Plane**: The existing Herdr workspace (`wK`) and pane (`wK:p1`) from which the orchestrator runs.
- **Factory Engine (`tools/factory.py`)**: Python 3 stdlib driver managing task lifecycles, worktrees, Herdr panes, merges, deterministic gates, and resume.
- **Worker Registry (`factory.json`)**: Declarative definitions for each worker identity and future adapter templates.
- **Plan Schema**: Declarative workflow JSON declaring waves, tasks, worker identities, allowed paths, context files, and post-wave validation commands.
- **Worktrees (`.agy-factory/worktrees/`)**: Isolated Git worktrees where workers modify code without touching the main working tree.
- **Audit & Evidence (`.agy-factory/runs/`, `.agy-factory/evidence/`)**: Full audit trails of prompts, outputs, diffs, tokens, and test logs.

---

## 3. Ownership & Isolation Invariant

The factory strictly enforces the ownership boundary:
```python
if resource_id not in owned_resources:
    mutation_forbidden()
```
- Every Herdr workspace or pane created by the factory is recorded immediately in `.agy-factory/state/owned-resources.json`.
- Pre-existing Herdr resources (other projects, active agents) are read-only baseline references and are **never** mutated, stopped, or cleaned up.
- The control plane itself is registered as protected and excluded from cleanup.

---

## 4. Worker Registry & Readiness

| Worker Identity | Script / Binary | Profile Home | Capabilities | Default Role |
| :--- | :--- | :--- | :--- | :--- |
| `agy` | `/root/.local/bin/agy` | `/root/.agy_home` | general, orchestration | Primary CLI (control plane) |
| `agy2` | `/root/.local/bin/agy2` | `/root/.agy2_home` | planning, specification | Wave 0: Specification |
| `agy3` | `/root/.local/bin/agy3` | `/root/.agy3_home` | implementation, backend, database | Wave 1: Backend / SQLite |
| `agy4` | `/root/.local/bin/agy4` | `/root/.agy4_home` | implementation, frontend | Wave 1: Frontend (HTML/CSS/JS) |
| `agy5` | `/root/.local/bin/agy5` | `/root/.agy5_home` | implementation, testing | Wave 1: Test Suite & Smoke Harness |
| `agy6` | `/root/.local/bin/agy6` | `/root/.agy6_home` | review, repair, integration | Wave 2: Repair / Quality Integration |
| `agy7` | `/root/.local/bin/agy7` | `/root/.agy7_home` | review, audit, security | Wave 3: Independent Final Audit |

### Future Worker Family Readiness
The registry in `factory.json` includes adapter stubs for `codex`, `droid`, and `freebuff`. Adding a new worker family requires only filling in the invocation command and result parsing format without changing the factory orchestration core.

---

## 5. Usage & Operations

### Preflight Verification
Inspects the environment, checks worker command availability, snapshots existing Herdr resources, and logs external config hashes:
```bash
python3 tools/factory.py preflight
```

### Validating a Plan
Validates top-level fields, duplicate task IDs, unknown workers, missing dependencies, cycles, and unsafe path escapes before execution:
```bash
python3 tools/factory.py validate-plan plans/minilinks.json
```

### Running a Plan
Executes the declarative orchestration plan end-to-end:
```bash
python3 tools/factory.py run plans/minilinks.json
```

### Resuming an Interrupted Run
Resumes an interrupted or partial factory run, skipping already integrated/committed tasks:
```bash
python3 tools/factory.py resume run-<timestamp>
```

### Checking Status
Inspects active and past runs, task states, and owned resources:
```bash
python3 tools/factory.py status
```

### Safe Cleanup
Removes only project-owned Herdr workspaces, Git worktrees, and ephemeral scratch files:
```bash
python3 tools/factory.py cleanup
```

### Running Factory Self-Tests
Runs the deterministic unit test suite verifying plan validation, path matching, resource safety, and resume decisions:
```bash
python3 -m unittest discover -s factory_tests -v
```

---

## 6. Built Applications

### 1. MiniBoard (`./`)
Local single-user Kanban task board built in the PoC run:
- **Backend**: Python 3 `http.server` with `sqlite3` persistence (`app/server.py`, `app/database.py`).
- **Frontend**: Vanilla responsive HTML/CSS/JS with TODO, DOING, and DONE columns (`web/`).
- **Tests**: 34 passing unit tests (`tests/test_api.py`, `tests/test_persistence.py`) and 12-step standalone smoke verification (`scripts/smoke_test.py`).
- **Verification**: `python3 -m unittest discover -s tests -v` (34/34 passing), `python3 scripts/smoke_test.py` (12/12 steps passing).

### 2. MiniLinks (`examples/minilinks/`)
Local single-user bookmark manager built completely through the reusable factory:
- **Specification**: `examples/minilinks/SPEC.md` authored by `agy2`.
- **Backend**: Python 3 `http.server` with `sqlite3` bookmark store, `/health`, search filtering `?q=`, and path traversal protection (`examples/minilinks/app/`).
- **Frontend**: Vanilla responsive HTML/CSS/JS bookmark manager with debounced search, modal dialogs, and toast notifications (`examples/minilinks/web/`).
- **Tests**: 21 passing unit tests (`examples/minilinks/tests/`) and 12-step standalone smoke verification (`examples/minilinks/scripts/smoke_test.py`).
- **Audit**: Independent audit by `agy7` produced `APPROVED` status with 0 critical, 0 major, and 0 minor findings.
- **Verification**: `python3 -m unittest discover -s examples/minilinks/tests -v` (21/21 passing), `python3 examples/minilinks/scripts/smoke_test.py` (12/12 steps passing).
