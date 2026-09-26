# Package Update & Compatibility History

Append-only historical ledger tracking toolchain inspections, compatibility audits, version transitions, and certification decisions for the AGY-Herdr Software Factory.

---

## [2026-09-23T07:52:00Z] Initial v4.0.0 Toolchain Audit & Certification Baseline

### 1. Context & Trigger
- **Trigger**: Mandatory Phase 0 package update gate for v4.0.0 upgrade.
- **Operator**: Antigravity Orchestrator (Gemini 3.8 Flash High).
- **Previous Stack (v3.0.0)**:
  - Factory Engine: `3.0.0`
  - Herdr CLI: `0.9.1` (protocol 22)
  - AGY CLI: `1.2.9` (`gemini-3.8-flash-high`)
  - Python: `3.12.3` (stdlib only)
  - Git: `2.43.0`
  - Herdr-Board: Not integrated
  - Droid: Not integrated

### 2. Discovered Installed Stack
- **Herdr CLI**: `0.9.1`
- **Herdr Socket Protocol**: `22` (API schema hash: `226d4ecbd128d2e6bc84e4c8ddcec21ba9c7e51a0aafffcf087111ead3f1fa9a`)
- **AGY CLI**: `1.2.9` (verified working, authenticated, model: `gemini-3.8-flash-high`)
- **Droid CLI**: `0.224.1` (installed at `/root/.local/bin/droid`)
- **herdr-board**: Not installed
- **Rustc / Cargo**: Not installed on host (`command not found`)
- **Python**: `3.12.3`
- **Git**: `2.43.0`
- **OS**: Linux x86_64 (kernel `6.8.0-139-generic`)

### 3. Upstream Compatibility Analysis
- **herdr-board upstream**:
  - Latest stable release: `v0.17.0` (commit `b6c9bce7a2307053a3ba039db31eb880c8979230`).
  - Compatibility declaration in `crates/board-herdr/src/lib.rs:28` and `herdr-plugin.toml`:
    `SUPPORTED_HERDR_VERSION = "0.9.0"`, `SUPPORTED_HERDR_PROTOCOL = 22`.
  - Pinned gate check: `crates/board-herdr/src/client.rs:237` strictly rejects any Herdr version other than `0.9.0` (`if pong.version != crate::SUPPORTED_HERDR_VERSION || pong.protocol != crate::SUPPORTED_HERDR_PROTOCOL`).
  - Installed Herdr server version is `0.9.1` (protocol 22).
  - Compatibility Rule evaluation: No stable herdr-board release officially supports Herdr `0.9.1`.
  - In accordance with Section 7 and 8 invariants:
    - **Decision**: Mark board integration `BLOCKED_EXTERNAL_COMPATIBILITY`.
    - Do not downgrade Herdr.
    - Do not patch upstream compatibility gates.
    - Do not use a preview release.
    - Do not pretend compatibility.
    - Implement `HerdrBoardProjector` with offline recovery, synthetic verification, and mapping synchronization.
- **Droid upstream & runtime**:
  - Installed Droid CLI `0.224.1` syntax verified via `droid exec --help`.
  - Authentication check: execution requires `FACTORY_API_KEY` (currently unset in environment).
  - Model catalog: `qwen3.8-max` requires authenticated account catalog retrieval.
  - In accordance with Section 3 and 10 rules:
    - Implement `DroidAdapter` conforming strictly to `WorkerAdapter` boundary.
    - Validate `DroidAdapter` deterministically via unit test harness and controlled fake provider.
    - Document missing `FACTORY_API_KEY` in `doctor.sh` as an authenticated provider prerequisite, preserving structural verification.

### 4. Decisions & Actions Taken
- [x] Initialized `UPDATE_PACKAGE.md` as permanent operational playbook.
- [x] Initialized `AGENTS.md` with package update gate instructions.
- [x] Created `toolchain.lock.json` recording last certified stack and compatibility statuses.
- [x] Created `scripts/update-package.sh` supporting `--check` and `--apply`.
- [x] Recorded `herdr_board` status as `BLOCKED_EXTERNAL_COMPATIBILITY`.
- [x] Recorded `droid` provider status with authentication requirement disclosure.

---

## [2026-09-23T08:09:25Z] v5.0.0 Harness Profile Architecture & Codex Integration

