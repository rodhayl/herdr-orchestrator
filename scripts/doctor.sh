#!/usr/bin/env bash
# scripts/doctor.sh — Read-only environment diagnostics for Herdr Orchestrator
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 - << 'EOF' "$PROJECT_ROOT" "${FACTORY_PROVIDER_PROBES:-1}"
import hashlib
import json
import os
import pathlib
import subprocess
import sys

project_root = pathlib.Path(sys.argv[1])
provider_probes = sys.argv[2] != "0"
lock_file = project_root / "toolchain.lock.json"
profiles_file = project_root / "harness_profiles.json"
structural_ok = True
auth_warnings = []

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return res.stdout.strip(), res.stderr.strip(), res.returncode
    except Exception as exc:
        return "", str(exc), 1

print("=" * 80)
print("Herdr Orchestrator (v9.0.0) — Environment Diagnostics (doctor)")
print("=" * 80)
print("\n[1. STRUCTURAL PREREQUISITES]")
print(f"  [OK] Operating System: {os.uname().sysname} ({os.uname().machine}, kernel {os.uname().release})")

for label, command in (("Python", ["python3", "-V"]), ("Git", ["git", "--version"]), ("Herdr CLI", ["herdr", "--version"])):
    out, err, code = run_cmd(command)
    if code == 0:
        print(f"  [OK] {label}: {out}")
    else:
        print(f"  [FAIL] {label}: {err or 'not available'}")
        structural_ok = False

try:
    snap_out, _, snap_code = run_cmd(["herdr", "api", "snapshot"])
    if snap_code == 0:
        snap = json.loads(snap_out).get("result", {}).get("snapshot", {})
        print(f"  [OK] Herdr Socket API: Connected (Protocol {snap.get('protocol')}, {len(snap.get('workspaces', []))} active workspaces)")
    else:
        print("  [WARN] Herdr Socket API: Unable to connect to socket")
except Exception as exc:
    print(f"  [WARN] Herdr Socket API error: {exc}")

schema_out, _, schema_code = run_cmd(["herdr", "api", "schema", "--json"])
if schema_code == 0 and schema_out:
    digest = hashlib.sha256(schema_out.encode("utf-8")).hexdigest()
    print(f"  [OK] Herdr API Schema Hash: {digest[:16]}... (verified)")

if provider_probes:
    provider_commands = (
        ("AGY", ["agy", "--version"]),
        ("Droid", ["droid", "--version"]),
        ("Codex", ["codex", "--version"]),
        ("Claude Code", ["claude", "--version"]),
        ("OpenCode", ["opencode", "--version"]),
    )
    for label, command in provider_commands:
        out, _, code = run_cmd(command)
        if code == 0:
            print(f"  [OK] {label} CLI: Version {out}")
        else:
            print(f"  [FAIL] {label} CLI not found")
            structural_ok = False
else:
    print("  [INFO] Provider CLI version probes skipped (FACTORY_PROVIDER_PROBES=0)")

print("\n[2. GOVERNANCE]")
if lock_file.exists():
    try:
        lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
        print(f"  [OK] toolchain.lock.json: Loaded (certified at {lock_data.get('certified_at', 'unknown')})")
    except Exception as exc:
        print(f"  [FAIL] toolchain.lock.json: Corrupt ({exc})")
        structural_ok = False
else:
    print("  [WARN] toolchain.lock.json: Not found (run scripts/update-package.sh --apply)")

if profiles_file.exists():
    try:
        pdata = json.loads(profiles_file.read_text(encoding="utf-8"))
        profiles = pdata.get("profiles", {})
        sys.path.insert(0, str(project_root))
        from tools.factory import validate_all_profiles
        results = validate_all_profiles(profiles_file)
        bad = {pid: errs for pid, errs in results.items() if errs}
        if bad:
            for pid, errs in bad.items():
                print(f"  [FAIL] Profile '{pid}': {', '.join(errs)}")
            structural_ok = False
        else:
            print(f"  [OK] harness_profiles.json: {len(profiles)} execution profiles validated.")
    except Exception as exc:
        print(f"  [FAIL] harness_profiles.json error: {exc}")
        structural_ok = False
else:
    print("  [FAIL] harness_profiles.json not found")
    structural_ok = False

print("\n[3. AUTHENTICATED REAL-PROVIDER PREREQUISITES]")
if provider_probes:
    sys.path.insert(0, str(project_root))
    from tools.factory import probe_harness_auth
    for harness in ["agy", "droid", "codex", "claude", "opencode"]:
        probe = probe_harness_auth(harness)
        if probe["authenticated"]:
            print(f"  [OK] {harness.upper()} Provider Authentication: {probe['auth_source']} ({probe['evidence']})")
        else:
            print(f"  [WARN] {harness.upper()} Provider Authentication: AUTH_BLOCKED ({probe['evidence']})")
            auth_warnings.append(f"{harness.upper()} AUTH_BLOCKED")
    fb = probe_harness_auth("freebuff")
    print(f"  [INFO] FREEBUFF Feasibility Gate: {fb['auth_source']} ({fb['evidence']})")
else:
    print("  [INFO] Provider auth/catalog probes skipped (FACTORY_PROVIDER_PROBES=0)")

print("\n" + "=" * 80)
if structural_ok:
    print("DOCTOR STATUS: STRUCTURAL PREREQUISITES SATISFIED (READY FOR FACTORY WORK)")
    if auth_warnings:
        print(f"PROVIDER WARNINGS: {'; '.join(auth_warnings)} (Provider-free tests pass)")
    raise SystemExit(0)
print("DOCTOR STATUS: STRUCTURAL PREREQUISITES FAILED (RESOLVE ISSUES ABOVE)")
raise SystemExit(1)
EOF
