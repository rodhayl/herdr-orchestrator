# Current state

Updated: 2026-10-22. Herdr Orchestrator v9.0.0 is an inactive experimental portfolio prototype. This document describes the source snapshot, not current authentication, provider service availability or production acceptance.

## Version boundaries

| Component | Recorded version |
| --- | --- |
| Factory engine | 9.0.0 |
| Reasoning policy/schema | 9.0.0 |
| Context policy/schema | 8.0.0 |
| Harness profile schema/config | 6.1.0 |
| Herdr in historical lock | 0.9.1 / protocol 22 |
| Python policy | CPython 3.12, standard library |

Schema versions change with their contracts, independently of the Factory release. `toolchain.lock.json` and profile certification fields preserve historical host observations; they are not fresh certifications of another machine.

## Architecture and safety

Factory owns durable DAG state, isolated worktrees, deterministic routing/integration and completion gates. Goal Autopilot adds planning, traceability, review and bounded remediation. The ContextCompiler supplies bounded role-specific packets with required-anchor checks. The reasoning policy permits bounded same-model-family escalation only for reasoning-quality failures, never for path, context, authentication or infrastructure failures.

Herdr lifecycle integration reports monotonic batch transitions and uses `agent.wait` for observation. Factory retains authority over worker commands and durable exit evidence. Missing session identifiers remain unknown until observed; bootstrap does not invent them.

Real-only intent persists across resume. Invalid semantic-role output fails closed rather than silently becoming a mock or approval. Test-only verdict overrides require `FACTORY_TEST_HARNESS=1`. The local UI projects Factory state and delegates only existing public actions. The retired external `herdr-board` is not an active dependency.

Path and Git guards are integration boundaries, not process isolation. Live workers and validation commands require an appropriately isolated host.

## Historical evidence

The v7/v8 TreeHash comparison recorded 51,170 versus 12,723 Factory-supplied bytes (75.1% reduction), with 100% required-anchor recall. The v8/v9 comparison recorded lower reasoning/output tokens and duration, but 27.20% higher input tokens. Different suite sizes and unavailable comparable cached-input telemetry preclude total-token or monetary-savings claims.

AGY and OpenCode free profiles have historical real-provider evidence. Direct Droid, Codex and Claude profiles recorded `AUTH_BLOCKED`; OpenCode Gemini recorded `PROFILE_UNAVAILABLE`; Freebuff recorded `FREEBUFF_HEADLESS_BLOCKED`. These are retained observations, not live status checks. Configure and revalidate a host before real execution, without changing authentication merely to make tests green.

## Maintenance

The offline path is the strict package check plus `scripts/verify.sh`. `doctor.sh` and `portable-smoke.sh` additionally need the Herdr host prerequisites, even with provider probes disabled. See [Reproducibility](../REPRODUCIBILITY.md) and [current snapshot validation](PORTFOLIO_VALIDATION.md).

Operational policy remains at stable root paths: `factory.json`, `harness_profiles.json`, `context_policy.json`, `reasoning_policy.json`, `toolchain.lock.json` and `schemas/`. The reasoning policy checks provenance hashes; changing a profile catalog or lock is not a cosmetic edit.

The concise [history](../UPDATE_HISTORY.md) and [machine-readable evidence](../certification/README.md) preserve useful provenance without raw historical prompts or redundant release reports.
