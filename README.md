# AGY-Herdr Software Factory v9.0.0

A project-local, orchestrator-agnostic software factory for turning goals or declarative DAGs into isolated implementation work, deterministic validation, auditable Git integration, and bounded review/remediation.

The current release combines:

- durable DAG execution and crash recovery;
- capability/profile-based multi-harness routing;
- external-project Autopilot;
- truthful REAL/MOCK execution provenance;
- deterministic context compilation and bounded handoffs;
- a versioned reasoning-effort policy with bounded escalation;
- provider-free regression and clean-room portability workflows;
- a local Factory Control UI for goals, runs, Kanban projection, profiles, context/reasoning state and bounded public actions.

## Current status

The canonical state summary is [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md).

Important evidence boundaries:

- v8 measured a **75.1% reduction in Factory-supplied context bytes** on the TreeHash benchmark while preserving 100% required-anchor recall.
- v9 observed **59.57% fewer worker reasoning tokens** and **31.87% fewer worker output tokens** than the recorded v8 TreeHash run, but worker input tokens increased **27.20%**.
- The v8 and v9 TreeHash runs produced different test-suite sizes, and v8 does not expose comparable cached-input telemetry.
- Therefore the repository does **not** claim demonstrated total-token savings or monetary-cost savings from the v8→v9 comparison.
- `reasoning_policy.json` is an initial evidence-backed production default, not a universal optimum.

## Architecture

```text
High-level goal / DAG
        |
        v
Project policy + GoalSpec
        |
        v
Planner -> deterministic plan gates -> reviewer
        |
        v
ContextCompiler
  - role-specific packets
  - required anchors
  - bounded handoffs
        |
        v
Deterministic router
        |
        v
ReasoningPolicy
  routine / standard / deep
  bounded same-family escalation
        |
        v
WorkerAdapter
  AGY | Droid | Codex | Claude | OpenCode
        |
        v
isolated task worktrees
        |
        v
path + test + integration gates
        |
        v
final audit / bounded remediation
```

Factory state, scheduling, routing, retries, Git integration, completion gates, and evidence remain deterministic. Models perform semantic tasks; they do not own completion truth.

The v9 closeout also hardens recovery/provenance: real-only semantic roles fail closed on provider failure or malformed output, real-only intent persists across resume, fresh runs do not enter resume reconciliation accidentally, and project cleanliness ignores only the repository-root `.agy-factory/` runtime subtree.

## Quick start — provider-free

```bash
./scripts/doctor.sh
./scripts/update-package.sh --check
./scripts/bootstrap.sh
./scripts/verify.sh
```

For a clean-room rehearsal:

```bash
./scripts/portable-smoke.sh
```

These are the normal maintenance paths. Real-provider verification is intentionally separate because it consumes provider usage:

```bash
./scripts/verify-real.sh
```

Run it only when new real-provider evidence is actually required.

## Factory Control UI

Factory v9 includes a local, no-build browser control surface:

```bash
./scripts/ui.sh --project-root /path/to/project
```

Then open `http://127.0.0.1:8765`.

The UI is intentionally thin: Factory remains the single source of truth, the Kanban is read-only, there is no UI database, and mutable actions only delegate to existing public Factory operations. Browser dependencies are exact-version, SRI-verified and self-hosted after first sync; no Node/npm runtime is required.

See [docs/FACTORY_UI.md](docs/FACTORY_UI.md).

## External-project Autopilot

```bash
python3 tools/factory.py --project-root /path/to/project project init --name "MyProject"
python3 tools/factory.py --project-root /path/to/project project doctor
python3 tools/factory.py --project-root /path/to/project goal run --goal-file /path/to/GOAL.md --real-only
python3 tools/factory.py --project-root /path/to/project goal report --goal-id <goal-id>
```

Interrupted goals/runs are resumed from durable state rather than restarted from scratch.

## Execution provenance

Production evidence distinguishes:

- `REAL`: verified provider-backed execution;
- `MOCK`: deterministic test-harness execution;
- `TRANSPORT_ONLY`: transport was proven without substantive task execution;
- `UNKNOWN`: insufficient evidence.

