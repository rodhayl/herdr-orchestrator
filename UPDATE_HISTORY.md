# Engineering and compatibility history

This is a condensed historical ledger, not an assertion that old hosts or providers remain available. Redundant release narratives and raw transcripts have been omitted; retained machine-readable evidence is indexed in [certification/README.md](certification/README.md).

## 2026-10-22: presentation naming follow-up

The previous source cleanup left inconsistent public branding. README, current documentation, CLI banners and the local UI now identify the project as **Herdr Orchestrator**. AGY provider identifiers and the internal `factory` paths, imports, state, API keys and environment variables remain unchanged. The profile catalog description is presentation-only; its current reasoning-policy fingerprint was refreshed, but profile definitions, calibration dates and historical evidence were not recertified or rewritten.

## 2026-10-22: source snapshot maintenance

- Retained the active runtime, dynamically consumed fake adapters, versioned regressions, application specifications, schemas and calibration fixtures.
- Consolidated redundant release/UI prose and removed an unconsumed MiniLinks certification stub. Moved the exact v7 aggregate context metrics to `certification/v7/context-baseline-metrics.json`; omitted five raw historical prompts, so that old measurement is not prompt-level reproducible here.
- Corrected bootstrap Git operations to target its own repository, removed invented Herdr control-plane IDs, and aligned status projection with Factory 9.0.0.
- Removed unused private-host configuration collection. Default executable discovery uses PATH or explicit overrides rather than a fixed home directory; explicit historical profile commands and certification fingerprints are unchanged.
- Repaired directory-fsync warning paths in atomic JSON/context/handoff persistence: logging is imported and opened directory descriptors close even when fsync fails.
- Added focused deterministic regressions, local database/environment ignore patterns, and documentation separating offline tests from live-host/provider validation. Exact results and limits are recorded in [snapshot validation](docs/PORTFOLIO_VALIDATION.md).

## 2026-09-29: contract and lifecycle cleanup

The active plan format became explicit DAG `tasks`; legacy `waves`, v5 profile aliases, unused planner-context primitives and the external `herdr-board` integration were removed. The local control UI became the canonical status surface. Routing now fails closed for a missing/malformed/empty profile catalog. Project concurrency, attempt and duration policy is wired to execution. Plan review and final audit validate distinct structured schemas; malformed verdicts fail closed. Reasoning provenance was refreshed for the then-changed policy/profile/lock inputs.

A later Linux validation report identified candidate `34fb5c23` and repaired missing context CLI wiring, enforcement of project concurrency/attempt/duration limits, incomplete UI usage aggregates, and test-created Git state pollution. Its attempted live AGY smoke was **BLOCKED after two HTTP 429 responses**, not a successful generation or renewed real-provider certification. Provider-free regressions remain the current reproducibility path.

## 2026-09-26–28: local UI, recovery and test isolation

The loopback-only stdlib UI added compact allowlisted projections, canonical state mapping, ETags, bounded same-origin actions and exact-version browser dependency integrity checks. It does not own a second scheduler or database. Real-only intent became durable across resume; semantic failures no longer silently downgrade to mock/approved output. Test overrides require explicit test-harness mode.

Git-test cleanup was constrained to test-owned resources, with fail-closed discovery and no global worktree pruning. Verification records HEAD/status and rejects unintended changes. Strict `FACTORY_PROVIDER_PROBES=0` became the deterministic default; lock `--apply` refuses that mode.

The historical host report for candidate `11e9debc262db47e907e15061a8e3b1076d74302` recorded 313 Factory, 34 MiniBoard and 51 MiniLinks tests, two HTTP smoke suites and three hash seeds, plus a portable-smoke PASS on its configured host. The original diagnostics included provider metadata/auth probes despite zero model inference; it was not literally a zero-provider-CLI run. Those old observations do not replace the current snapshot results.

## 2026-09-24–26: v7–v9 experiments

v7 introduced external-project Autopilot with bounded review/remediation and deterministic provenance. v8 introduced bounded ContextCompiler packets and required-anchor gates. The retained TreeHash aggregate records 51,170 v7 bytes versus 12,723 v8 bytes, a 75.1% reduction with 100% anchor recall.

v9 added a separate deterministic reasoning-effort policy. Its recorded TreeHash comparison shows reasoning tokens -59.57%, output tokens -31.87%, duration -20.10%, but input tokens +27.20%. Test-suite sizes differ (87 versus 141), cached-input telemetry is not comparable, and monetary usage is unavailable. No total-token, monetary-savings or universal-optimum conclusion follows. `PATH_VALIDATION_FAILED` is a non-escalatable scope failure.

## 2026-09-23: profiles and truthful provenance

v4/v5 introduced explicit toolchain inspection, execution profiles and additional harness adapters. v6 expanded capability/execution-class routing and telemetry across five harness families. Adapter implementation and deterministic testing were not equivalent to live certification.

The v6.1 audit reclassified the v6 mixed-harness rehearsal as **MOCK (contains mock execution)**: one Droid backend task was REAL, while other tasks were deterministic mocks. It was not real multi-harness certification. The fail-closed certification guard subsequently required genuine binary identity, attempt evidence and non-mock execution. Historical direct-provider authentication blockers were retained rather than hidden.

## v3 foundation

Durable DAG execution, dependency/ownership checks, isolated Git worktrees and recovery established the deterministic foundation. The v3 regression modules remain active consumers of that behavior, including dynamically selected fake adapters; old version names do not justify their deletion.
