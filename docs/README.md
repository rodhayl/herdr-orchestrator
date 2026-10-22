# Documentation map

## Start here

- [Project overview](../README.md)
- [Current source state and evidence boundaries](CURRENT_STATE.md)
- [Offline and host-dependent reproducibility](../REPRODUCIBILITY.md)
- [Snapshot validation](PORTFOLIO_VALIDATION.md)
- [Security and licensing boundaries](../SECURITY.md)

## Operational contracts

- [Agent guidance](../AGENTS.md)
- [Orchestrator integration](../ORCHESTRATOR.md)
- [Harness profiles](../HARNESS_PROFILES.md)
- [Context and usage evidence](../CONTEXT_EFFICIENCY.md)
- [Toolchain update workflow](../UPDATE_PACKAGE.md)
- [Concise engineering history](../UPDATE_HISTORY.md)
- [Herdr Orchestrator UI](FACTORY_UI.md)

Root operational documents retain stable paths for their consumers. Machine-readable contracts live in [factory.json](../factory.json), [harness_profiles.json](../harness_profiles.json), [context_policy.json](../context_policy.json), [reasoning_policy.json](../reasoning_policy.json), [toolchain.lock.json](../toolchain.lock.json) and [schemas/](../schemas/).

## Reference applications

- [MiniBoard specification](SPECIFICATION.md)
- [MiniLinks specification](../examples/minilinks/SPEC.md)

The specifications, plans, tests and intentionally faulty calibration fixtures have distinct purposes and are not obsolete merely because they predate Factory v9.

## Historical evidence

[Certification records](../certification/README.md) retain useful machine-readable provenance. Superseded narrative reports are summarized in the engineering history. Historical observations must not be presented as fresh host/provider validation or production certification. Changes to prose must preserve measurement values, evidence classes and known limitations.
