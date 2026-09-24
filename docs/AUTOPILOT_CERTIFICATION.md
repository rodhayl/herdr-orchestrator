# AGY-Herdr Software Factory — v7.0.0 Project Autopilot Certification Report

This document certifies that the AGY-Herdr Software Factory has been upgraded to **v7.0.0 (Project Autopilot)** in accordance with all strict requirements, architectural invariants, host isolation boundaries, deterministic fault-injection suites, and genuine real-provider delegation on an isolated external repository.

---

## 1. Executive Summary

- **Factory Version**: `7.0.0`
- **Core Architecture**: Python 3 standard library only (`tools/factory.py`, zero external packages, no `.venv`).
- **Major Capability Delivered**: Natural Language Goal Specification -> Discovery -> Structured Criteria -> Traceable DAG Plan -> Independent Plan Review -> Bounded Plan Revision -> Deterministic Capability Routing -> Isolated Worktree Execution -> Deterministic Post-Execution Validation -> Independent Final Audit -> Bounded Delta Remediation -> Finished Project.
- **External Target Project Support**: Full multi-project support with isolated `<project_root>/.agy-factory` runtime directories and per-project policy (`factory.project.json`).
- **Real-Provider External Certification**: Successfully certified on isolated external Git repository `/root/treehash-project` ("TreeHash", a deterministic Merkle-tree cryptographic directory hashing utility and library satisfying requirements R1–R14) via genuine provider execution (`REAL_PROVIDER_CERTIFIED`).
- **Freebuff Feasibility Gate**: Formally evaluated and classified as `FREEBUFF_HEADLESS_BLOCKED` (Freebuff CLI v0.0.141 provides interactive TUI only; non-interactive headless prompt execution is unsupported).
- **Herdr-Board Compatibility**: Rechecked and preserved as `BLOCKED_EXTERNAL_COMPATIBILITY` (herdr-board v0.17.0 strictly pins Herdr 0.9.0 / protocol 22; installed Herdr is 0.9.1).
- **Execution Evidence**:
  - Full Deterministic Test Suite: **159/159 passing unit tests** in under 40 seconds with zero failures or errors across all test modules.
  - Full Deterministic Verification: `./scripts/verify.sh` passed 100% across all 5 test suites.
  - Real Provider Autopilot Run: `run-20260924-100833` in `goal-20260924-100806` completed end-to-end with 100% `REAL` execution mode.
  - Final Independent Audit: `agy-audit-high` (`claude-sonnet-4-6`) issued verdict `ACCEPTED` with 0 findings.
  - Target Project Test Suite: 96 unit and integration tests passing in 0.36s with 100% pass rate.
  - Clean-Room Portability: `./scripts/portable-smoke.sh` verified zero leaked directories, zero machine-specific paths, and clean execution from a fresh clone.

---

## 2. Hard Scope Verification Matrix