### 1. Context & Trigger
- **Trigger**: Implementation of v5.0.0 execution profile system and CodexAdapter integration.
- **Operator**: Antigravity Orchestrator (Gemini 3.8 Flash High).
- **Previous Stack (v4.0.0)**:
  - Factory Engine: `4.0.0`
  - Registered Adapters: `AgyAdapter`, `DroidAdapter`
  - Routing: Raw worker identity routing

### 2. Discovered Installed Stack
- **Herdr CLI**: `0.9.1` (protocol 22)
- **AGY CLI**: `1.2.9` (authenticated, `gemini-3.8-flash`)
- **Droid CLI**: `0.225.1` (installed, `FACTORY_API_KEY` required for live provider execution)
- **Codex CLI**: `0.155.1` (installed, `OPENAI_API_KEY` required for live provider execution)
- **Claude Code CLI**: `2.1.263` (detected on host, planned for v6)
- **OpenCode CLI**: `1.18.31` (detected on host, planned for v6)
- **herdr-board**: Upstream release `v0.17.0` (retained `BLOCKED_EXTERNAL_COMPATIBILITY`)

### 3. Decisions & Actions Taken
- [x] Upgraded Factory Engine from `4.0.0` to `5.0.0` in `factory.json` and `toolchain.lock.json`.
- [x] Implemented `CodexAdapter` registered in `ADAPTER_REGISTRY`.
- [x] Created `harness_profiles.json` and JSON schema `schemas/harness-profiles.schema.json`.
- [x] Created comprehensive documentation in `HARNESS_PROFILES.md`.
- [x] Refactored Factory deterministic router to route by execution profiles according to capability priority.
- [x] Implemented `route explain` CLI command with `--json` output.
- [x] Updated `herdr-board` projection to project profile, harness, model, and effort metadata onto Kanban cards.
- [x] Updated `scripts/doctor.sh`, `scripts/update-package.sh`, and `scripts/verify-real.sh` to v5.0.0.
- [x] Applied updated `toolchain.lock.json` recording 8 certified profiles, Codex CLI, and detected future harnesses.

---

## [2026-09-23T15:45:00Z] v6.0.0 5-Harness Architecture, Execution Classes, Telemetry & Multi-Model Profiles

### 1. Context & Trigger
- **Trigger**: Mandatory upgrade from Factory v5.0.0 to v6.0.0.
- **Operator**: Antigravity Orchestrator (Gemini 3.8 Flash High).
- **Previous Stack (v5.0.0)**:
  - Factory Engine: `5.0.0`
  - Registered Adapters: `AgyAdapter`, `DroidAdapter`, `CodexAdapter`
  - Execution Profiles: 8 profiles
  - Routing: Capability-based profile preference without explicit task execution classes
  - Telemetry: Basic timing without standardized JSON schema or git churn tracking

### 2. Discovered Installed Stack
- **Herdr CLI**: `0.9.1` (protocol 22, socket snapshot verified)
- **AGY CLI**: `1.2.9` (Gemini 3.8 Flash medium/high; Claude Sonnet 4.6 high)
- **Droid CLI**: `0.225.1` (Qwen 3.8 Max xhigh/medium, real execution and test harness verified)
- **Codex CLI**: `0.155.1` (GPT-5.6 Luna xhigh/high/medium, test harness verified)
- **Claude Code CLI**: `2.1.263` (Claude Sonnet 5 high/medium, test harness verified)
- **OpenCode CLI**: `1.18.31` (Gemini 3.8 Flash high / Mimo v2.6 Flash Free, test harness verified)
- **herdr-board**: Upstream release `v0.17.0` (retained `BLOCKED_EXTERNAL_COMPATIBILITY` due to host Herdr 0.9.1 vs required 0.9.0)
- **Python**: `3.12.3` (CPython stdlib-only)
- **Git**: `2.43.0`

