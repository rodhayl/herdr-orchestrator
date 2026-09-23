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