Mock execution can validate architecture and recovery, but cannot satisfy a real-provider certification gate.

## Current harness state

The live source of truth is [harness_profiles.json](harness_profiles.json), with the last certified stack in [toolchain.lock.json](toolchain.lock.json).

At the current documented baseline:

| Harness | State |
| --- | --- |
| AGY | real-provider certified profiles exist |
| OpenCode | `opencode-mimo-free` real-provider certified |
| Droid | adapter implemented/deterministically tested; direct profiles currently `AUTH_BLOCKED` |
| Codex | adapter implemented/deterministically tested; direct profiles currently `AUTH_BLOCKED` |
| Claude Code | adapter implemented/deterministically tested; direct profiles currently `AUTH_BLOCKED` |
| OpenCode Gemini | `PROFILE_UNAVAILABLE` under current provider guardrails |
| Freebuff | `FREEBUFF_HEADLESS_BLOCKED` |
| herdr-board | certified lock still records v0.17.0 as blocked; the update gate now recognizes upstream v0.18.0 compatibility with Herdr 0.9.1/protocol 22 |

These statuses can drift. Use `doctor.sh` and `update-package.sh --check`; do not silently mutate authentication to make a test pass.

## Reasoning policy

The v9 policy separates routing from reasoning effort.

- routine work: lower certified effort where supported;
- standard work: medium/default calibrated effort;
- deep work and final audit: conservative high effort;
- at most one same-model-family escalation by default;
- only reasoning-quality failures can trigger escalation;
- infrastructure/auth failures and scope/path guardrail failures never trigger higher effort.

See [reasoning_policy.json](reasoning_policy.json) and [UPDATE_PACKAGE.md](UPDATE_PACKAGE.md).

## Context policy

v8 introduced deterministic role-specific context packets, file references instead of broad inlining, 100% required-anchor recall gates, bounded handoffs, stable prefixes, fresh-session defaults, and stale-packet detection.

See [CONTEXT_EFFICIENCY.md](CONTEXT_EFFICIENCY.md) and [context_policy.json](context_policy.json).

## Documentation

Start with [docs/README.md](docs/README.md).

Current operational documents:

- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md)
- [ORCHESTRATOR.md](ORCHESTRATOR.md)
- [HARNESS_PROFILES.md](HARNESS_PROFILES.md)
- [CONTEXT_EFFICIENCY.md](CONTEXT_EFFICIENCY.md)
- [REPRODUCIBILITY.md](REPRODUCIBILITY.md)
- [UPDATE_PACKAGE.md](UPDATE_PACKAGE.md)
- [UPDATE_HISTORY.md](UPDATE_HISTORY.md)

Application contracts:

- [MiniBoard specification](docs/SPECIFICATION.md)
- [MiniLinks specification](examples/minilinks/SPEC.md)

Historical narrative certification documents are under [docs/archive/](docs/archive/README.md). Machine-readable certification evidence remains under [certification/](certification/README.md).

## Repository layout

```text
tools/              orchestration, context, reasoning engines and UI HTTP facade
ui/                 Factory Control UI static assets + frontend dependency lock
schemas/            versioned machine-readable contracts
factory_tests/      Factory regression/invariant tests
scripts/            doctor, update, verify, portability, certification utilities
prompts/            stable worker/reviewer prompt contracts
plans/              retained orchestration plans and compatibility fixtures
certification/      machine-readable certification evidence
docs/               current docs index, app specification, historical archive
examples/minilinks/ second reference application
app/, web/, tests/  MiniBoard reference application
.agy-factory/       retained historical evidence/runtime samples in this PoC repository
```

## Project principles

1. Local/project scope before global mutation.
2. Deterministic control plane; model reasoning only where semantic reasoning is needed.
3. Fail closed on path, provenance, schema, context, and certification ambiguity.
4. Provider-free tests by default.
5. Real-provider calls only when they create genuinely new evidence.
6. Historical evidence is preserved, but historical documentation is not presented as current truth.
