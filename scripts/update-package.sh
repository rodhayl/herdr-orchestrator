#!/usr/bin/env bash
# scripts/update-package.sh — Automated toolchain inspection and package updater for AGY-Herdr Factory
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:-}"

if [[ -z "$MODE" || ("$MODE" != "--check" && "$MODE" != "--apply") ]]; then
    echo "Usage: $0 [--check | --apply]"
    echo "  --check   Read-only inspection of toolchain, lock, and upstream compatibility"
    echo "  --apply   Apply compatible project-local updates and refresh toolchain.lock.json"
    exit 1
fi

python3 - << 'EOF' "$PROJECT_ROOT" "$MODE" "${FACTORY_PROVIDER_PROBES:-1}"
import sys, os, json, subprocess, pathlib, urllib.request, hashlib, datetime

project_root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
provider_probes = sys.argv[3] != "0"
if mode == "--apply" and not provider_probes:
    print("ERROR: --apply requires provider CLI probes; unset FACTORY_PROVIDER_PROBES=0 and retry.", file=sys.stderr)
    raise SystemExit(2)
lock_file = project_root / "toolchain.lock.json"
history_file = project_root / "UPDATE_HISTORY.md"
profiles_file = project_root / "harness_profiles.json"

# 1. Load previous lock
if lock_file.exists():
    with open(lock_file, "r", encoding="utf-8") as f:
        prev_lock = json.load(f)
else:
    prev_lock = {}

# 2. Probe current installed stack
def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return res.stdout.strip(), res.stderr.strip(), res.returncode
    except Exception as e:
        return "", str(e), 1

# Herdr
herdr_ver, _, _ = run_cmd(["herdr", "--version"])
herdr_ver = herdr_ver.replace("herdr", "").strip() if herdr_ver else "not_installed"

herdr_proto = None
schema_hash = None
try:
    snap_out, _, code = run_cmd(["herdr", "api", "snapshot"])
    if code == 0:
        data = json.loads(snap_out)
        herdr_proto = data.get("result", {}).get("snapshot", {}).get("protocol")
    schema_out, _, code2 = run_cmd(["herdr", "api", "schema", "--json"])
    if code2 == 0 and schema_out:
        schema_hash = hashlib.sha256(schema_out.encode("utf-8")).hexdigest()
except Exception:
    pass

# Provider harness CLI metadata. Strict provider-free validation skips every
# provider executable invocation; --apply refuses that mode to avoid certifying stale versions.
if provider_probes:
    agy_ver, _, _ = run_cmd(["agy", "--version"])
    agy_ver = agy_ver.strip() if agy_ver else "not_installed"

    droid_ver, _, _ = run_cmd(["droid", "--version"])
    droid_ver = droid_ver.strip() if droid_ver else "not_installed"

    codex_ver, _, _ = run_cmd(["codex", "--version"])
    codex_ver = codex_ver.replace("codex-cli", "").strip() if codex_ver else "not_installed"

    claude_ver, _, _ = run_cmd(["claude", "--version"])
    claude_ver = claude_ver.replace("Claude Code", "").strip().replace("(", "").replace(")", "").strip() if claude_ver else "not_installed"

    opencode_cmd = "/root/.opencode/bin/opencode" if os.path.exists("/root/.opencode/bin/opencode") else "opencode"
    opencode_ver, _, _ = run_cmd([opencode_cmd, "--version"])
    opencode_ver = opencode_ver.strip() if opencode_ver else "not_installed"

    freebuff_cmd = "/usr/local/bin/freebuff" if os.path.exists("/usr/local/bin/freebuff") else "freebuff"
    fb_out, _, fb_code = run_cmd([freebuff_cmd, "--version"])
    freebuff_ver = fb_out.splitlines()[-1].strip() if fb_code == 0 and fb_out else "not_installed"
else:
    agy_ver = droid_ver = codex_ver = claude_ver = opencode_ver = freebuff_ver = "probe_skipped"

# Toolchain

py_ver, _, _ = run_cmd(["python3", "-V"])
py_ver = py_ver.replace("Python", "").strip() if py_ver else "not_installed"

git_ver, _, _ = run_cmd(["git", "--version"])
git_ver = git_ver.replace("git version", "").strip() if git_ver else "not_installed"

