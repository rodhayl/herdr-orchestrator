# AGY-Herdr Software Factory — Permanent Package Update & Maintenance Playbook

Authoritative operational procedure governing software version discovery, toolchain locking, compatibility resolution, and dependency updates for the AGY-Herdr Software Factory.

---

## 1. Update Trigger

Package version inspection and compatibility checking occurs under either of two conditions:

1. **Mandatory Iteration Gate**: At the beginning of **every** future substantive implementation iteration, before modifying factory code or application features.
2. **Explicit User Request**: Whenever requested to update dependencies, refresh the stack, check versions, migrate to newer Herdr/AGY/Droid, or update `herdr-board`.

Every coding agent must execute this workflow before feature work:
```bash
# 1. Inspect operational instructions
cat UPDATE_PACKAGE.md

# 2. Inspect the previously certified lock
cat toolchain.lock.json

# 3. Run the read-only package update check
./scripts/update-package.sh --check

# 4. Review the generated version and compatibility matrix
# 5. Resolve compatible project-local updates
# 6. Only then proceed to feature development
```

---

## 2. Sources of Truth & Precedence

Version numbers, CLI flags, supported models, and protocols must **never** be inferred from model memory or external blog posts. The authoritative precedence is:

```
Level 1: Live Installed CLI / Socket API
         (Probed directly from the host system environment)
    +
Level 2: Official Upstream Documentation & Repository Declarations
         (Authoritative specifications from upstream maintainers)
    +
Level 3: Official Stable Releases / Tags / Changelogs
         (Excluding preview, alpha, beta, rc, and nightly branches)
    +
Level 4: Repository Compatibility Declarations & Prior Certification
         (toolchain.lock.json and UPDATE_HISTORY.md)
```

If an upstream source claims compatibility but the live installed CLI fails execution, live runtime verification is authoritative.

---

## 3. Previous Certified Stack (`toolchain.lock.json`)

Before evaluating or proposing any updates, the agent **must** read and preserve the existing certified values from:
`toolchain.lock.json`

This file records the exact toolchain and dependencies that passed the last full certification suite:
- Factory engine version
- Operating system and architecture
- Herdr binary version, socket protocol, and API schema hash
- herdr-board release version, immutable git commit, required Herdr version, and protocol
- AGY CLI version, worker profiles (`agy` through `agy7`), certified model, and effort
- Droid CLI version, certified model, reasoning effort, and autonomy
- Python, Git, rustc, and cargo toolchain versions
- Exact ISO-8601 certification timestamp

**Rule**: Never overwrite `toolchain.lock.json` before comparison and verification are complete.

---

## 4. Current Installed Stack Probing

The update system queries installed binaries and running servers dynamically:
- **Herdr**: `herdr --version`, socket ping/snapshot (`herdr api snapshot` -> `.result.snapshot.version`, `.result.snapshot.protocol`), and API schema hash (`herdr api schema --json | sha256sum`).
- **AGY**: `agy --version`, available models (`agy models`).
- **Droid**: `droid --version`, `droid exec --help`, model catalog inspection, authentication check (`FACTORY_API_KEY`).
- **herdr-board**: Local binary (`.tools/bin/board --version` or system `board --version`).
- **Toolchain**: `python3 -V`, `git --version`, `rustc --version`, `cargo --version`.
- **System**: Host OS, architecture (`uname -s`, `uname -m`).

---

## 5. Latest Stable Upstream Stack Querying

The update system queries official upstream repositories for the newest **stable** releases:
- Stable release tags matching semantic versioning (`vX.Y.Z`).
- Strict exclusion: `preview`, `alpha`, `beta`, `rc`, `nightly`, git `HEAD`, and PR branches.
- Offline behavior: If network access is unavailable, the update check reports `OFFLINE` and uses the locked certified stack without fabricating version numbers.

---

## 6. Certified Baseline & Compatibility Summary

This section documents the **committed certified baseline**, not a substitute for a live `--check` run. Live/current/latest values may drift.

Baseline source: `toolchain.lock.json`.

The committed lock is evidence of the last certified stack, not a claim that the newest compatible upstream package has already been applied. As of 2026-09-26 the lock still records herdr-board v0.17.0; the read-only updater recognizes v0.18.0 as compatible with Herdr 0.9.1/protocol 22. Apply/update the lock only after the normal provider-free compatibility and regression gate.

