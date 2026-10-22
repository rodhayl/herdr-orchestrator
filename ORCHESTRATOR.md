# Herdr Orchestrator — Integration Guide (v9.0.0)

## Contract

An external brain/orchestrator supplies a goal or an explicit DAG. The Factory owns execution truth.

```text
external brain
    |
    v
GoalSpec / DAG
    |
    v
Project policy
    |
    v
planning + deterministic gates + review
    |
    v
ContextCompiler
    |
    v
deterministic router
    |
    v
ReasoningPolicy
    |
    v
WorkerAdapter
    |
    v
isolated worktree
    |
    v
validation + integration + audit
```

The planner/model may propose work. It does not own:

- scheduler state;
- routing truth;
- retries;
- Git integration;
- path validation;
- completion;
- certification.

## Recommended external-project workflow

```bash
python3 tools/factory.py --project-root /path/to/project project init --name "MyProject"
python3 tools/factory.py --project-root /path/to/project project doctor
python3 tools/factory.py --project-root /path/to/project goal plan --goal-file /path/to/GOAL.md
python3 tools/factory.py --project-root /path/to/project goal run --goal-file /path/to/GOAL.md --real-only
python3 tools/factory.py --project-root /path/to/project goal status --goal-id <goal-id> --json
python3 tools/factory.py --project-root /path/to/project goal report --goal-id <goal-id>
```

Interrupted work should be resumed from durable state:

```bash
python3 tools/factory.py --project-root /path/to/project goal resume --goal-id <goal-id>
```

## Low-level DAG mode

Retained declarative plans remain supported:

```bash
python3 tools/factory.py validate-plan plans/<plan>.json
python3 tools/factory.py run plans/<plan>.json
python3 tools/factory.py resume <run-id>
```

## Context contract

v8 introduced deterministic role-specific context packets.

A worker receives only the information required for its task:

- task objective;
- relevant acceptance criteria;
- allowed/protected paths;
- dependency handoffs;
- relevant file references;
- validation commands;
- output contract.

It does not inherit unrelated worker conversations by default.

Dispatch fails closed if required-anchor recall is below 100%.

## Reasoning contract

v9 adds deterministic effort selection after model-family/profile routing.

Experimental defaults are evidence-backed starting points, not universal optima. The Factory may perform at most one same-family effort escalation by default when a normalized **reasoning-quality** failure justifies it.

No automatic effort escalation is allowed for:

- auth/provider/infrastructure failures;
- context compilation/anchor/budget failures;
- Git/worktree conflicts;
- path/scope guardrail failures.

In particular, `PATH_VALIDATION_FAILED` fails closed.

## Execution provenance

Every attempt is classified as:

- `REAL`
- `MOCK`
- `TRANSPORT_ONLY`
- `UNKNOWN`

A run containing mock execution cannot be promoted into real-provider certification.

## Safety boundaries

1. Foreign Herdr resources are never mutated.
2. Every attempt owns a dedicated task worktree/branch.
3. Target projects must be clean before real-provider execution.
4. Path allowlists and symlink checks are commit/integration guardrails, not an OS sandbox.
5. Runtime artifacts belong under the target project's `.agy-factory/`.
6. No global installation/auth mutation is required for normal operation.
7. Deterministic tests are preferred over quota-consuming real-provider re-certification.

## Provider-call discipline

For routine provider-free maintenance, use:

```bash
FACTORY_PROVIDER_PROBES=0 ./scripts/update-package.sh --check
./scripts/verify.sh
```

`verify.sh` forces strict provider-probe suppression for its deterministic matrix. Run standalone diagnostics without that environment variable only when live read-only provider metadata/auth discovery is intentionally wanted.

Only use `verify-real.sh`, real calibration, or a model-backed audit when new real-provider evidence is explicitly needed.

## Machine-readable integration surface

Prefer stable JSON/CLI outputs rather than scraping terminal UI:

- status/report JSON;
- profile/route/reasoning explain commands;
- run/goal manifests;
- context packet/evidence metadata;
- certification bundles.

## Documentation

- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md)
- [HARNESS_PROFILES.md](HARNESS_PROFILES.md)
- [CONTEXT_EFFICIENCY.md](CONTEXT_EFFICIENCY.md)
- [REPRODUCIBILITY.md](REPRODUCIBILITY.md)

`doctor.sh` and `portable-smoke.sh` also check Herdr host prerequisites. They may fail on an offline-only machine even with provider probes disabled; see [Reproducibility](REPRODUCIBILITY.md).

Pass `--project-root` explicitly for an external target. Without it, the Factory CLI uses its own source repository, not the shell current directory.