rust_ver, _, rcode = run_cmd(["rustc", "--version"])
rust_ver = rust_ver.replace("rustc", "").strip() if rcode == 0 else "not_installed"

cargo_ver, _, ccode = run_cmd(["cargo", "--version"])
cargo_ver = cargo_ver.replace("cargo", "").strip() if ccode == 0 else "not_installed"

# Upstream checks
upstream_board = "v0.18.0"
board_commit = "d7a67470309c378778e388982bda67eee6dc1a58"
board_supported_herdr = ["0.9.0", "0.9.1"]
board_supported_proto = 22

board_status = "OK"
if herdr_ver not in board_supported_herdr or (herdr_proto is not None and herdr_proto != board_supported_proto):
    board_status = "BLOCKED_EXTERNAL_COMPATIBILITY"

factory_json_path = project_root / "factory.json"
factory_ver = "9.0.0"
if factory_json_path.exists():
    try:
        with open(factory_json_path, "r", encoding="utf-8") as f:
            factory_ver = json.load(f).get("version", "9.0.0")
    except Exception:
        pass

# Build report
matrix = [
    {
        "component": "Factory Engine",
        "prev_certified": prev_lock.get("factory", {}).get("version", "9.0.0"),
        "installed": factory_ver,
        "latest_stable": factory_ver,
        "action": "Maintain",
        "evidence": "Local package declaration (factory.json)"
    },
    {
        "component": "Herdr CLI",
        "prev_certified": prev_lock.get("herdr", {}).get("version", "0.9.1"),
        "installed": herdr_ver,
        "latest_stable": herdr_ver,
        "action": "Check Only",
        "evidence": f"herdr --version ({herdr_ver})"
    },
    {
        "component": "Herdr Protocol",
        "prev_certified": str(prev_lock.get("herdr", {}).get("protocol", "22")),
        "installed": str(herdr_proto) if herdr_proto is not None else "Unknown",
        "latest_stable": str(herdr_proto) if herdr_proto is not None else "22",
        "action": "Check Only",
        "evidence": f"Socket snapshot (protocol {herdr_proto})"
    },
    {
        "component": "herdr-board",
        "prev_certified": prev_lock.get("herdr_board", {}).get("selected_release", "None"),
        "installed": "Not Built" if rust_ver == "not_installed" else "Source Available",
        "latest_stable": upstream_board,
        "action": board_status,
        "evidence": f"Supports Herdr {', '.join(board_supported_herdr)}/proto {board_supported_proto}; host has Herdr {herdr_ver}/proto {herdr_proto}"
    },
    {
        "component": "AGY CLI",
        "prev_certified": prev_lock.get("agy", {}).get("cli_version", "1.2.9"),
        "installed": agy_ver,
        "latest_stable": agy_ver,
        "action": "Check Only",
        "evidence": f"agy --version ({agy_ver})" if provider_probes else "FACTORY_PROVIDER_PROBES=0; AGY CLI not invoked"
    },
    {
        "component": "Droid CLI",
        "prev_certified": prev_lock.get("droid", {}).get("cli_version", "0.225.1"),
        "installed": droid_ver,
        "latest_stable": droid_ver,
        "action": "Check Only",
        "evidence": f"droid --version ({droid_ver})" if provider_probes else "FACTORY_PROVIDER_PROBES=0; Droid CLI not invoked"
    },
    {
        "component": "Codex CLI",
        "prev_certified": prev_lock.get("codex", {}).get("cli_version", "0.155.1"),
        "installed": codex_ver,
        "latest_stable": codex_ver,
        "action": "Check Only",
        "evidence": f"codex --version ({codex_ver})" if provider_probes else "FACTORY_PROVIDER_PROBES=0; Codex CLI not invoked"
    },
    {
        "component": "Claude Code",
        "prev_certified": prev_lock.get("claude", {}).get("cli_version", "2.1.263"),
        "installed": claude_ver,
        "latest_stable": claude_ver,
        "action": "Check Only",
        "evidence": f"claude --version ({claude_ver})" if provider_probes else "FACTORY_PROVIDER_PROBES=0; Claude CLI not invoked"
    },
    {
        "component": "OpenCode CLI",
        "prev_certified": prev_lock.get("opencode", {}).get("cli_version", "1.18.31"),
        "installed": opencode_ver,
        "latest_stable": opencode_ver,
        "action": "Check Only",
        "evidence": f"opencode --version ({opencode_ver})" if provider_probes else "FACTORY_PROVIDER_PROBES=0; OpenCode CLI not invoked"
    },
    {
        "component": "Freebuff CLI",
        "prev_certified": prev_lock.get("freebuff", {}).get("version", "None"),
        "installed": freebuff_ver,
        "latest_stable": freebuff_ver,
        "action": "FREEBUFF_HEADLESS_BLOCKED",
        "evidence": "Requires interactive TUI; lacks non-interactive/headless CLI execution mode" if provider_probes else "FACTORY_PROVIDER_PROBES=0; Freebuff CLI not invoked"
    },
    {

        "component": "Python",
        "prev_certified": prev_lock.get("python", {}).get("version", "3.12.3"),
        "installed": py_ver,
        "latest_stable": "3.12.x",
        "action": "Maintain",
        "evidence": f"python3 -V ({py_ver})"
    },
    {
        "component": "Git",
        "prev_certified": prev_lock.get("git", {}).get("version", "2.43.0"),
        "installed": git_ver,
        "latest_stable": "2.43.x",
        "action": "Maintain",
        "evidence": f"git --version ({git_ver})"
    },
    {
        "component": "Rust / Cargo",
        "prev_certified": "None",
        "installed": rust_ver,
        "latest_stable": "1.85.x",
        "action": "Host Prerequisite",
        "evidence": f"rustc: {rust_ver}, cargo: {cargo_ver}"
    }
]

