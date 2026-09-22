# AGY-Herdr Software Factory Proof-of-Concept

A proof-of-concept autonomous software factory demonstrating that an arbitrary brain/orchestrator can delegate the end-to-end specification, parallel implementation, deterministic verification, and independent audit of a complete application across multiple isolated worker identities through Herdr.

---

## 1. What This PoC Proves

1. **Orchestrator Independence**: Any brain (AGY, Codex, Claude, Droid, human) can orchestrate development by issuing declarative plan JSONs and executing a standard library driver.
2. **Infrastructure Reusability without Disruption**: The user's pre-existing Herdr server, sessions, and workspaces act as the execution substrate without creating separate sessions or mutating existing panes.
3. **Multi-Worker Identity Delegation**: Distinct worker identities (`agy`, `agy2`, ..., `agy7`) with separate private authentication profiles are dispatched to specialized roles.
4. **True Concurrency**: Multiple workers operate in parallel within isolated Git worktrees and Herdr workspaces with overlapping timestamps.
5. **Deterministic Integration**: Code quality and correctness are gated strictly by standard library compilation and test suites, not LLM opinion.
6. **Zero Host Pollution**: Strict standard library Python implementation—no `pip` installs outside local `.venv`, no `sudo`, and zero modification to host configuration.

---

## 2. Architecture

```
                  arbitrary orchestrator
                            |
                            v
                        plan JSON
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
               (compileall + unittests)
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
- **Factory Engine (`tools/factory.py`)**: Python 3 stdlib driver managing task lifecycles, worktrees, Herdr panes, merges, and gates.
- **Worker Registry (`factory.json`)**: Declarative definitions for each worker identity and future adapter templates.
- **Worktrees (`.agy-factory/worktrees/`)**: Isolated directories where workers modify code without touching the main working tree.
- **Audit & Evidence (`.agy-factory/runs/`, `.agy-factory/evidence/`)**: Full audit trails of prompts, outputs, diffs, tokens, and test logs.

---

## 3. Ownership & Isolation Model

The factory enforces a strict safety invariant:
```python
if resource_id not in owned_resources:
    mutation_forbidden()
```
- Every Herdr workspace or pane created by the factory is recorded immediately in `.agy-factory/state/owned-resources.json`.
- Pre-existing Herdr resources (other projects, active agents) are read-only baseline references and are **never** mutated, stopped, or cleaned up.
- The control plane itself is registered as protected and excluded from cleanup.

---

## 4. Worker Registry

| Worker Identity | Script / Binary | Profile Home | Role |
| :--- | :--- | :--- | :--- |
| `agy` | `/root/.local/bin/agy` | `/root/.agy_home` | Primary CLI (reserved) |
| `agy2` | `/root/.local/bin/agy2` | `/root/.agy2_home` | Wave 0: Specification |
| `agy3` | `/root/.local/bin/agy3` | `/root/.agy3_home` | Wave 1: Backend / SQLite |
| `agy4` | `/root/.local/bin/agy4` | `/root/.agy4_home` | Wave 1: Frontend (HTML/CSS/JS) |
| `agy5` | `/root/.local/bin/agy5` | `/root/.agy5_home` | Wave 1: Test Suite & Smoke Harness |
| `agy6` | `/root/.local/bin/agy6` | `/root/.agy6_home` | Wave 2: Repair / Quality Integration |
| `agy7` | `/root/.local/bin/agy7` | `/root/.agy7_home` | Wave 3: Independent Final Audit |

### Future Worker Adapters
Adding non-AGY workers (e.g. Codex, Droid, Freebuff) requires defining an adapter block in `factory.json` with its binary, execution flags, and JSON result parser without modifying the orchestrator.

---

## 5. Usage & Operations

### Preflight Verification
Inspects the environment, checks worker command availability, snapshots existing Herdr resources, and logs external config hashes:
```bash
python3 tools/factory.py preflight
```

### Running the Factory Plan
Executes the declarative orchestration plan end-to-end:
```bash
python3 tools/factory.py run plans/demo.json
```

### Checking Status
Inspects the active or most recent run, task states, and owned resources:
```bash
python3 tools/factory.py status
```

### Safe Cleanup
Removes only project-owned Herdr workspaces, Git worktrees, and ephemeral scratch files:
```bash
python3 tools/factory.py cleanup
```

---

## 6. Observing Workers in Herdr

While `python3 tools/factory.py run plans/demo.json` is executing:
1. Open or switch to your Herdr interface (`herdr` or browser UI).
2. During Wave 1, notice three new workspaces appear: `task-wave1_backend`, `task-wave1_frontend`, `task-wave1_tests`.
3. In each workspace, the respective worker (`agy3`, `agy4`, `agy5`) executes concurrently inside its own pane and dedicated Git worktree.
4. Once completed, the branches are merged into `main`, verified via deterministic test suites, and audited by `agy7`.

---

## 7. MiniBoard Application

The demo application created by the factory is **MiniBoard**, a lightweight, zero-dependency task board:
- **Backend**: Python 3 `http.server` with `sqlite3` persistence (`app/server.py`).
- **Frontend**: Vanilla responsive HTML/CSS/JS with TODO, DOING, and DONE columns (`web/`).
- **API**:
  - `GET /health`
  - `GET /api/tasks`
  - `POST /api/tasks`
  - `PATCH /api/tasks/<id>`
  - `DELETE /api/tasks/<id>`
- **Testing**: `tests/test_api.py`, `tests/test_persistence.py`, and `scripts/smoke_test.py`.
