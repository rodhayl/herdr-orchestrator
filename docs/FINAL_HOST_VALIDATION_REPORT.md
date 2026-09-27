# Final Host-Side Validation Report — AGY-Herdr Software Factory v9

**Date:** 2026-09-27  
**Factory Version:** v9.0.0  
**Repository:** `rodhayl/herdr-orchestrator` (`agy-herdr-factory-poc`)  
**Validation Mode:** Exhaustive, deterministic, 100% provider-free (0 model/LLM calls, 0 quota spent)

---

## 1. Starting State Verification

- **Target Starting Commit:** `ccf280bf136f9a4c6b917f1e68ce518c4676a134` (`fix(v9): close UI gaps and harden fail-closed recovery`)
- **Initial Verification:**
  - Branch: `main`
  - Diverged local commit `a3458c0` safely archived to branch `backup/local-audit-pre-ui` before aligning workspace.
  - Working tree initialized clean against `ccf280bf136f9a4c6b917f1e68ce518c4676a134`.
  - All subsequent fixes committed on `main`.

---

## 2. Architectural & Contract Alignment

Reviewed all core contracts and documentation:
- `README.md`, `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/FACTORY_UI.md`, `UPDATE_PACKAGE.md`, `UPDATE_HISTORY.md`
- `tools/factory_contracts.py`, `tools/factory_ui.py`, `ui/vendor.lock.json`

**Invariants Confirmed:**
- **Factory Authority:** Factory engine and `.agy-factory/` filesystem state remain strictly authoritative.
- **UI Facade:** The local HTTP UI is strictly a read-only / control projection facade. No secondary database, state engine, or background scheduler exists.
- **Kanban Projections:** Kanban board columns are pure derived projections of canonical task lifecycle states.
- **Fail-Closed `real_only`:** Inability to invoke a real provider fails closed immediately.
- **Provider-Free Discipline:** All validation runs are fully deterministic, using fake/test harnesses.

---

## 3. Python Syntax and Module Imports

### Bytecode Compilation (`python3 -m compileall`)
- Command: `python3 -m compileall tools scripts factory_tests app tests examples`
- **Result:** PASS. Zero syntax errors or compilation warnings across all active source trees.

### Direct Import Verification
```python
import tools.factory_contracts
import tools.context
import tools.reasoning
import tools.factory
import tools.factory_ui
print("imports PASS")
```
- **Result:** PASS. All primary modules load cleanly with zero runtime initialization defects.

---

## 4. Factory Test Suite Execution

Ran full deterministic test discovery across three distinct seeds:
- `PYTHONHASHSEED=0 python3 -m unittest discover -s factory_tests -v`
- `PYTHONHASHSEED=1 python3 -m unittest discover -s factory_tests -v`
- `PYTHONHASHSEED=42 python3 -m unittest discover -s factory_tests -v`

### Defects Identified & Resolved
1. **`factory_tests/test_v7_plan_review_and_revision.py`:**
   - *Issue:* Test relied on `PLAN_REVIEW_TEST_VERDICT=REJECTED`, which is strictly ignored in hardened v9 unless `FACTORY_TEST_HARNESS=1`.
   - *Fix:* Added explicit `FACTORY_TEST_HARNESS=1` setup and teardown in the test case.
2. **`factory_tests/test_v9_core_hardening.py`:**
   - *Issue:* `GoalController` initialization modified global context `RUNS_DIR` without cleaning up, causing subsequent tests in the suite to inherit a temporary directory path.
   - *Fix:* Captured `_CURRENT_CONTEXT` in `setUp()` and cleanly restored it in `tearDown()`.

### Results
- Seed 0: Ran 303 tests — **303 OK** (0 failures, 0 errors, 4 skipped as designed).
- Seed 1: Ran 303 tests — **303 OK** (0 failures, 0 errors, 4 skipped as designed).
- Seed 42: Ran 303 tests — **303 OK** (0 failures, 0 errors, 4 skipped as designed).

Focus suites verified:
- `test_factory_contracts.py`
- `test_factory_ui.py`
- `test_vendor_ui.py`
- `test_v9_core_hardening.py`
- `test_v9_core_source_contracts.py`
- `test_v9_maintenance_scripts.py`

---

## 5. Verification Suite (`verify.sh`)

Executed the official multi-suite verification across all three seeds:
- `PYTHONHASHSEED=0 ./scripts/verify.sh`
- `PYTHONHASHSEED=1 ./scripts/verify.sh`
- `PYTHONHASHSEED=42 ./scripts/verify.sh`

