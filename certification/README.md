# Historical certification evidence

These records preserve experimental observations, not current provider availability, production readiness or a new certification of this source snapshot. Redacted historical copies retain their numerical measurements and verdicts. Generated runtime state is not evidence storage and remains untracked.

## v7

- `v7/autopilot-real-certification.json`: external-project Autopilot observation.
- `v7/context-baseline-metrics.json`: exact retained aggregate baseline (51,170 Factory-supplied bytes). It was moved without changing its contents. The five raw prompts are omitted; this snapshot does not reproduce the old measurement at prompt level.

## v8

- `v8/autopilot-real-certification.json`
- `v8/independent-audit-report.json`

The recorded context benchmark reports 75.1% fewer Factory-supplied bytes with 100% required-anchor recall. A redundant raw audit patch was omitted; maintained fixes and tests remain in source.

## v9

- `v9/effort-baseline.json`
- `v9/effort-capabilities.json`
- `v9/calibration-runs.jsonl`
- `v9/reasoning-policy-certification.json`
- `v9/reasoning-boundaries-20260929.json`
- `v9/treehash-v9-certification.json`
- `v9/v8-v9-comparison.json`

These establish an initial experimental reasoning policy and preserve the TreeHash comparison. Calibration records are also inputs to policy provenance checks and must not be removed as mere logs.

Reasoning/output tokens and duration fell in the recorded comparison, but input tokens increased; cached-input telemetry and target suite sizes are not comparable. The evidence does not establish total-token or monetary savings.

## Interpretation rules

- Preserve original measurements and distinguish `REAL`, `MOCK`, `TRANSPORT_ONLY` and `UNKNOWN`.
- Never rewrite historical data to imply fresh certification. Add clearly scoped interpretation instead.
- Use [engineering history](../UPDATE_HISTORY.md) for concise narrative context and [snapshot validation](../docs/PORTFOLIO_VALIDATION.md) for present deterministic checks.
- Absence of raw transcripts limits independent historical reproduction; offline regressions validate current deterministic behavior, not past provider execution.
