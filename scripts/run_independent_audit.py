#!/usr/bin/env python3
"""
scripts/run_independent_audit.py

Runs independent audit using agy-audit-high (claude-sonnet-4-6) to review
all FACTORY v8.0.0 changes for:
1. subtle prompt-leak regressions
2. anchor recall bypasses
3. stale context packet reuse
4. unchecked cache poisoning
5. race conditions in packet saving
6. unbounded string growth
7. silent truncation of required information
8. foreign host mutations
9. provenance laundering
10. missing or fake metrics
"""

import json
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

def main():
    print("================================================================================")
    print("AGY-Herdr Software Factory (v8.0.0) — Independent Audit (claude-sonnet-4-6)")
    print("================================================================================")

    # Read the core diffs
    diff_cmd = ["git", "diff", "aa27ecc..HEAD", "--", "tools/context.py", "tools/factory.py"]
    diff_text = subprocess.check_output(diff_cmd, cwd=str(REPO_ROOT)).decode("utf-8", errors="replace")

    # Persist the complete patch for reference
    patch_path = REPO_ROOT / "certification" / "v8" / "audit_diff.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(diff_text, encoding="utf-8")

    # tools/factory.py diff
    factory_diff = subprocess.check_output(
        ["git", "diff", "aa27ecc..HEAD", "--", "tools/factory.py"],
        cwd=str(REPO_ROOT)
    ).decode("utf-8", errors="replace")

    audit_prompt = f"""You are the Independent Code Auditor for AGY-Herdr Software Factory v8.0.0.
Perform a strict audit of the v8 context efficiency engine implementation across `tools/context.py` and the orchestrator modifications in `tools/factory.py`.
The complete git diff is saved at `certification/v8/audit_diff.patch` and the complete new context engine module is located at `tools/context.py`.

Audit specifically for:
1. subtle prompt-leak regressions (e.g. leaking secrets, environment tokens, or unnecessary internal variables into worker prompts)
2. anchor recall bypasses (can any required anchor be dropped or bypassed before worker dispatch?)
3. stale context packet reuse (can a worker run with outdated goal/plan/task definitions without re-compilation?)
4. unchecked cache poisoning (can bad prompt hash or state corrupt future compilations?)
5. race conditions in packet saving (are context packets and handoffs written atomically without corruption?)
6. unbounded string growth (are free-text handoff notes and history bounded to <= 4096 bytes?)
7. silent truncation of required information (does budget pruning ever silently drop required anchors, criteria, or validations?)
8. foreign host mutations (are foreign Herdr resources or host systems untouched?)
9. provenance laundering (is REAL, MOCK, or TRANSPORT_ONLY provenance strictly preserved without falsification?)
10. missing or fake metrics (are token counts honest/null when unavailable, and bytes measured canonically?)

=== ORCHESTRATOR DIFF (tools/factory.py v7 -> v8) ===
{factory_diff}

=== CONTEXT ENGINE (tools/context.py) ===
Read and inspect `tools/context.py` directly in the repository for the implementation of ContextCompiler, HandoffPacket, ContextPacket, redact_secrets, Anchor recall calculation, and DerivedRequirementAuditor.

Output ONLY a JSON object adhering to this schema:
{{
  "verdict": "ACCEPTED" or "REMEDIATION_REQUIRED",
  "findings": [
    {{
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "area": "implementation" | "tests" | "security" | "traceability",
      "evidence": "concrete file and line or logic reference",
      "recommendation": "suggested fix or remediation"
    }}
  ]
}}
"""

    cmd = [
        "agy",
        "-p", audit_prompt,
        "--model", "claude-sonnet-4-6",
        "--output-format", "json",
        "--dangerously-skip-permissions"
    ]

    print("Submitting audit request to claude-sonnet-4-6...")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        print(f"Error executing agy: {proc.stderr}")
        return 1

    out = proc.stdout.strip()
    print("Audit Response received.")
    
    # Extract JSON object
    import re

    def parse_llm_json(s: str) -> dict:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            raise ValueError(f"Failed to find JSON object in: {s[:200]}")
        content = m.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Sanitize invalid backslash escapes produced by LLM
            sanitized = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', content)
            return json.loads(sanitized)

    try:
        raw_obj = parse_llm_json(out)
        if "response" in raw_obj and isinstance(raw_obj["response"], str):
            resp_str = raw_obj["response"]
            try:
                report = parse_llm_json(resp_str)
            except Exception:
                report = raw_obj
        else:
            report = raw_obj
    except Exception as e:
        print(f"JSON decode error: {e}\nRaw output: {out}")
        return 1

    print("\n================================================================================")
    print(f"INDEPENDENT AUDIT VERDICT: {report.get('verdict')}")
    print("================================================================================")
    findings = report.get("findings", [])
    print(f"Total Findings: {len(findings)}")

    criticals = [f for f in findings if f.get("severity") == "CRITICAL"]
    majors = [f for f in findings if f.get("severity") == "MAJOR"]
    minors = [f for f in findings if f.get("severity") == "MINOR"]
    infos = [f for f in findings if f.get("severity") == "INFO"]

    print(f"  - Critical: {len(criticals)}")
    print(f"  - Major:    {len(majors)}")
    print(f"  - Minor:    {len(minors)}")
    print(f"  - Info:     {len(infos)}")
    print("--------------------------------------------------------------------------------")

    for idx, f in enumerate(findings, 1):
        print(f"[{idx}] {f.get('severity')} ({f.get('area')}): {f.get('evidence')}")
        print(f"    Recommendation: {f.get('recommendation')}")

    # Save audit report to artifacts
    out_path = REPO_ROOT / "certification" / "v8" / "independent-audit-report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)
    print(f"\nSaved audit report to: {out_path}")

    if criticals or majors:
        print("FAILED: Found CRITICAL or MAJOR findings that require remediation.")
        return 1

    print("SUCCESS: 0 Critical, 0 Major findings. Audit passed.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
