# Herdr Orchestrator — Toolchain Update Workflow

This repository keeps dependency inspection explicit and provider-safe. The supported maintenance surface is:

- Herdr CLI/server protocol and API schema.
- AGY, Droid, Codex, Claude Code, and OpenCode CLI metadata/auth state.
- Freebuff headless feasibility status.
- Python and Git.
- `harness_profiles.json` governance.
- `reasoning_policy.json` provenance/staleness.

The legacy external `herdr-board` integration is retired. Herdr Orchestrator UI reads Factory manifests directly and is the supported Kanban/status surface.

## Commands

```bash
# Read-only inspection. Provider metadata/auth probes are enabled.
./scripts/update-package.sh --check

# Strict provider-free inspection.
FACTORY_PROVIDER_PROBES=0 ./scripts/update-package.sh --check

# Refresh the committed lock from the real host.
./scripts/update-package.sh --apply
```

`--apply` intentionally refuses `FACTORY_PROVIDER_PROBES=0`: a lock refresh must not certify stale provider versions. The updater starts from `new_lock = dict(prev_lock)`, so unknown extension keys and historical metadata are preserved unless a dedicated migration removes them.

## Required gate before implementation work

Run:

```bash
FACTORY_PROVIDER_PROBES=0 ./scripts/update-package.sh --check
./scripts/verify.sh
```

Use provider probes only when the task actually requires live-provider verification. Never mutate credentials just to turn a diagnostic green.

## Lock semantics

`toolchain.lock.json` records the last certified host/toolchain snapshot. It is evidence, not a declaration that every historical component in the file is still an active runtime dependency. Active runtime dependencies are defined by current code, scripts, profiles, and this document.

A lock refresh records current Factory/Herdr/provider/Python/Git data and the current profile catalog. Reasoning-policy provenance checks remain authoritative for drift detection.

`doctor.sh` and `portable-smoke.sh` also check Herdr host prerequisites. They may fail on an offline-only machine even with provider probes disabled; see [Reproducibility](REPRODUCIBILITY.md).