### 3. Decisions & Actions Taken
- [x] Closed unsupported v5 certification claims: honestly distinguished real test-harness verification from live credentials.
- [x] Resolved Herdr-board compatibility: confirmed Herdr 0.9.1 remains incompatible with herdr-board v0.17.0 (`<0.9.0`), retaining `BLOCKED_EXTERNAL_COMPATIBILITY` without downgrading host Herdr.
- [x] Implemented `ClaudeAdapter` with isolated Herdr workspaces, CLI flags (`-p`, `--model claude-sonnet-5`, `--effort`, `--permission-mode acceptEdits`, `--output-format json`, `--json-schema`), timeout management, and test behavior injection.
- [x] Implemented `OpenCodeAdapter` with isolated Herdr workspaces, CLI flags (`run`, `--dir`, `--model`, `--variant`, `--format json`, `--auto`, `--pure`), timeout management, and test behavior injection.
- [x] Expanded `harness_profiles.json` to 19 certified/declared execution profiles across 5 distinct harnesses (AGY, Droid, Codex, Claude, OpenCode) with multi-effort profiles (medium, high, xhigh, free).
- [x] Introduced deterministic `execution_class` layer (`routine`, `standard`, `deep`) derived from task type or plan declaration, routed via `ROUTING_PRIORITY_MATRIX`.
- [x] Standardized execution telemetry adhering to `schemas/execution-metrics.schema.json`, appending to `.agy-factory/evidence/telemetry.jsonl` with lines added/deleted/files changed git churn.
- [x] Added descriptive telemetry CLI `python3 tools/factory.py metrics summarize [--json] [--run <id>] [--profile <id>]` (observation-only, zero learned routing).
- [x] Upgraded MiniLinks application with bookmark `archived` feature (database migration, CRUD, REST API endpoints `POST /archive` & `/restore`, `?archived=true/false/all` query filtering, frontend UI toggle/buttons, unit tests, and smoke test Step 8b).
- [x] Executed 5-harness rehearsal DAG (`plans/minilinks_v6_archive.json`) with overall COMPLETED status. Note: Audit in v6.1 established that backend (Droid) was genuine REAL execution while frontend (Codex), tests (Claude), support (OpenCode), and AGY tasks ran in deterministic test-harness mode.
- [x] Updated `scripts/update-package.sh`, `scripts/doctor.sh`, `toolchain.lock.json`, and `UPDATE_PACKAGE.md` to Factory v6.0.0.

---

## [2026-09-23T22:10:00Z] v6.1.0 Truth Audit & Execution Provenance Closure Baseline

### 1. Context & Trigger
- **Trigger**: Factory v6.1.0 production certification closure audit.
- **Operator**: Antigravity Orchestrator (Gemini 3.8 Flash High).
- **Audit Target**: Rehearsal run `run-20260923-153816` and multi-harness claims in v6.0.0 report.

### 2. Discovered Execution Provenance
- **Rehearsal `run-20260923-153816` Decomposition**:
  - `backend` (`droid-backend-xhigh`): **REAL** (genuine Droid CLI execution; duration 55.4s; session `9e3007a6-617c-4c9b-a8db-822c6b064789`; modified `server.py` with 11 insertions; 54,327 Factory credits consumed).
  - `frontend` (`codex-luna-high`): **MOCK** (duration 249ms; generated by `CodexAdapter._handle_test_behavior`).
  - `tests` (`claude-sonnet5-high`): **MOCK** (duration 286ms; generated by `ClaudeAdapter._handle_test_behavior`).
  - `support` (`opencode-gemini-high`): **MOCK** (duration 328ms; generated by `OpenCodeAdapter._handle_test_behavior`).
  - `spec`, `integration`, `integration_hardening`, `audit` (`agy` profiles): **MOCK** (duration 189-269ms; generated by `AgyAdapter._handle_test_behavior`).
- **Classification Verdict**: Run `run-20260923-153816` is reclassified as **`MOCK` (contains mock execution)**. It provided valid deterministic workflow testing, but does NOT constitute `REAL_MULTI_HARNESS_CERTIFIED`.
- **Evidence Record**: Recorded in `.agy-factory/evidence/v6_reconciliation.json` conforming to `schemas/v6-reconciliation.schema.json`.

---

## [2026-09-23T22:38:00Z] v6.1.0 Production Certification Closure & Verification

### 1. Context & Objectives
- **Trigger**: Factory v6.1.0 Production Certification Closure Goal.
- **Operator**: Antigravity Orchestrator (Gemini 3.8 Flash High).
- **Core Mission**: Close every production-certification gap left by v6.0.0; make it technically impossible to confuse deterministic mock simulation with genuine provider-backed execution; implement fail-closed certification guards; verify read-only harness auth discovery; execute real mixed-harness DAG and independent final audit.