| Component | Committed baseline | Current committed status / policy |
| :--- | :--- | :--- |
| Factory Engine | `9.0.0` | current release |
| Herdr | `0.9.1`, protocol `22` | certified external control-plane baseline |
| herdr-board | certified lock: `v0.17.0` | lock remains blocked; current upstream `v0.18.0` explicitly accepts Herdr 0.9.1 / protocol 22 and is selected by the update checker |
| AGY CLI | `1.2.10` | real-provider certified profiles retained |
| Droid CLI | `0.226.2` | adapter/profile implementation deterministic; direct profiles `AUTH_BLOCKED` |
| Codex CLI | `0.155.1` | adapter/profile implementation deterministic; direct profiles `AUTH_BLOCKED` |
| Claude Code | `2.1.263` | adapter/profile implementation deterministic; direct profiles `AUTH_BLOCKED` |
| OpenCode CLI | `1.18.31` | free profile real-provider certified; Gemini profile unavailable under current guardrails |
| Freebuff | `0.0.195` | `FREEBUFF_HEADLESS_BLOCKED` |
| Python | `3.12.3` | CPython, stdlib-only project policy |
| Git | `2.43.0` | retained baseline |

### Harness profile-state summary

Factory release and profile schema versions are independent: the Factory is v9.0.0 while `harness_profiles.json` currently declares schema/config version 6.1.0.

| Profile family | Committed status |
| :--- | :--- |
| AGY specification/backend/frontend/tests/integration/audit | `REAL_PROVIDER_CERTIFIED` profiles are present |
| Droid backend | `AUTH_BLOCKED` for direct live execution; deterministic adapter coverage retained |
| Codex Luna | `AUTH_BLOCKED` for direct live execution; deterministic adapter coverage retained |
| Claude Sonnet 5 | `AUTH_BLOCKED` for direct live execution; deterministic adapter coverage retained |
| OpenCode free | `REAL_PROVIDER_CERTIFIED` |
| OpenCode Gemini | `PROFILE_UNAVAILABLE` |

Do not reinterpret `enabled=true` as live authentication. Live status must be discovered read-only.

---

## 7. Deterministic Update Policy

### A. User / Host-Managed External Prerequisites
External tools are **never** auto-updated or mutated by the Factory:
- `herdr`, `agy`, `droid`, `python3`, `git`, `rustc`, `cargo`.
- Host packages (`apt`, `brew`, `pacman`), global symlinks, global config files.
- If an external tool has changed since previous certification:
  - If compatible: revalidate, run regressions, update lock upon passing.
  - If incompatible: report `EXTERNAL_UPDATE_REQUIRED` or `EXTERNAL_INCOMPATIBILITY`. Halt modification.

### B. Project-Local Dependencies (`.tools/`, `herdr-board`)
Project-local dependencies may be updated via `./scripts/update-package.sh --apply` if and only if:
1. A newer official stable release exists.
2. The release **explicitly supports** the installed external toolchain (e.g. Herdr version & protocol).
3. All deterministic test suites pass with the new version.

### C. Herdr / herdr-board Pinned Compatibility Invariant
Compatibility strictly takes precedence over recency:
```
detected installed Herdr version & protocol
    -> inspect all stable herdr-board releases
    -> select the NEWEST STABLE release that EXPLICITLY supports that Herdr version & protocol
```
- If no stable release officially supports the installed Herdr:
  - **Do NOT** downgrade Herdr.
  - **Do NOT** patch upstream compatibility gates.
  - **Do NOT** use a preview or unreleased branch.
  - **Do NOT** pretend compatibility.
  - Continue non-board factory work and mark board status as:
    `BLOCKED_EXTERNAL_COMPATIBILITY`

---

## 8. Validation Gate

Before any update is committed to `toolchain.lock.json`, the entire verification harness must pass:
1. `python3 -m unittest discover -s factory_tests -v`
2. `python3 -m unittest discover -s tests -v`
3. `python3 scripts/smoke_test.py`
4. `python3 -m unittest discover -s examples/minilinks/tests -v`
5. `python3 examples/minilinks/scripts/smoke_test.py`
6. `scripts/verify.sh`
7. `scripts/portable-smoke.sh`

---

## 9. Rollback Procedure

