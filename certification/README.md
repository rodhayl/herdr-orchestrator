# Certification evidence

This directory contains retained machine-readable evidence and audit artifacts. It is distinct from narrative documentation.

## Current evidence sets

### v7

`v7/autopilot-real-certification.json`

Historical proof of external-project Autopilot execution.

### v8

- `v8/autopilot-real-certification.json`
- `v8/independent-audit-report.json`
- `v8/audit_diff.patch`

Primary context-efficiency certification. The recorded benchmark reports 75.1% Factory-supplied context-byte reduction with 100% required-anchor recall.

### v9

- `v9/effort-baseline.json`
- `v9/effort-capabilities.json`
- `v9/calibration-runs.jsonl`
- `v9/reasoning-policy-certification.json`
- `v9/treehash-v9-certification.json`
- `v9/v8-v9-comparison.json`

v9 establishes an initial evidence-backed reasoning policy and records the TreeHash comparison.

The comparison must be interpreted narrowly: reasoning/output tokens and wall-clock duration fell, while input tokens increased; cached-input telemetry is not comparable across the recorded v8/v9 artifacts; the target test-suite sizes differ. It therefore does not establish total-token or monetary-cost savings.

## Rules

- Never rewrite historical measurements to make later claims look cleaner.
- Corrections should add interpretation/metadata, not falsify source measurements.
- REAL/MOCK provenance must remain explicit.
- Narrative historical certifications belong under `docs/archive/`.
