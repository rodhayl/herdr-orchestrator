# AGENTS.md — Autonomous Agent Guidance

This repository contains **Herdr Orchestrator v9.0.0**. Public presentation uses that name; internal `factory` identifiers and AGY provider names are compatibility contracts, not branding targets.

## Mandatory preflight

Before substantive implementation work:

1. Read [UPDATE_PACKAGE.md](UPDATE_PACKAGE.md).
2. Inspect [toolchain.lock.json](toolchain.lock.json).
3. Read the current-state summary in [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md).
4. Run the strict provider-free compatibility check:
   ```bash
   FACTORY_PROVIDER_PROBES=0 ./scripts/update-package.sh --check
   ```
5. For code changes, run the relevant deterministic tests before broad regression.

## Provider-call discipline

Real model/provider calls are **not** part of routine repository maintenance.

Default to:

- deterministic unit/integration tests;
- fake/test harnesses;
- provider-free `./scripts/verify.sh`;
- `./scripts/portable-smoke.sh` when portability matters and its live Herdr host prerequisites are available. It is not an offline-only gate.

Use `./scripts/verify-real.sh`, calibration scripts, AGY audits, or other real-provider certification only when the task explicitly requires new real-provider evidence. Do not spend provider quota merely to reconfirm an already-certified invariant.

## Test and execution discipline

- Do not poll or query status repeatedly while background test suites or commands are executing.
- Always wait for tests and processes to finish completely before inspecting results or proceeding.

## Safety invariants

- Never mutate unrelated Herdr resources.
- Never change authentication as part of a test.
- Never install global dependencies or use `sudo`.
- Treat `REAL`, `MOCK`, `TRANSPORT_ONLY`, and `UNKNOWN` as distinct evidence classes.
- A path/scope guardrail failure such as `PATH_VALIDATION_FAILED` fails closed and must not trigger higher reasoning effort.
- Preserve the distinction between Factory version, schema versions, configuration versions, and certification status.

## Documentation

The documentation map is [docs/README.md](docs/README.md).

Current operational documents remain at stable paths in the repository root because scripts and agents consume them. Keep concise historical context in `UPDATE_HISTORY.md` and useful machine-readable evidence under `certification/`. Do not duplicate superseded release reports or retain raw provider transcripts merely as documentation.
