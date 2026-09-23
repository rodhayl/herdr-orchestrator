# AGY-Herdr Software Factory — Permanent Package Update & Maintenance Playbook

Authoritative operational procedure governing software version discovery, toolchain locking, compatibility resolution, and dependency updates for the AGY-Herdr Software Factory.

---

## 1. Update Trigger

Package version inspection and compatibility checking occurs under either of two conditions:

1. **Mandatory Iteration Gate**: At the beginning of **every** future substantive implementation iteration, before modifying factory code or application features.
2. **Explicit User Request**: Whenever requested to update dependencies, refresh the stack, check versions, migrate to newer Herdr/AGY/Droid, or update `herdr-board`.

Every coding agent must execute this workflow before feature work:
```bash
# 1. Inspect operational instructions
cat UPDATE_PACKAGE.md

# 2. Inspect the previously certified lock
cat toolchain.lock.json

# 3. Run the read-only package update check
./scripts/update-package.sh --check

# 4. Review the generated version and compatibility matrix
# 5. Resolve compatible project-local updates
# 6. Only then proceed to feature development
```

---

## 2. Sources of Truth & Precedence

Version numbers, CLI flags, supported models, and protocols must **never** be inferred from model memory or external blog posts. The authoritative precedence is:

```
Level 1: Live Installed CLI / Socket API
         (Probed directly from the host system environment)
    +
Level 2: Official Upstream Documentation & Repository Declarations
         (Authoritative specifications from upstream maintainers)
    +
Level 3: Official Stable Releases / Tags / Changelogs
         (Excluding preview, alpha, beta, rc, and nightly branches)
    +
Level 4: Repository Compatibility Declarations & Prior Certification
         (toolchain.lock.json and UPDATE_HISTORY.md)
```

If an upstream source claims compatibility but the live installed CLI fails execution, live runtime verification is authoritative.

---

## 3. Previous Certified Stack (`toolchain.lock.json`)

Before evaluating or proposing any updates, the agent **must** read and preserve the existing certified values from:
`toolchain.lock.json`

This file records the exact toolchain and dependencies that passed the last full certification suite:
- Factory engine version
- Operating system and architecture
- Herdr binary version, socket protocol, and API schema hash
- herdr-board release version, immutable git commit, required Herdr version, and protocol
- AGY CLI version, worker profiles (`agy` through `agy7`), certified model, and effort
- Droid CLI version, certified model, reasoning effort, and autonomy
- Python, Git, rustc, and cargo toolchain versions
- Exact ISO-8601 certification timestamp

**Rule**: Never overwrite `toolchain.lock.json` before comparison and verification are complete.

---

## 4. Current Installed Stack Probing

The update system queries installed binaries and running servers dynamically:
- **Herdr**: `herdr --version`, socket ping/snapshot (`herdr api snapshot` -> `.result.snapshot.version`, `.result.snapshot.protocol`), and API schema hash (`herdr api schema --json | sha256sum`).
- **AGY**: `agy --version`, available models (`agy models`).
- **Droid**: `droid --version`, `droid exec --help`, model catalog inspection, authentication check (`FACTORY_API_KEY`).
- **herdr-board**: Local binary (`.tools/bin/board --version` or system `board --version`).
- **Toolchain**: `python3 -V`, `git --version`, `rustc --version`, `cargo --version`.
- **System**: Host OS, architecture (`uname -s`, `uname -m`).

---

## 5. Latest Stable Upstream Stack Querying

The update system queries official upstream repositories for the newest **stable** releases:
- Stable release tags matching semantic versioning (`vX.Y.Z`).
- Strict exclusion: `preview`, `alpha`, `beta`, `rc`, `nightly`, git `HEAD`, and PR branches.
- Offline behavior: If network access is unavailable, the update check reports `OFFLINE` and uses the locked certified stack without fabricating version numbers.

---

## 6. Compatibility Matrix Schema

The output of `./scripts/update-package.sh --check` produces an explicit compatibility matrix:

| Component | Previous Certified | Installed Now | Latest Stable | Compatible Target | Action | Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Factory Engine** | `4.0.0` | `4.0.0` | `4.0.0` | `4.0.0` | None | Local repo `factory.json` |
| **Herdr CLI** | `0.9.1` | `0.9.1` | `0.9.1` | `0.9.1` | Check Only | `herdr --version` |
| **Herdr Protocol**| `22` | `22` | `22` | `22` | Check Only | `herdr api snapshot` |
| **herdr-board** | `v0.17.0` | None | `v0.17.0` | None | Blocked | `v0.17.0` requires Herdr `0.9.0` |
| **AGY CLI** | `1.2.9` | `1.2.9` | `1.2.9` | `1.2.9` | Check Only | `agy --version` |
| **AGY Model** | `gemini-3.8-flash-high` | `gemini-3.8-flash-high` | `gemini-3.8-flash-high` | `gemini-3.8-flash-high` | Retain | `agy models` |
| **Droid CLI** | `0.224.1` | `0.224.1` | `0.224.1` | `0.224.1` | Check Only | `droid --version` |
| **Droid Model** | `qwen3.8-max` (xhigh) | Unauthenticated | Catalog | Requires Auth | Adapter Ready | Missing `FACTORY_API_KEY` |
| **Python** | `3.12.3` | `3.12.3` | `3.12.3` | `3.12.3` | Retain | `python3 -V` (stdlib only) |
| **Git** | `2.43.0` | `2.43.0` | `2.43.0` | `2.43.0` | Retain | `git --version` |
| **Rust / Cargo** | None | None | `1.85.0` | None | Host Pre-req | `rustc` not installed |

---

## 7. Deterministic Update Policy

### A. User / Host-Managed External Prerequisites
External tools are **never** auto-updated or mutated by the Factory:
- `herdr`, `agy`, `droid`, `python3`, `git`, `rustc`, `cargo`.
- Host packages (`apt`, `brew`, `pacman`), global symlinks, global config files.
- If an external tool has changed since previous certification:
  - If compatible: revalidate, run regressions, update lock upon passing.
  - If incompatible: report `EXTERNAL_UPDATE_REQUIRED` or `EXTERNAL_INCOMPATIBILITY`. Halt modification.

### B. Project-Local Dependencies (`.tools/`, `herdr-board`)
Project-local dependencies may be updated via `./scripts/update-package.sh --apply` if and only if:
1. A newer official stable release exists.
2. The release **explicitly supports** the installed external toolchain (e.g. Herdr version & protocol).
3. All deterministic test suites pass with the new version.

### C. Herdr / herdr-board Pinned Compatibility Invariant
Compatibility strictly takes precedence over recency:
```
detected installed Herdr version & protocol
    -> inspect all stable herdr-board releases
    -> select the NEWEST STABLE release that EXPLICITLY supports that Herdr version & protocol
```
- If no stable release officially supports the installed Herdr:
  - **Do NOT** downgrade Herdr.
  - **Do NOT** patch upstream compatibility gates.
  - **Do NOT** use a preview or unreleased branch.
  - **Do NOT** pretend compatibility.
  - Continue non-board factory work and mark board status as:
    `BLOCKED_EXTERNAL_COMPATIBILITY`

---

## 8. Validation Gate

Before any update is committed to `toolchain.lock.json`, the entire verification harness must pass:
1. `python3 -m unittest discover -s factory_tests -v`
2. `python3 -m unittest discover -s tests -v`
3. `python3 scripts/smoke_test.py`
4. `python3 -m unittest discover -s examples/minilinks/tests -v`
5. `python3 examples/minilinks/scripts/smoke_test.py`
6. `scripts/verify.sh`
7. `scripts/portable-smoke.sh`

---

## 9. Rollback Procedure

If an update fails validation:
1. Discard modified project-local dependency files (`git checkout -- .tools/`).
2. Restore previous `toolchain.lock.json` from git HEAD.
3. Record the failure reason in `UPDATE_HISTORY.md` under a `FAILED_UPDATE` entry.
4. Leave the certified working stack intact.

---

## 10. Audit History (`UPDATE_HISTORY.md`)

Every execution of `./scripts/update-package.sh --apply` or significant compatibility evaluation appends a structured record to `UPDATE_HISTORY.md`. No entries may be deleted.