If an update fails validation:
1. Discard modified project-local dependency files (`git checkout -- .tools/`).
2. Restore previous `toolchain.lock.json` from git HEAD.
3. Record the failure reason in `UPDATE_HISTORY.md` under a `FAILED_UPDATE` entry.
4. Leave the certified working stack intact.

---

## 10. Audit History (`UPDATE_HISTORY.md`)

Every execution of `./scripts/update-package.sh --apply` or significant compatibility evaluation appends a structured record to `UPDATE_HISTORY.md`. No entries may be deleted.

---

## 11. Harness Profile Governance

Execution Profiles decouple task definitions and routing decisions from raw worker names:
1. **Schema Compliance**: All profiles in `harness_profiles.json` must strictly conform to `schemas/harness-profiles.schema.json`.
2. **Explicit Semantics**: Every profile declares harness-specific parameters (e.g., AGY `thinking_budget`, Droid `autonomy`, Codex `sandbox_mode`, Claude `budget_tokens`).
3. **Compatibility Probing**: Profile validity is audited automatically during `./scripts/update-package.sh --check` and `./scripts/doctor.sh`.
4. **Concurrency Bounds**: Each profile configures `max_concurrency` (default: 1) to prevent resource starvation.
5. **No Speculative Rerouting**: The router operates strictly on capability ranking across certified profiles; if a preferred profile's provider is unauthenticated or busy, it falls back to the next certified profile in order.

---

## 12. Reasoning Policy & Effort Governance (v9.0.0)

Reasoning Policy isolates and optimizes provider reasoning effort:
1. **Schema Compliance**: `reasoning_policy.json` strictly conforms to `schemas/reasoning-policy.schema.json`.
2. **Model-Specific Ladders**: Supported effort levels (`low`, `medium`, `high`, `xhigh`) are model-specific and validated against live CLI capabilities. Universal native effort enums are strictly forbidden.
3. **Deterministic Selection**: Initial reasoning effort is resolved strictly from `(role, task_type, execution_class, model_family)` without LLM or probabilistic routing.
4. **Bounded Deterministic Escalation**: Failed tasks on quality-related failures (e.g. `DETERMINISTIC_TEST_FAILED`, `REQUIREMENT_VALIDATION_FAILED`) may escalate by at most 1 ladder step within the same model family. Infrastructure failures (`AUTH_BLOCKED`, network, timeout) and guardrail/scope violations such as `PATH_VALIDATION_FAILED` fail closed and never escalate reasoning effort.
5. **Provenance Hash Invariant**: `reasoning_policy.json` records SHA-256 provenance hashes of `context_policy.json`, `toolchain.lock.json`, `harness_profiles.json`, and calibration evidence.
6. **Governance Status Taxonomy**:
   - `VALID`: All provenance hashes match live files; calibrated ladders are certified.
   - `NEEDS_REVALIDATION`: Upstream context policy or calibration evidence drifted.
   - `PROFILE_DRIFT`: Harness profile models or effort configurations drifted.
   - `EXTERNAL_UPDATE_REQUIRED`: External toolchain lock or installed CLI versions changed.
7. **Read-Only Verification**: `./scripts/update-package.sh --check` audits reasoning policy provenance without consuming provider quota.
8. **Calibration Scope**: The certified v9 policy is an initial evidence-backed production default. Fixture calibration does not establish a universal optimum across repositories or future model versions; real usage should be observed passively and recalibration should be deliberate, bounded, and separately justified.
9. **Efficiency Claim Boundary**: v9 certification demonstrates lower reasoning/output tokens and lower wall-clock time on the recorded TreeHash comparison. Because input tokens increased and provider cost units were unavailable, governance documentation must not infer total-token or monetary-cost savings from that comparison.

---

## 13. Documentation Governance

Current documentation is indexed in `docs/README.md` and summarized in `docs/CURRENT_STATE.md`.

Rules:
1. Keep operational files consumed by scripts/agents at stable paths unless code is changed in the same commit.
2. Use relative repository links in current docs; do not add host-specific `file:///root/...` links.
3. Archive superseded narrative certification documents under `docs/archive/releases/` instead of deleting history.
4. Keep machine-readable certification evidence under `certification/`; do not move current evidence into the narrative archive.
5. Distinguish Factory release version, schema/config versions, live auth state, deterministic test status, and real-provider certification.
6. Do not claim total-token or monetary-cost savings unless the evidence directly supports those metrics.
