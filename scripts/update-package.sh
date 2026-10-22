#!/usr/bin/env bash
# scripts/update-package.sh — Read-only toolchain inspection and lock refresh for active Factory dependencies
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-}"

if [[ -z "$MODE" || ("$MODE" != "--check" && "$MODE" != "--apply") ]]; then
    echo "Usage: $0 [--check | --apply]"
    exit 1
fi

python3 - << 'EOF' "$PROJECT_ROOT" "$MODE" "${FACTORY_PROVIDER_PROBES:-1}"
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys

project_root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
provider_probes = sys.argv[3] != "0"
if mode == "--apply" and not provider_probes:
    print("ERROR: --apply requires provider CLI probes; unset FACTORY_PROVIDER_PROBES=0 and retry.", file=sys.stderr)
    raise SystemExit(2)

lock_file = project_root / "toolchain.lock.json"
profiles_file = project_root / "harness_profiles.json"
prev_lock = json.loads(lock_file.read_text(encoding="utf-8")) if lock_file.exists() else {}

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return res.stdout.strip(), res.stderr.strip(), res.returncode
    except Exception as exc:
        return "", str(exc), 1

herdr_raw, _, _ = run_cmd(["herdr", "--version"])
herdr_ver = herdr_raw.replace("herdr", "").strip() if herdr_raw else "not_installed"
herdr_proto = None
schema_hash = None
snap_out, _, snap_code = run_cmd(["herdr", "api", "snapshot"])
if snap_code == 0:
    try:
        herdr_proto = json.loads(snap_out).get("result", {}).get("snapshot", {}).get("protocol")
    except Exception:
        pass
schema_out, _, schema_code = run_cmd(["herdr", "api", "schema", "--json"])
if schema_code == 0 and schema_out:
    schema_hash = hashlib.sha256(schema_out.encode("utf-8")).hexdigest()

if provider_probes:
    commands = {
        "agy": ["agy", "--version"],
        "droid": ["droid", "--version"],
        "codex": ["codex", "--version"],
        "claude": ["claude", "--version"],
        "opencode": ["opencode", "--version"],
        "freebuff": ["freebuff", "--version"],
    }
    versions = {}
    for key, command in commands.items():
        out, _, code = run_cmd(command)
        versions[key] = out.splitlines()[-1].strip() if code == 0 and out else "not_installed"
else:
    versions = {k: "probe_skipped" for k in ("agy", "droid", "codex", "claude", "opencode", "freebuff")}

py_raw, _, _ = run_cmd(["python3", "-V"])
git_raw, _, _ = run_cmd(["git", "--version"])
py_ver = py_raw.replace("Python", "").strip() if py_raw else "not_installed"
git_ver = git_raw.replace("git version", "").strip() if git_raw else "not_installed"
factory_ver = "9.0.0"
factory_file = project_root / "factory.json"
if factory_file.exists():
    factory_ver = json.loads(factory_file.read_text(encoding="utf-8")).get("version", factory_ver)

profiles = {}
if profiles_file.exists():
    profiles = json.loads(profiles_file.read_text(encoding="utf-8")).get("profiles", {})

matrix = [
    ("Factory Engine", prev_lock.get("factory", {}).get("version", factory_ver), factory_ver, "Maintain"),
    ("Herdr CLI", prev_lock.get("herdr", {}).get("version", "unknown"), herdr_ver, "Check Only"),
    ("AGY CLI", prev_lock.get("agy", {}).get("cli_version", "unknown"), versions["agy"], "Check Only"),
    ("Droid CLI", prev_lock.get("droid", {}).get("cli_version", "unknown"), versions["droid"], "Check Only"),
    ("Codex CLI", prev_lock.get("codex", {}).get("cli_version", "unknown"), versions["codex"], "Check Only"),
    ("Claude Code", prev_lock.get("claude", {}).get("cli_version", "unknown"), versions["claude"], "Check Only"),
    ("OpenCode CLI", prev_lock.get("opencode", {}).get("cli_version", "unknown"), versions["opencode"], "Check Only"),
    ("Freebuff CLI", prev_lock.get("freebuff", {}).get("cli_version", "unknown"), versions["freebuff"], "FREEBUFF_HEADLESS_BLOCKED"),
    ("Python", prev_lock.get("python", {}).get("version", "unknown"), py_ver, "Maintain"),
    ("Git", prev_lock.get("git", {}).get("version", "unknown"), git_ver, "Maintain"),
]

print("=" * 80)
print("Herdr Orchestrator (v9.0.0) — Toolchain & Package Update Gate")
print("=" * 80)
for component, previous, installed, action in matrix:
    evidence = f"{component} CLI not invoked" if not provider_probes and component in {"AGY CLI","Droid CLI","Codex CLI","Claude Code","OpenCode CLI","Freebuff CLI"} else ""
    print(f"{component:<16} | {str(previous)[:14]:<14} | {str(installed)[:14]:<14} | {action:<24} {evidence}")

print("\nHarness Profiles Compatibility & Governance Matrix")
for pid, profile in profiles.items():
    cert = profile.get("certification", {}).get("status", "UNCERTIFIED")
    print(f"{pid:<24} | {profile.get('harness',''):<8} | {profile.get('model','')[:20]:<20} | {profile.get('effort',''):<8} | {cert}")

if not provider_probes:
    print("\nProvider CLI probes skipped; AGY CLI not invoked and other provider CLIs not invoked.")

reasoning_file = project_root / "reasoning_policy.json"
if reasoning_file.exists():
    try:
        sys.path.insert(0, str(project_root))
        from tools.reasoning import ReasoningPolicy
        valid, reasons = ReasoningPolicy.load(reasoning_file).check_staleness(project_root)
        print(f"Reasoning Policy Governance: {'VALID' if valid else 'STALE'}")
        for reason in reasons:
            print(f"  - {reason}")
    except Exception as exc:
        print(f"Reasoning Policy Governance: ERROR ({exc})")

if mode == "--apply":
    new_lock = dict(prev_lock)
    new_lock.update({
        "factory": {"version": factory_ver, "schema_version": prev_lock.get("factory", {}).get("schema_version", factory_ver)},
        "certified_environment": {"os": os.uname().sysname, "architecture": os.uname().machine, "kernel": os.uname().release},
        "herdr": {"version": herdr_ver, "protocol": herdr_proto or 22, "relevant_api_schema_hash": schema_hash},
        "agy": {**prev_lock.get("agy", {}), "cli_version": versions["agy"]},
        "droid": {**prev_lock.get("droid", {}), "cli_version": versions["droid"]},
        "codex": {**prev_lock.get("codex", {}), "cli_version": versions["codex"]},
        "claude": {**prev_lock.get("claude", {}), "cli_version": versions["claude"]},
        "opencode": {**prev_lock.get("opencode", {}), "cli_version": versions["opencode"]},
        "freebuff": {"cli_version": versions["freebuff"], "feasibility_status": "FREEBUFF_HEADLESS_BLOCKED", "notes": "Interactive TUI only; no certified non-interactive/headless prompt execution mode."},
        "certified_profiles": list(profiles.keys()),
        "python": {"version": py_ver, "implementation": "CPython", "policy": "stdlib_only"},
        "git": {"version": git_ver},
        "certified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    lock_file.write_text(json.dumps(new_lock, indent=2) + "\n", encoding="utf-8")
    print(f"Updated toolchain.lock.json for Factory v{factory_ver} successfully.")
EOF
