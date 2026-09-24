# CONTEXT_EFFICIENCY.md — Context Efficiency Architecture & Verification (v8.0.0)

## Executive Summary

The AGY-Herdr Software Factory v8.0.0 delivers a **75.1% reduction** in Factory-supplied prompt and context bytes on the primary TreeHash certification workflow, comfortably exceeding the mandatory $\ge 40\%$ reduction objective.

Crucially, this efficiency gain is achieved with **100.0% required anchor recall** across all dispatched worker, reviewer, and auditor stages, preserving deterministic validation quality, attempt isolation, and clean-room portability.

---

## 1. Verified A/B Benchmark Results (TreeHash Workflow)

| Role / Stage | v7 Bytes | v8 Bytes | Reduction | Anchor Recall |
|:---|:---:|:---:|:---:|:---:|
| `reviewer` | 16,543 B | 2,613 B | **-84.2%** | 100% |
| `task_core_impl` | 5,711 B | 1,943 B | **-66.0%** | 100% |
| `task_cli_impl` | 5,633 B | 2,332 B | **-58.6%** | 100% |
| `task_unit_tests` | 6,870 B | 2,634 B | **-61.7%** | 100% |
| `auditor` | 16,413 B | 3,201 B | **-80.5%** | 100% |
| **TOTAL (Workflow)** | **51,170 B** | **12,723 B** | **-75.1%** | **100%** |

### Redundancy Analysis
- **v7 Baseline Redundancy Ratio**: `67.1%`
- **v8 Compiled Redundancy Ratio**: `59.7%`
- **Measurement Standard**: Exact provider-independent byte counts calculated via bounded chunk segmentation.

---

## 2. Context Compiler Architecture

The v8 context engine replaces ad-hoc multi-path prompt construction with a deterministic, role-specialized `ContextCompiler`:

1. **Role-Specific Context Packets**:
   - `PlanReviewContextPacket`: Scoped Goal Spec, proposed plan, policy constraints, and structural traceability.
   - `TaskContextPacket`: Scoped criteria, task-relevant disk file references, predecessor task handoffs, and deterministic validations.
   - `AuditContextPacket`: Authoritative Goal Spec, validation evidence, clean-commit Git diffs, and audit schema.

2. **File References Over File Inlining**:
   - Agents operate directly within isolated Git worktrees and inspect code natively via tools.
   - Raw full-file copies are completely eliminated from worker prompts by default; inlined excerpts are only included when strictly necessary and bounded.

3. **Required Anchor Gate**:
   - Every requirement ID, allowed path, and validation command constitutes a required anchor.
   - Dispatch fails closed (`CONTEXT_ANCHOR_MISSING`) if `required_anchor_recall < 1.0`.

4. **Bounded Semantic Handoffs**:
   - Cross-task communication flows exclusively through immutable `HandoffPacket` instances bounded to $\le 4,096$ bytes.
   - Unbounded conversation histories between tasks are strictly forbidden.

5. **Stable Prefix Architecture**:
   - Static operational contracts are canonically positioned at the prefix of prompts, maximizing KV-cache reuse.
   - Dynamic prompt content is isolated to the tail.

6. **Derived Requirement Auditing**:
   - Every derived requirement must trace to an explicit criterion or hard invariant with a documented rationale.
   - Orphan derived requirements fail closed (`OrphanDerivedRequirementError`).

---

## 3. Provider Metric Honesty

In accordance with Factory truth invariants:
- Provider token counts (`input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens`) are recorded when reported by the underlying provider.
- When an adapter or harness does not report token metrics, fields remain `null`.
- Canonical measurements remain exact byte lengths.
