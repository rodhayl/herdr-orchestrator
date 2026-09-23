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
- **Toolchain Lock & Governance**: Updated `factory.json`, `harness_profiles.json`, `toolchain.lock.json`, `scripts/update-package.sh`, `scripts/doctor.sh`, and schemas to `v6.1.0`. Preserved Herdr 0.9.1 `BLOCKED_EXTERNAL_COMPATIBILITY` for `herdr-board` without patching upstream gates.