### 2. Verified Implementation & Architectural Guardrails
- **Provenance Model**: Added canonical execution provenance classification (`REAL`, `MOCK`, `TRANSPORT_ONLY`, `UNKNOWN`) to every task attempt record, event, and telemetry entry.
- **Fail-Closed Certification Guard**: Implemented `assert_real_certifiable(manifest)` in `tools/factory.py` (and CLI `factory.py certify guard <run_id>`). Fails closed if `FACTORY_TEST_HARNESS=1`, if `contains_mock_execution=true`, if any attempt mode is `MOCK`, if test fixture or fake shim paths are detected via `verify_binary_identity`, or if raw result hashes / evidence bundles are missing.
- **Harness-Specific Auth Discovery**: Implemented `probe_harness_auth` and `probe_profile_auth` with read-only, secret-safe discovery:
  - `agy`: `provider_credentials` via `agy models` (model `gemini-3.8-flash` available).
  - `droid`: `AUTH_BLOCKED` via `droid doctor` ("no usable credentials found").
  - `codex`: `AUTH_BLOCKED` via `codex login status` ("Not logged in").
  - `claude`: `AUTH_BLOCKED` via `claude auth status --json` (`loggedIn: false`).
  - `opencode`: `api_key_env` via `opencode auth list` (active `OPENROUTER_API_KEY`).
  - Profiles: `opencode-mimo-free` (`openrouter/openrouter/free`) is `REAL_PROVIDER_CERTIFIED`; `opencode-gemini-high` is `PROFILE_UNAVAILABLE` due to OpenRouter workspace guardrails.
- **Secret Redaction**: Implemented recursive `redact_secrets` masking tokens, API keys, and sensitive auth parameters across manifests, execution bundles, invocation arguments, and events.
- **Native CLI Contracts**:
  - `CodexAdapter`: Verified TOML reasoning effort quoting `-c 'model_reasoning_effort="{effort}"'`.
  - `ClaudeAdapter`: Pinned flags `--model`, `--effort`, `--output-format json`, `--json-schema`.
  - `OpenCodeAdapter`: Pinned flags `run`, `--dir`, `--model`, `--variant`, `--format json`, `--auto`, `--pure`.
- **Telemetry Partitioning**: Updated `summarize_execution_metrics` to strictly group and report metrics by `execution_mode` (never combining mock and real metrics into a single rate).

### 3. Genuine Real-Provider Certifications
- **Real Mixed-Harness Rehearsal Run (`run-20260923-222722`)**:
  - Plan: `plans/certification_real_v6_1.json` (`Factory v6.1 Real Mixed-Harness Production Certification DAG`).
  - Execution: Completely executed WITHOUT `FACTORY_TEST_HARNESS`.
  - Tasks:
    - `cert_spec`: Routed to `agy-spec-high` (`agy2`). Executed real `agy` CLI binary (`/root/.local/bin/agy2` v1.2.9). Status `COMPLETED`, mode `REAL`, raw result hash `300cc574...`, integrated in commit `4c45fc2`.
    - `cert_support`: Routed to `opencode-mimo-free` (`opencode`). Executed real `opencode` CLI binary (`/root/.opencode/bin/opencode` v1.18.31, model `openrouter/openrouter/free`, variant `free`). Status `COMPLETED`, mode `REAL`, session `ses_f2f9c6079ffezgy2pBZf66QHsX`, raw result hash `2599c264...`, integrated in commit `70ec18c`.
  - Manifest & Verdict: `contains_mock_execution: false`, `certification_level: REAL_PROVIDER_CERTIFIED`. Validated by `assert_real_certifiable` guard (`PASSED`).
- **Independent Final Audit Run (`run-20260923-223546`)**:
  - Plan: `plans/v6_1_final_audit.json`.
  - Execution: Routed to `agy-audit-high` (`agy7`, model `claude-sonnet-4-6`). Executed genuine `agy` CLI binary in read-only review mode.
  - Verdict: `status: APPROVED`. Comprehensive audit evaluation across backend, frontend, tests, security, and integration.

### 4. Verification & Clean-Room Portability
- **Deterministic Suites**: All 5 test suites (121 unit tests in `factory_tests`, MiniBoard unit tests, MiniBoard smoke test, MiniLinks unit tests, MiniLinks smoke test) passed with 0 failures, 0 errors.
- **Provider Verification**: `./scripts/verify-real.sh` confirmed live AGY and OpenCode execution, and accurate `AUTH_BLOCKED` reporting for Droid, Codex, and Claude.
- **Clean-Room Portability**: `./scripts/portable-smoke.sh` executed all 6 steps in an isolated clean checkout sandbox without leaked directories, machine-specific paths, or prior state.
---