### Suites Covered & Status
1. **Factory Core Tests:** PASS (all unit/integration tests).
2. **MiniBoard Verification:** PASS (`verify.sh` in MiniBoard project context).
3. **MiniLinks Verification:** PASS (`verify.sh` in MiniLinks example context).
4. **Smoke Tests:** PASS (deterministic task lifecycle run).
5. **v9 Deterministic Tests:** PASS (all v9 hardening and contract suites).

**Result:** PASS on Seed 0, Seed 1, and Seed 42.

---

## 6. Portable Smoke Verification (`portable-smoke.sh`)

- Command: `./scripts/portable-smoke.sh`
- **Sandbox Environment:** Fresh temporary directory (`/tmp/agy-portable-*`) without provider credentials.
- **Steps Verified:**
  1. Clean checkout initialization.
  2. Environment and dependency isolation check.
  3. Preflight and contract checks.
  4. Deterministic core tests.
  5. MiniBoard integration check.
  6. MiniLinks integration check.
- **Result:** All 6 steps passed. Zero skips introduced; zero external model credentials requested.

---

## 7. Doctor and Update Checks

### `scripts/doctor.sh`
- *Defect Found:* String formatting error when printing herdr-board compatibility (`{board_status}` unformatted).
- *Fix Applied:* Corrected string interpolation so `herdr-board Compatibility: compatible (certified lock)` displays properly.
- Output Confirmed:
  - Factory Version: `9.0.0`
  - Toolchain lock: clean, valid SHA-256 digests.
  - Policy hashes: Reasoning policy and Context policy verified against lockfile.
  - Freebuff status: Inactive (provider-free safe).
  - herdr-board compatibility: `v0.18.0` recognized as compatible with Herdr `0.9.1` / protocol `22`.

### `scripts/update-package.sh --check`
- Executed read-only check mode.
- Verified that package manifests match toolchain lock and no uncommitted mutations occur.

---

## 8. Factory UI Vendor Asset Validation

Verified zero-Node vendor management using `scripts/vendor_ui.py`:
1. Clean sync:
   ```bash
   rm -rf .tools/ui/vendor
   python3 scripts/vendor_ui.py sync
   python3 scripts/vendor_ui.py check
   ```
2. Offline check:
   ```bash
   FACTORY_UI_OFFLINE=1 python3 scripts/vendor_ui.py check
   ```
3. Tamper detection:
   - Modified an asset locally -> `scripts/vendor_ui.py check` failed with SRI mismatch as expected.
   - Re-synced -> verification returned `PASS`.

**Assets Validated:**
- `@awesome.me/webawesome` (v3.14.0): npm SRI hashes verified for CSS and JS distribution bundles.
- `@alpinejs/csp` (v3.17.4): verified against `ui/vendor.lock.json`.
- State file `.tools/ui/vendor/vendor-state.json` cleanly generated and ignored by git.

---

## 9. Real HTTP UI Smoke (Deterministic, No Model Calls)

Launched UI server on loopback using a deterministic fixture project:
- Command: `FACTORY_UI_OFFLINE=1 ./scripts/ui.sh --project-root <fixture> --port 8765`
- Verified HTTP endpoints:
  - `GET /health` -> `200 OK` (`{"status": "ok"}`)
  - `GET /api/v1/snapshot` -> `200 OK` (Valid snapshot JSON)
  - `GET /api/v1/system` -> `200 OK` (System, profile, policy state)
- Verified Browser Views:
  - **Overview:** System status, project root, active run stats.
  - **Board:** Kanban columns (Backlog, Ready, Running, Review, Done, Failed).
  - **Goals / Runs:** Historical runs, execution states, attempt metadata.
  - **System:** Policies, harness profiles, effort baseline, toolchain lock status.
- Verified Task Drawer Tabs:
  - Overview, Requirements, Context, Validation, Git, Attempts, Events.
  - Verified context metrics, anchor information, validation evidence, commit/diff summaries, and audit logs.
- Absolute Constraint: Zero model invocations; Resume on real goals was not triggered.

---

## 10. HTTP Security Hardening

Validated network security controls against the UI server:
- **Loopback Enforcement:** Server strictly binds to `127.0.0.1` / `::1`. Public binds (e.g. `0.0.0.0`) are refused.
- **Host Header Validation:**
  - `Host: 127.0.0.1:8765` -> `200 OK`.
  - Spoofed/foreign `Host: malicious.com` -> `400 Bad Request` / Rejected.
- **Origin Validation:**
  - Same-origin POST requests accepted.
  - Foreign `Origin: http://evil.com` rejected with `403 Forbidden`.
