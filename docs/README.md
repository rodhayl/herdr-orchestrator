# Documentation map

This directory separates **current operational truth**, **application contracts**, **machine-readable evidence**, and **historical narrative records**.

## Start here

- [CURRENT_STATE.md](CURRENT_STATE.md) — concise current v9 status and evidence boundaries.
- [../README.md](../README.md) — project overview and quick start.
- [../ORCHESTRATOR.md](../ORCHESTRATOR.md) — integration contract for external brains/orchestrators.
- [../REPRODUCIBILITY.md](../REPRODUCIBILITY.md) — provider-free bootstrap and verification workflow.
- [FACTORY_UI.md](FACTORY_UI.md) — local browser control surface, API, security and dependency contract.

## Current operational documentation

These remain at stable root paths because scripts/agents already consume them:

- [../AGENTS.md](../AGENTS.md)
- [../UPDATE_PACKAGE.md](../UPDATE_PACKAGE.md)
- [../UPDATE_HISTORY.md](../UPDATE_HISTORY.md)
- [../HARNESS_PROFILES.md](../HARNESS_PROFILES.md)
- [../CONTEXT_EFFICIENCY.md](../CONTEXT_EFFICIENCY.md)

Machine-readable policy is authoritative when prose and configuration differ:

- [../factory.json](../factory.json)
- [../harness_profiles.json](../harness_profiles.json)
- [../context_policy.json](../context_policy.json)
- [../reasoning_policy.json](../reasoning_policy.json)
- [../toolchain.lock.json](../toolchain.lock.json)
- [../schemas/](../schemas/)

## Application specifications

These are product contracts, not Factory-version documentation:

- [SPECIFICATION.md](SPECIFICATION.md) — MiniBoard product/API specification.
- [../examples/minilinks/SPEC.md](../examples/minilinks/SPEC.md) — MiniLinks product/API specification.

They intentionally remain in their established paths because retained plans and test/evidence artifacts reference them.

## Certification evidence

See [../certification/README.md](../certification/README.md).

Machine-readable evidence stays under `certification/`. Do not move current evidence merely to make the docs tree prettier.

## Historical documentation

See [archive/README.md](archive/README.md).

Historical certification narratives are preserved for provenance but are not current operational guidance.

## Documentation maintenance rules

1. Use relative repository links; avoid host-specific `file:///root/...` links in current docs.
2. State the Factory version separately from schema/config versions.
3. Distinguish implemented/deterministically tested adapters from real-provider certification.
4. Do not infer total-token or monetary-cost savings from partial provider telemetry.
5. Archive superseded narrative documents instead of deleting engineering history.
6. Keep paths consumed by scripts/configuration stable unless the consuming code is changed in the same commit.