## [2026-09-24T12:00:00Z] v7.0.0 Project Autopilot Full Implementation & Real Certification

### 1. Context & Objectives
- **Trigger**: Factory v7.0.0 Project Autopilot Architecture Upgrade.
- **Operator**: Antigravity Orchestrator (Gemini 3.8 Flash High).
- **Core Mission**: Elevate Factory from manual plan authoring to natural language Goal Specification with full lifecycle autonomy:
  `Goal -> Discovery Packet -> Structured GoalSpec (Explicit vs Derived) -> Traceable Plan v2 DAG -> Independent Plan Review -> Bounded Revision -> Deterministic Routing / Real-Only Execution -> Post-Execution Validation -> Independent Final Audit -> Bounded Delta Remediation -> Finished Project`.
- **Target Project Support**: Enable full external project execution outside `factory_root` with isolated `<project_root>/.agy-factory` runtime directories and versioned per-project policy (`factory.project.json`).

### 2. Verified Implementation & Architectural Capabilities
- **Per-Project Policy & Discovery**:
  - Implemented `ProjectPolicy` and `ProjectContext` binding isolated target directories, dirty git guards, and permission scopes.
  - Implemented `generate_discovery_packet` providing bounded workspace analysis.
  - Created `schemas/factory-project.schema.json`.
- **Goal Specification & Traceability Compiler**:
  - Implemented `compile_goal_spec` with canonical provenance classification (`USER_EXPLICIT` vs `DERIVED`).
  - Implemented `compile_plan_from_goal` compiling full criteria into DAG tasks with deterministic validations.
  - Implemented `validate_plan_traceability` verifying criteria coverage, cycle-free topology, safe command tokens, and task limits.
  - Created `schemas/goal-spec.schema.json` and updated `schemas/plan.schema.json`.
- **Independent Plan Reviewer & Bounded Revision**:
  - Implemented `review_plan` invoking independent reviewer (`agy-audit-high`, `claude-sonnet-4-6`) and `revise_plan` with bounded revision loops up to `max_plan_revisions`.
- **Autonomous Goal Controller**:
  - Implemented `GoalController` with durable state transitions (`RECEIVED` -> `DISCOVERING` -> `STRUCTURING` -> `PLANNING` -> `PLAN_VALIDATING` -> `PLAN_REVIEWING` -> `READY` -> `EXECUTING` -> `POST_VALIDATING` -> `AUDITING` -> `REMEDIATING` -> `COMPLETE`).
  - Atomic state writes, failpoint injection support, and durable restart/resume without duplicate task execution.
  - Created `schemas/goal-controller.schema.json`.
- **Post-Execution Validation & Independent Final Audit**:
  - Deterministic execution of task validations across the repository with stdout/stderr recording.
  - Implemented `audit_project` invoking independent auditor for full implementation critique, coupled with bounded delta remediation planning.
- **Feasibility & Upstream Compatibility Gates**:
  - Evaluated Freebuff CLI v0.0.141: classified as `FREEBUFF_HEADLESS_BLOCKED` (lacks non-interactive headless prompt execution mode; interactive TUI only).
  - Maintained `herdr-board` v0.17.0 gate as `BLOCKED_EXTERNAL_COMPATIBILITY` without host mutation.

### 3. Genuine Real-Provider External Project Certification ("TreeHash")
- **Target Project**: `/root/treehash-project` (completely isolated external Git repository).
- **Goal**: Full implementation of TreeHash Merkle directory hashing library and CLI satisfying 14 requirements (R1–R12 explicit, R13–R14 derived).
- **Execution Run (`run-20260924-100833`)**:
  - Goal ID: `goal-20260924-100806`
  - Final Phase: `COMPLETE`
  - Revisions: 0, Remediation rounds: 0
  - Tasks Executed:
    - `task_core_impl`: Mode `REAL`, worker `agy3`, profile `agy-backend-high` (`gemini-3.8-flash`), commit `53f9fcb`.
    - `task_cli_impl`: Mode `REAL`, worker `agy3`, profile `agy-backend-high` (`gemini-3.8-flash`), commit `7beaf10`.
    - `task_unit_tests`: Mode `REAL`, worker `agy5`, profile `agy-tests-medium` (`gemini-3.8-flash`), commit `ad91531`.
  - Validations: 3/3 passed (100%).
  - Independent Final Audit: `ACCEPTED`.
  - Certification Guard: `REAL_PROVIDER_CERTIFIED: All tasks executed genuine provider-backed processes with verifiable evidence` (`PASSED`).
  - Target Project Test Suite: 96 unit and integration tests passing 100% in 0.36s.
  - Functional Smoke: CLI compute, JSON manifest, verification match (RC 0), and tamper detection (RC 1) all verified.
  - Bundle: Saved to `certification/v7/autopilot-real-certification.json`.