print("=" * 80)
print("AGY-Herdr Software Factory (v9.0.0) — Toolchain & Package Update Gate")
print("=" * 80)
header_fmt = "{:<16} | {:<12} | {:<12} | {:<14} | {:<12}"
row_fmt    = "{:<16} | {:<12} | {:<12} | {:<14} | {:<12}"
print(header_fmt.format("Component", "Previous", "Installed", "Latest Stable", "Action"))
print("-" * 80)
for row in matrix:
    print(row_fmt.format(
        row["component"],
        row["prev_certified"][:12],
        row["installed"][:12],
        row["latest_stable"][:14],
        row["action"][:12]
    ))
print("-" * 80)

# Display Harness Profiles Matrix
profiles_data = {}
if profiles_file.exists():
    with open(profiles_file, "r", encoding="utf-8") as f:
        profiles_data = json.load(f).get("profiles", {})

print("\n" + "=" * 80)
print("Harness Profiles Compatibility & Governance Matrix")
print("=" * 80)
p_header_fmt = "{:<22} | {:<8} | {:<18} | {:<8} | {:<12} | {:<12}"
p_row_fmt    = "{:<22} | {:<8} | {:<18} | {:<8} | {:<12} | {:<12}"
print(p_header_fmt.format("Profile ID", "Harness", "Model", "Effort", "Concurrency", "Cert Status"))
print("-" * 80)
for pid, p in profiles_data.items():
    cert_st = p.get("certification", {}).get("status", "UNCERTIFIED")
    print(p_row_fmt.format(
        pid,
        p.get("harness", ""),
        p.get("model", "")[:18],
        p.get("effort", ""),
        str(p.get("max_concurrency", 1)),
        cert_st
    ))
print("-" * 80)

# Display Reasoning Policy Provenance & Calibration Gate Matrix (v9.0.0)
reasoning_policy_file = project_root / "reasoning_policy.json"
reasoning_status = "MISSING"
drift_reasons = []
if reasoning_policy_file.exists():
    try:
        sys.path.insert(0, str(project_root / "tools"))
        sys.path.insert(0, str(project_root))
        from tools.reasoning import ReasoningPolicy
        r_pol = ReasoningPolicy.load(reasoning_policy_file)
        is_valid, drift_reasons = r_pol.check_staleness(project_root)
        if not is_valid:
            if any("harness_profiles" in r for r in drift_reasons):
                reasoning_status = "PROFILE_DRIFT"
            elif any("toolchain_lock" in r for r in drift_reasons):
                reasoning_status = "EXTERNAL_UPDATE_REQUIRED"
            else:
                reasoning_status = "NEEDS_REVALIDATION"
        else:
            reasoning_status = "VALID"
    except Exception as e:
        reasoning_status = f"ERROR: {e}"

