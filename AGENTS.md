# AGENTS.md — Guidance for Autonomous Coding Agents

Welcome to the AGY-Herdr Software Factory repository.

## Operational Rule: Mandatory Package Update Gate

Before undertaking any substantive implementation or feature development work in this repository:

1. Read [UPDATE_PACKAGE.md](file:///root/agy-herdr-factory-poc/UPDATE_PACKAGE.md).
2. Inspect the current certified lock in [toolchain.lock.json](file:///root/agy-herdr-factory-poc/toolchain.lock.json).
3. Execute the package update check:
   ```bash
   ./scripts/update-package.sh --check
   ```
4. Review the generated version and compatibility report.
5. Resolve compatible project-local updates if applicable.

`toolchain.lock.json` records the last certified stack; never assume those versions are still current. Always verify live installed tools and upstream compatibility before modifying the orchestration core.