### 4. Verification & Clean-Room Portability
- **Deterministic Test Suites**: 159 tests in `factory_tests` passed with zero failures or errors in under 40s.
- **Portability**: Verified clean-room execution via `./scripts/portable-smoke.sh` and zero host mutation.

---

## [2026-09-25T00:50:00Z] Factory v8.0.0 Context Efficiency & Deep Hardening Certification

### 1. Context & Objectives
- **Trigger**: Factory v8.0.0 Context Efficiency + Deep Hardening Architecture Upgrade.
- **Operator**: Antigravity Orchestrator (Claude Sonnet 4.6 & Gemini 3.8 Flash High).
- **Core Mission**: Drastically optimize context consumption across autonomous workflows while hardening all deterministic invariants:
  - Deliver $\ge 40\%$ reduction in factory-supplied context/prompt bytes.
  - Enforce 100% required anchor recall (`CONTEXT_ANCHOR_MISSING` fail-closed gate).
  - Guarantee zero orphan derived requirements (`OrphanDerivedRequirementError`).
  - Implement bounded immutable semantic handoffs (`HandoffPacket` $\le 4,096$ bytes).
  - Eliminate multi-path string templating with unified, role-specialized `ContextCompiler`.
  - Establish stable prefix architecture for maximal KV-cache reuse.
  - Secure independent code audit verdict `ACCEPTED` with 0 Critical / 0 Major findings.
  - Pass 3-pass deterministic test verification across random seeds (`PYTHONHASHSEED=0, 1, 42`).

### 2. Verified Architectural Capabilities
- **Deterministic ContextCompiler (`tools/context.py`)**:
  - Implemented role-specialized packets: `PlanReviewContextPacket`, `TaskContextPacket`, `AuditContextPacket`.
  - Replaced raw file inlining with scoped file references and boundary-checked excerpts.
  - Implemented boundary-aware anchor recall and secondary exact-substring validation gates.
  - Implemented `DerivedRequirementAuditor` enforcing parent requirement tracing and closed enum categories.
  - Implemented content-hashed secret environment fingerprinting (`get_secret_env_fingerprint`).
  - Added portable `NonReentrantLock` for manifest deadlock prevention.
- **Independent Code Audit (`scripts/run_independent_audit.py`)**:
  - Independent auditor model: `claude-sonnet-4-6`.
  - Final Audit Verdict: **`ACCEPTED`** (0 Critical, 0 Major findings).
  - Complete report recorded in `certification/v8/independent-audit-report.json`.

### 3. Genuine Real-Provider External Project Certification ("TreeHash v8")
- **Target Project**: `/root/treehash-v8-project` (isolated external Git repository).
- **Goal**: Full implementation of TreeHash Merkle directory hashing library and CLI satisfying all 14 requirements.
- **Execution Run (`run-20260924-184518`)**:
  - Goal ID: `goal-20260924-184501`
  - Final Phase: `COMPLETE`
  - Context Metrics:
    - Baseline v7 Workflow Bytes: `51,170 B`
    - Compiled v8 Workflow Bytes: `12,723 B`
    - **Context Reduction**: **`75.1%`** (comfortably exceeding the $\ge 40\%$ target).
    - Required Anchor Recall: **`100.0%`** across all attempts.
  - Certification Bundle: Saved to `certification/v8/autopilot-real-certification.json`.

### 4. Verification & Clean-Room Portability
- **Test Suite**: 225 unit, integration, stress, and security tests passing 100%.
- **3-Pass Deterministic Verification**:
  - `PYTHONHASHSEED=0 ./scripts/verify.sh` -> PASS (225/225 tests, exit code 0).
  - `PYTHONHASHSEED=1 ./scripts/verify.sh` -> PASS (225/225 tests, exit code 0).
  - `PYTHONHASHSEED=42 ./scripts/verify.sh` -> PASS (225/225 tests, exit code 0).