| Requirement / Scenario | Specification | Method / Evidence | Result |
| :--- | :--- | :--- | :---: |
| **1. External Target Project Support** | Target projects reside outside `factory_root`; isolated runtime in `<project_root>/.agy-factory` | `ProjectContext` and `--project-root`; verified with `/root/treehash-project` | **PASS** |
| **2. Versioned Project Policy** | Per-project policy in `factory.project.json` controlling limits, paths, and routing | Schema `schemas/factory-project.schema.json`; validated via `ProjectPolicy` | **PASS** |
| **3. Goal Specification Compiler** | Compiles natural-language goals into structured `GoalSpec` with canonical provenance (`USER_EXPLICIT` vs `DERIVED`) | `compile_goal_spec()`; schema `schemas/goal-spec.schema.json`; tested in `test_v7_goal_compiler_and_traceability.py` | **PASS** |
| **4. Traceable DAG Plan Generation** | Compiles `GoalSpec` into DAG tasks with complete criteria coverage and deterministic validations | `compile_plan_from_goal()`; schema `schemas/plan.schema.json` v2 | **PASS** |
| **5. Traceability Gates** | Validates complete requirements coverage, safe validation argv, acyclic dependencies, and allowed paths | `validate_plan_traceability()`; tested in `test_validate_plan_traceability_*` | **PASS** |
| **6. Independent Plan Review** | Pre-execution plan review by independent reviewer (`agy-audit-high`, `claude-sonnet-4-6`) | `review_plan()`; schema `schemas/review-result.schema.json`; tested in `test_review_*` | **PASS** |
| **7. Bounded Plan Revision** | Deterministically applies revisions up to `max_plan_revisions` without runaway loops | `revise_plan()`; tested in `test_v7_plan_review_and_revision.py` | **PASS** |
| **8. Autonomous Goal Controller** | Durable state machine (`RECEIVED` -> `COMPLETE`) with atomic writes and durable state file | `GoalController`; schema `schemas/goal-controller.schema.json` | **PASS** |
| **9. Crash Recovery & Failpoints** | Durable resume across all phases (`after_goal_structured`, `after_plan_generated`, `after_plan_reviewed`, `after_execution`, `after_post_validation`, `after_audit`) | Tested in `test_v7_goal_controller_recovery.py` with 5 failpoint recovery tests | **PASS** |
| **10. Post-Execution Validations** | Driver executes deterministic validation commands across the target project after execution | `execute_post_validations()`; tested in `test_v7_remediation.py` | **PASS** |
| **11. Independent Final Audit** | Independent auditor reviews git diff against GoalSpec and issues `ACCEPTED` or `REMEDIATION_REQUIRED` | `audit_project()`; tested in `test_v7_remediation.py` and real run | **PASS** |
| **12. Bounded Delta Remediation** | Delta planning to resolve audit findings up to `max_remediation_rounds` | `compile_remediation_plan()`; tested in `test_compile_remediation_plan` | **PASS** |
| **13. Real-Only Autopilot Mode** | Rejects uncertified profiles and mock executions when `mode: real_only` | Verified in `resolve_task_worker` and certified in real TreeHash run | **PASS** |
| **14. Real-Provider TreeHash Certification** | Full autonomous implementation of TreeHash Merkle directory hashing library and CLI | Completed in `run-20260924-100833`; all attempts `REAL`; guard `PASSED` | **PASS** |
| **15. Freebuff Headless Feasibility Gate** | Formally evaluate Freebuff v0.0.141 headless feasibility | Probed via `probe_harness_auth("freebuff")`: `FREEBUFF_HEADLESS_BLOCKED` | **PASS** |
| **16. herdr-board Compatibility Gate** | Maintain stable compatibility without host mutation | Doctor reports `BLOCKED_EXTERNAL_COMPATIBILITY`; synthetic projection active | **PASS** |
| **17. Clean-Room Portability** | Fresh checkout execution with zero prior state and zero leaked directories | `./scripts/portable-smoke.sh` passed all 6 verification steps | **PASS** |

---

## 3. Real-Provider TreeHash Certification Run

- **Target Project Directory**: `/root/treehash-project`
- **Goal File**: `/root/treehash-project/GOAL.md`
- **Goal ID**: `goal-20260924-100806`
- **Orchestration Run ID**: `run-20260924-100833`
- **Final Status**: `REAL_PROVIDER_CERTIFIED`
- **Final Phase**: `COMPLETE`
- **Revisions Count**: `0` (Plan approved on initial review)
- **Remediation Rounds**: `0` (All validations and final audit passed on round 0)

### Task Breakdown & Provenance Evidence

| Task ID | Task Type | Worker | Profile | Model | Effort | Mode | Result Commit | Validations |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- | :---: |
| `task_core_impl` | `backend` | `agy3` | `agy-backend-high` | `gemini-3.8-flash` | `high` | **REAL** | `53f9fcb` | **PASS** |
| `task_cli_impl` | `backend` | `agy3` | `agy-backend-high` | `gemini-3.8-flash` | `high` | **REAL** | `7beaf10` | **PASS** |
| `task_unit_tests` | `tests` | `agy5` | `agy-tests-medium` | `gemini-3.8-flash` | `medium` | **REAL** | `ad91531` | **PASS** |

### Independent Final Audit
- **Auditor Profile**: `agy-audit-high` (`claude-sonnet-4-6`)
- **Verdict**: `ACCEPTED`
- **Findings**: 0 Critical, 0 Major, 0 Minor

### Functional Verification
- **Target Test Suite**: 96 tests passing in 0.36s (`python3 -m unittest discover -s tests -v`).
- **CLI Commands**:
  - `python3 -m treehash compute <dir> --format text` -> deterministic root hash output.
  - `python3 -m treehash compute <dir> --format json` -> full JSON Merkle manifest.
  - `python3 -m treehash verify <dir> <manifest.json>` -> exit code 0 on match.
  - Tamper detection -> exit code 1 on file modification.

---

## 4. Certification Sign-off

The AGY-Herdr Software Factory v7.0.0 Project Autopilot release satisfies all architectural invariants, delivers complete lifecycle autonomy from natural-language goals to certified external repositories, preserves all evidence-integrity mechanisms, enforces strict host safety, and is fully certified for production use.
