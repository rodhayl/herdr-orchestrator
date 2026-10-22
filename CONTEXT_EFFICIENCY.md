# Context & Usage Efficiency — v8 baseline, v9 interpretation

## Current role of this document

v8 introduced the deterministic Context Management subsystem. v9 retained that architecture and changed a separate variable: reasoning effort.

The context system is therefore still the active v9 baseline.

## Verified v7 → v8 context result

The preserved TreeHash benchmark records:

| Stage | v7 bytes | v8 bytes | Reduction |
| --- | ---: | ---: | ---: |
| reviewer | 16,543 | 2,613 | 84.2% |
| task_core_impl | 5,711 | 1,943 | 66.0% |
| task_cli_impl | 5,633 | 2,332 | 58.6% |
| task_unit_tests | 6,870 | 2,634 | 61.7% |
| auditor | 16,413 | 3,201 | 80.5% |
| **workflow total** | **51,170** | **12,723** | **75.1%** |

Required-anchor recall remained 100%.

This is the recorded Factory-supplied byte comparison, independent of provider token accounting. The exact historical aggregate is retained in [context-baseline-metrics.json](certification/v7/context-baseline-metrics.json). Raw historical prompts are omitted, so prompt-level reconstruction of that measurement is not available from this snapshot.

## Active ContextCompiler invariants

- role-specific context packets;
- file references preferred over broad source inlining;
- required anchors must achieve 100% recall before dispatch;
- cross-task semantic handoffs are bounded;
- new tasks default to fresh sessions;
- native compaction is not required for correctness;
- stable prompt prefixes are rendered deterministically;
- stale source hashes invalidate packets;
- context budgeting uses deterministic pruning, never blind slicing;
- project/run isolation prevents context leakage.

Authoritative policy: [context_policy.json](context_policy.json).

## v9 reasoning comparison

The preserved v8→v9 TreeHash comparison observed:

| Metric | v8 | v9 | Observed change |
| --- | ---: | ---: | ---: |
| worker reasoning tokens | 90,703 | 36,667 | -59.57% |
| worker output tokens | 136,950 | 93,299 | -31.87% |
| worker input tokens | 1,095,534 | 1,393,545 | **+27.20%** |
| worker duration | 661,324 ms | 528,383 ms | -20.10% |

Interpretation limits:

1. v8 did not record comparable cached-input-token telemetry.
2. v8 and v9 target runs produced different test-suite sizes (87 vs 141 passing tests).
3. provider monetary usage/cost units were unavailable.
4. therefore these runs do not establish total-token savings, cost savings, or a precise causal percentage attributable only to effort.

The valid conclusion is narrower: the recorded v9 run used substantially fewer reasoning/output tokens and less wall-clock time while preserving the recorded quality gates.

## Reasoning policy

v9 uses a deterministic, versioned policy after routing.

The policy is an initial evidence-backed experimental default, not a universal optimum.

It uses bounded escalation only for reasoning-quality failures. Infrastructure/auth/context/path guard failures do not trigger higher effort. `PATH_VALIDATION_FAILED` is explicitly non-escalatable.

Authoritative policy: [reasoning_policy.json](reasoning_policy.json).

## Provider metric honesty

Provider metrics are recorded only when actually exposed:

- input tokens;
- cached input tokens;
- output tokens;
- reasoning tokens;
- provider usage units if available.

Unavailable fields remain null/unknown in evidence. Do not reconstruct hidden reasoning or monetary cost from guesses.

Provider-independent measurements such as rendered packet bytes remain exact.

## Operational recommendation

Do not repeatedly run model-backed calibration/audits to optimize an already-certified baseline.

For routine changes:

```bash
./scripts/verify.sh
```

If the prototype is explicitly reopened, collect experimental-run metrics without claiming production validation. Recalibrate only for a demonstrated model/profile drift or systematic quality/usage problem.

See [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) for the overall release status.