- **CORS:** No permissive `Access-Control-Allow-Origin: *` headers present.
- **Directory Traversal:**
  - Requests containing `/../../etc/passwd` or `/static/../...` rejected safely with `404` or `400`.
- **Security Headers:**
  - `Content-Security-Policy`: Strict CSP enforcing Alpine CSP build; does **not** permit `unsafe-eval`.
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`

---

## 11. UI ETag & Polling Validation

- Performed `GET /api/v1/snapshot` and captured `ETag`.
- Re-queried with `If-None-Match: <ETag>`.
- Verified response: `304 Not Modified`.
- Verified that ETag computation is derived deterministically from file content/hash state and not per-request timestamps.

---

## 12. Canonical State Contract

Inspected and tested `tools/factory_contracts.py` vs UI projections:
- Proved that `ui_display_state is display_state` (exact object identity).
- Authoritative state mappings verified:
  - `PENDING` -> `BACKLOG`
  - `READY` -> `READY`
  - `RUNNING` -> `RUNNING`
  - `VALIDATING` -> `RUNNING`
  - `COMMITTING` -> `RUNNING`
  - `INTEGRATING` -> `RUNNING`
  - `CONFLICTED` -> `REVIEW`
  - `COMPLETED` -> `DONE`
  - `FAILED` -> `FAILED`
- Zero duplicate or conflicting state maps exist in the codebase.

---

## 13. `real_only` Fail-Closed Hardening

Provider-free tests proved:
- **Missing Goal:** `GoalController(goal_id="nonexistent")` fails closed with expected error.
- **Persistence:** Goals initialized with `real_only=True` retain `real_only=True` across save/resume cycles; never downgrades to mock.
- **First Execution vs Resume:**
  - First execution strictly calls `execute_plan(resume_mode=False)`.
  - Resumed runs use `resume_mode=True`.
- **Test Override Isolation:**
  - `PLAN_REVIEW_TEST_VERDICT` and `AUDIT_TEST_VERDICT` are strictly ignored unless `FACTORY_TEST_HARNESS=1`.
- **Live Semantic Roles:**
  - When `real_only=True` and mock providers attempt execution outside test harness, GoalSpec planner, plan compiler, plan reviewer, and final auditor fail closed raising `RealProviderRequiredError`.
  - No deterministic fallback, no auto-approval, no auto-acceptance.

---

## 14. Git Cleanliness Guard

- Verified that `.agy-factory/` runtime output files are properly excluded by dirty-project preflight checks.
- Verified that modifications to tracked or source paths (e.g. `src/foo.agy-factory.py` or `docs/.agy-factory-notes.md`) properly flag the working tree as dirty.
- Boundary rename cases verified to prevent untracked leakage.

---

## 15. Validation Argument Parsing

- Verified that string validation commands (e.g. `python3 -c "import sys; sys.exit(0)"`) are tokenized safely using `shlex.split`.
- Subprocess execution explicitly uses `shell=False`.
- Verified immunity against shell metacharacter injection (`|`, `;`, `&&`, `` ` ``).

---

## 16. Static Dead-Code & Cleanup Review

- Audited active codebase under `tools/`, `scripts/`, `app/`, `factory_tests/`.
- Zero unused imports or dead assignments found in active modules.
- Preserved historical evidence under `docs/archive/` and `certification/` intact.

---

## 17. Documentation Consistency

- Audited non-archived markdown files (`README.md`, `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/FACTORY_UI.md`, etc.).
- Confirmed clear distinction between Factory version (`v9.0.0`), configuration versions, schema versions, and certified toolchain locks.
- Confirmed zero stale claims regarding external compatibility blocks.

---

## 18. Zero Provider Verification

- **Real Provider Calls:** 0
- **Model Invocations:** 0
- **Quota Consumed:** 0
- **Harness Mode:** Deterministic mocks and test harness only.

---

## 19. Execution Discipline & Documentation Note

Updated `AGENTS.md` to document strict test execution discipline:
```markdown
## Test and execution discipline

- Do not poll or query status repeatedly while background test suites or commands are executing.
- Always wait for tests and processes to finish completely before inspecting results or proceeding.
```

---

## Summary of Commits

1. `b212e85ef2a45ba8d4105bda500aa57a345c494f` — `fix(v9): close final provider-free validation defects`
   - Fixed `scripts/doctor.sh` string interpolation.
   - Fixed `factory_tests/test_v7_plan_review_and_revision.py` test harness setup.
   - Fixed `factory_tests/test_v9_core_hardening.py` context leak.
   - Added test execution discipline note to `AGENTS.md`.
2. Follow-up commit recording this final host-side validation report.