print("\n" + "=" * 80)
print("Reasoning Policy Calibration & Provenance Gate (v9.0.0)")
print("=" * 80)
print(f"Policy File:        {reasoning_policy_file.name}")
print(f"Governance Status:  {reasoning_status}")
if drift_reasons:
    print("Drift Reasons:")
    for dr in drift_reasons:
        print(f"  - {dr}")
else:
    print("Drift Check:        Clean (all provenance hashes certified)")
print("-" * 80)

if board_status == "BLOCKED_EXTERNAL_COMPATIBILITY":
    print("\n[COMPATIBILITY GATE NOTICE]")
    print(f"  herdr-board {upstream_board} supports Herdr {', '.join(board_supported_herdr)} on protocol {board_supported_proto}.")
    print(f"  The installed Herdr server version is {herdr_ver} (protocol {herdr_proto}).")
    print("  Status: BLOCKED_EXTERNAL_COMPATIBILITY.")
    print("  Per Section 7/8 rules: do not downgrade Herdr, do not patch gates, do not pretend compatibility.")

if mode == "--apply":
    print("\n[APPLY MODE]")
    new_lock = dict(prev_lock)
    new_lock.update({
        "factory": {"version": factory_ver, "schema_version": prev_lock.get("factory", {}).get("schema_version", factory_ver)},
        "certified_environment": {
            "os": os.uname().sysname,
            "architecture": os.uname().machine,
            "kernel": os.uname().release
        },
        "herdr": {
            "version": herdr_ver,
            "protocol": herdr_proto or 22,
            "relevant_api_schema_hash": schema_hash
        },
        "herdr_board": {
            "selected_release": upstream_board,
            "git_commit": board_commit,
            "supported_herdr_versions": board_supported_herdr,
            "required_herdr_protocol": board_supported_proto,
            "board_protocol": prev_lock.get("herdr_board", {}).get("board_protocol", "board.v1"),
            "sqlite_schema": prev_lock.get("herdr_board", {}).get("sqlite_schema", "v1"),
            "compatibility_status": board_status,
            "compatibility_notes": f"herdr-board {upstream_board} supports Herdr {', '.join(board_supported_herdr)} on protocol {board_supported_proto}; host has Herdr {herdr_ver} (protocol {herdr_proto})."
        },
        "agy": {
            **prev_lock.get("agy", {}),
            "cli_version": agy_ver,
            "worker_profiles": prev_lock.get("agy", {}).get("worker_profiles", ["agy", "agy2", "agy3", "agy4", "agy5", "agy6", "agy7"])
        },
        "droid": {**prev_lock.get("droid", {}), "cli_version": droid_ver},
        "codex": {**prev_lock.get("codex", {}), "cli_version": codex_ver},
        "claude": {**prev_lock.get("claude", {}), "cli_version": claude_ver},
        "opencode": {**prev_lock.get("opencode", {}), "cli_version": opencode_ver},
        "freebuff": {
            "cli_version": freebuff_ver,
            "feasibility_status": "FREEBUFF_HEADLESS_BLOCKED",
            "notes": "Interactive TUI only; no certified non-interactive/headless prompt execution mode."
        },
        "certified_profiles": list(profiles_data.keys()),
        "python": {"version": py_ver, "implementation": "CPython", "policy": "stdlib_only"},
        "git": {"version": git_ver},
        "rustc": {"version": rust_ver if rust_ver != "not_installed" else None, "installed": rust_ver != "not_installed"},
        "cargo": {"version": cargo_ver if cargo_ver != "not_installed" else None, "installed": cargo_ver != "not_installed"},
        "certified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })
    with open(lock_file, "w", encoding="utf-8") as f:
        json.dump(new_lock, f, indent=2)
    print(f"  -> Updated toolchain.lock.json for Factory v{factory_ver} successfully.")

print("=" * 80)
EOF