- **Zero Host Mutation**: Workspaces 1–13 protected; zero external pip packages; standard-library Python only.

## [2026-09-26] v9 Safety & Evidence Closeout (No Provider Calls)

- **Scope**: Local/static closeout only. No AGY, Droid, Codex, Claude, OpenCode, or other model/provider calls were requested or required.
- **Reasoning Escalation Safety**: Reclassified `PATH_VALIDATION_FAILED` from an escalation-eligible quality failure to a non-escalatable guardrail/scope violation in both `tools/reasoning.py` and `reasoning_policy.json`. Higher reasoning effort must never be used as an automatic response to writing outside allowed scope.
- **Regression Coverage**: Added deterministic tests asserting that path-validation failures are absent from eligible categories, present in non-eligible categories, and produce `FAILURE_NOT_ELIGIBLE` with no effort increase.
- **Calibration Scope**: Clarified that v9 effort calibration is an initial evidence-backed production default with bounded escalation, not a universal optimum across repositories, workloads, providers, or future model versions.
- **Efficiency Evidence Correction**: The recorded TreeHash comparison demonstrates lower worker reasoning tokens (-59.57%), lower worker output tokens (-31.87%), and lower wall-clock duration (-20.10%), while worker input tokens increased (+27.20%). The v8 baseline does not expose comparable cached-input telemetry, and the v8/v9 target suites differ in size (87 vs 141 tests). Therefore the certification does not claim demonstrated total-token or monetary-cost savings.
- **External Blockers**: Existing AUTH_BLOCKED / FREEBUFF_HEADLESS_BLOCKED / herdr-board compatibility states were intentionally left unchanged; no quota-consuming re-probes were performed.

## [2026-09-26] Documentation Reorganization & Archive

- **Scope**: Documentation-only maintenance plus archive moves. No model/provider calls were used.
- **Current Documentation Refresh**: Rewrote `README.md`, `HARNESS_PROFILES.md`, `ORCHESTRATOR.md`, `REPRODUCIBILITY.md`, and `CONTEXT_EFFICIENCY.md` to reflect Factory v9.0.0, v8 context architecture, v9 reasoning policy, current evidence boundaries, and provider-call discipline.
- **New Indexes**: Added `docs/README.md`, `docs/CURRENT_STATE.md`, `docs/archive/README.md`, and `certification/README.md`.
- **Archive Policy**: Historical certification narratives from v3, v6.1, and v7 were moved to `docs/archive/releases/`. Current app specifications remain in their established paths because retained plans/evidence reference them. Machine-readable certification evidence remains under `certification/`.
- **Link Hygiene**: Current documentation now uses repository-relative links instead of host-specific `file:///root/...` paths.
- **Evidence Interpretation**: Current docs consistently state the v8 75.1% context-byte reduction and the narrower v9 reasoning/output reductions while explicitly recording the +27.20% input-token increase and declining to claim total-token or monetary-cost savings.
- **Reasoning Safety**: Current docs consistently state that `PATH_VALIDATION_FAILED` is a fail-closed scope guardrail and never a trigger for higher reasoning effort.
- **Version Hygiene**: Documentation now distinguishes Factory v9.0.0 from retained schema/config versions (notably context policy 8.0.0 and harness profile schema/config 6.1.0).

## [2026-09-26] Factory Control UI Lite

