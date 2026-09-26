# Current state — 2026-09-26

## Release

**AGY-Herdr Software Factory: v9.0.0**

Version boundaries currently coexist intentionally:

| Item | Version / state |
| --- | --- |
| Factory engine | 9.0.0 |
| Reasoning policy/schema | 9.0.0 |
| Context policy/schema | 8.0.0 |
| Harness profile schema/config description | 6.1.0 |
| Herdr in certified lock | 0.9.1 / protocol 22 |
| Python policy | CPython 3.12, stdlib-only |

A lower schema version does not mean the Factory release is stale; schema versions advance only when their contract changes.

## Current architecture

v9 combines the previously certified capabilities:

- arbitrary DAG scheduling and durable attempt state;
- isolated worktrees and deterministic Git integration;
- REAL/MOCK/TRANSPORT_ONLY execution provenance;
- capability/profile routing across AGY, Droid, Codex, Claude, and OpenCode adapters;
- external-project Goal Autopilot;
- deterministic requirement traceability and bounded remediation;
- v8 ContextCompiler with role-specific packets, 100% required-anchor gates, bounded handoffs, and fresh-session defaults;
- v9 deterministic reasoning-effort policy with bounded same-model-family escalation.

## Current evidence interpretation

### v8 context efficiency

The preserved TreeHash benchmark records:

- v7 Factory-supplied workflow context: 51,170 bytes;
- v8 compiled workflow context: 12,723 bytes;
- reduction: 75.1%;
- required-anchor recall: 100%.

This is a provider-independent byte measurement.

### v9 reasoning-effort comparison

The preserved v8→v9 TreeHash comparison records:

- worker reasoning tokens: -59.57%;
- worker output tokens: -31.87%;
- worker duration: -20.10%;
- worker input tokens: +27.20%.

Limitations:

- the v8 baseline does not contain comparable cached-input-token telemetry;
- the two target runs produced different test-suite sizes (87 vs 141 passing tests);
- provider monetary usage/cost units were unavailable.

Therefore the repository does **not** claim proven total-token savings, cost savings, or a universal optimal effort policy.

## Reasoning safety closeout

`PATH_VALIDATION_FAILED` is a non-escalatable guardrail/scope failure.

Higher reasoning effort must never be used automatically as a response to a worker writing outside its allowed scope. Infrastructure/auth failures likewise do not trigger reasoning escalation.

## Harness/provider baseline

From the current committed profile/lock records:

| Harness/profile family | Documented state |
| --- | --- |
| AGY | real-provider certified profiles |
| OpenCode free | real-provider certified |
| Droid | adapter/profile implementation deterministic; direct live profiles AUTH_BLOCKED |
| Codex | adapter/profile implementation deterministic; direct live profiles AUTH_BLOCKED |
| Claude Code | adapter/profile implementation deterministic; direct live profiles AUTH_BLOCKED |
| OpenCode Gemini | PROFILE_UNAVAILABLE under current provider guardrails |
| Freebuff | FREEBUFF_HEADLESS_BLOCKED |
| herdr-board | BLOCKED_EXTERNAL_COMPATIBILITY |

Use read-only diagnostics for live status. Do not mutate credentials merely to improve a certification matrix.

## Verification policy

Normal maintenance:

```bash
./scripts/update-package.sh --check
./scripts/doctor.sh
./scripts/verify.sh
```

Portability-sensitive changes:

```bash
./scripts/portable-smoke.sh
```

Real-provider verification is optional and quota-consuming. Run it only when explicitly needed to establish new evidence.

## Current authoritative files

- Factory/runtime config: `factory.json`
- Harness profiles: `harness_profiles.json`
- Context policy: `context_policy.json`
- Reasoning policy: `reasoning_policy.json`
- Certified stack: `toolchain.lock.json`
- Schemas: `schemas/`
- Operational update workflow: `UPDATE_PACKAGE.md`
- Current documentation map: `docs/README.md`

Historical narrative certifications are archived under `docs/archive/releases/`.
