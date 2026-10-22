# Herdr Orchestrator

An experimental, project-local software orchestration prototype. Herdr Orchestrator turns goals or declarative DAGs into isolated implementation tasks, deterministic validation and auditable Git integration.

**Status:** inactive portfolio project, runtime v9.0.0. The retained results describe historical experiments, not production readiness, current provider availability or customer adoption.

AGY is one supported provider, not the project name. Herdr is the external session/lifecycle tool. `Factory` is the internal engine name; consumed paths and identifiers such as `tools/factory.py`, `factory_tests/`, `factory.json`, `.agy-factory/`, imports and `FACTORY_*` settings remain stable for compatibility. They are active contracts, not abandoned directories.

## What it demonstrates

- Durable DAG scheduling, isolated task worktrees and crash recovery.
- Capability-based routing across AGY, Droid, Codex, Claude and OpenCode adapters.
- Explicit `REAL`, `MOCK`, `TRANSPORT_ONLY` and `UNKNOWN` execution provenance.
- Deterministic context compilation, required-anchor checks and bounded handoffs.
- A versioned reasoning-effort policy with bounded same-family escalation.
- External-project Goal Autopilot and a local, thin control UI.

Factory owns state, scheduling, validation and completion truth. Models perform semantic tasks; they do not decide whether deterministic gates passed. Git worktrees and path guards are not an operating-system sandbox.

## Try the offline regression suite

Requirements: Python 3.12 and Git. Python runtime and tests use the standard library. No provider account or live Herdr installation is required for this path.

```bash
FACTORY_PROVIDER_PROBES=0 ./scripts/update-package.sh --check
./scripts/verify.sh
```

The verification runner disables provider CLI probes and checks that Git HEAD and status are preserved. It runs Factory tests, both reference applications' tests and their HTTP smoke tests. A test requiring live Herdr is explicitly skipped when unavailable.

Optional `./scripts/bootstrap.sh` initializes ignored, project-local runtime state and a local Git identity if none is configured. It is not required for the offline test suite.

Live operation and `portable-smoke.sh` have additional host prerequisites. Follow [Reproducibility](REPRODUCIBILITY.md); do not run `verify-real.sh` or calibration scripts unless provider usage is intended.

## Architecture

```text
Goal / DAG -> project policy -> planner and plan gates
           -> context compiler -> profile router -> reasoning policy
           -> worker adapter -> isolated task worktree
           -> path, test and integration gates -> audit / bounded remediation
```

See [Orchestrator contract](ORCHESTRATOR.md), [Harness profiles](HARNESS_PROFILES.md) and [Current state](docs/CURRENT_STATE.md) for the operational boundaries.

## Local control UI

```bash
./scripts/ui.sh --project-root /path/to/project
```

Open `http://127.0.0.1:8765`. The UI projects existing Factory state; it has no separate database or scheduler. Its first launch downloads exact-version browser assets with SRI verification. Later launches can use the verified local assets offline. Resuming a real goal can consume provider usage.

See [Local control UI](docs/FACTORY_UI.md) for dependencies, security limits and the API.

## Evidence, not marketing claims

The retained TreeHash experiments recorded:

- v7 to v8: 75.1% fewer Factory-supplied context bytes, with 100% required-anchor recall.
- v8 to v9: 59.57% fewer worker reasoning tokens and 31.87% fewer worker output tokens, but 27.20% more worker input tokens.

The runs had different test-suite sizes and no comparable cached-input telemetry. They do **not** establish total-token savings, monetary savings or a universally optimal policy. Historical aggregate metrics remain available; raw historical prompts are deliberately not distributed.

See [Context and usage analysis](CONTEXT_EFFICIENCY.md), [Certification evidence](certification/README.md) and [Snapshot validation](docs/PORTFOLIO_VALIDATION.md).

## Repository map

| Path | Purpose |
| --- | --- |
| `tools/` | Orchestration, context, reasoning and UI facade |
| `ui/` | Static UI source and browser dependency lock |
| `schemas/`, root JSON files | Versioned contracts and policy |
| `factory_tests/` | Deterministic regression and invariant tests |
| `scripts/` | Maintenance, verification and optional live tools |
| `app/`, `web/`, `tests/` | MiniBoard reference application |
| `examples/minilinks/` | MiniLinks reference application |
| `plans/`, `fixtures/` | Consumed examples and calibration fixtures |
| `certification/` | Minimal historical machine-readable evidence |
| `docs/` | Architecture, application specifications and validation |

Generated `.agy-factory/`, UI vendor files, local databases and environment files are not source artifacts. Versioned v3–v9 tests are retained because they still exercise active invariants; their names are not release-support promises.

Start with the [documentation map](docs/README.md). See [Security](SECURITY.md) before execution or disclosure. No project license is specified in this repository; public visibility alone does not grant reuse rights.