- **Scope**: Implemented locally and provider-free. No AGY, Droid, Codex, Claude, OpenCode, or other model/provider calls were used.
- **Architecture**: Added a loopback-only Python stdlib HTTP facade and a read-only `FactoryReadModel`; no UI database, ORM, scheduler, routing engine, WebSocket layer, frontend build system, or Node/npm runtime.
- **Frontend**: Added four views — Overview, Board, Goals/Runs, and System — with task details in a drawer. The board is a projection only; no drag/drop state mutation is allowed.
- **Reuse**: Uses Web Awesome 3.14.0 and Alpine CSP 3.17.4 instead of custom components/state plumbing. Exact npm packages are locked in `ui/vendor.lock.json`, registry SRI is verified, and generated browser assets are self-hosted under ignored `.tools/ui/vendor/`.
- **Actions**: v1 exposes only existing stable Factory operations. Goal resume delegates to the public Factory CLI and warns that real execution can consume provider usage. No UI-specific retry/cancel/DAG-edit semantics were introduced.
- **Efficiency**: Snapshot polling is adaptive (active/idle/background) and state-derived ETags return HTTP 304 when nothing changed. WebSockets/SSE were deliberately deferred.
- **Security**: Loopback-only bind, explicit loopback Host validation (DNS-rebinding resistance), no CORS, same-origin mutation checks, CSP without `unsafe-eval`, Alpine CSP build, bounded JSON bodies, path traversal/identifier guards, and compact evidence projections instead of raw provider prompt/output exposure.
- **Verification**: Added 12 deterministic provider-free tests covering read-model projections, task/goal/run detail, ETag stability/304, static/traversal security, loopback/Host policy, same-origin resume delegation, vendor extraction/SRI failure, tamper detection, and lock path safety. Python/Bash/JavaScript/JSON syntax checks passed during implementation.

## [2026-09-26] UI Plan Closure & Core Fail-Closed Hardening

- **Scope**: Provider-free closeout of Factory Control UI plus targeted repair of demonstrated pre-existing Factory recovery/provenance defects. No model/provider calls were used.
- **UI Plan Gaps Closed**: Restored task-scoped Requirements, Context, Validation, Git, Attempts and Events surfaces; added context-byte/attempt overview metrics, model/effort/duration card details, retry/escalation/blocked badges, run validation/audit evidence, and reasoning provenance while keeping the Kanban read-only.
- **Shared State Contract**: Added pure `tools/factory_contracts.py` so the Factory core and UI share canonical task-to-Kanban mapping, terminal state semantics, real-only monotonicity helpers, run-resume identity and root-scoped runtime Git filtering. This removes the duplicated/drifting UI state map.
- **UI Bugs Fixed**: Corrected intermediate-state projection (`VALIDATING/COMMITTING/INTEGRATING` remain RUNNING; `CONFLICTED` projects to REVIEW), filter-before-tail telemetry selection, duration fallback aggregation, active-run selection, terminal CANCELLED goals, runtime symlink escapes, Host/Origin parsing, bounded error exposure and sensitive raw evidence leakage.
- **Real-Only Fail-Closed**: GoalSpec planner, plan compiler, plan reviewer and final auditor now raise `RealProviderRequiredError` when a real-only live semantic role fails or returns invalid structured output instead of degrading silently to deterministic/APPROVED/ACCEPTED fallback.
- **Recovery/Provenance Fixes**: Missing goal IDs fail closed; `real_only` persists monotonically across GoalController/run resume; first execution no longer enters reconciliation after assigning a new run ID; new run manifests record Factory v9 and `real_only`; string validations use `shlex.split` without shell execution.
- **Test-Harness Isolation**: `PLAN_REVIEW_TEST_VERDICT` and `AUDIT_TEST_VERDICT` are honored only when `FACTORY_TEST_HARNESS=1`.
- **Git Cleanliness Fix**: Replaced substring matching for `.agy-factory` with root-scoped porcelain-path filtering so files such as `src/foo.agy-factory.py` cannot be hidden from the dirty-repository gate.
- **Maintenance Cleanup**: Removed unused core imports and a dead typo assignment in remediation tests; active doctor/portable/real-verification scripts now identify v9; `verify-real.sh` no longer hardcodes old auth outcomes or hides failed smoke exit codes.
- **herdr-board Update Gate**: The updater now recognizes official herdr-board v0.18.0 (tag commit `d7a67470309c378778e388982bda67eee6dc1a58`) as supporting Herdr 0.9.1/protocol 22. The committed toolchain lock remains the previous certified v0.17.0 baseline until `--apply` is run on the real host after provider-free gates.
- **Provider-Free Validation Executed Here**: 32 UI/contracts/vendor tests passed under `PYTHONHASHSEED=0,1,42`; Python compileall, Bash syntax for the local UI launcher, JavaScript syntax, JSON parsing and static UI CSP/no-drag checks passed.
- **Full-Checkout Validation Boundary**: This execution environment could not materialize the full private repository checkout. New runtime/source-contract tests for the core and active maintenance scripts are committed so the repository's normal `./scripts/verify.sh` executes them on the actual checkout. Full Factory/MiniBoard/MiniLinks/portable-smoke execution remains the final host-side validation step; no false claim of having run it is made here.

