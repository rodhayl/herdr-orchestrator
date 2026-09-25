#!/usr/bin/env python3
"""
scripts/run_v9_independent_audit.py

Runs independent audit using agy-audit-high (claude-sonnet-4-6) to review
all FACTORY v9.0.0 Reasoning Efficiency changes for:
1. Deterministic model-specific reasoning policy and lowest-sufficient-effort calibration.
2. Bounded escalation (max 1 ladder step within model family for quality failures only; infrastructure failures fail closed).
3. Telemetry isolation with 15 provider fields and strict execution_purpose partitioning. No synthetic costs or fabricated token counts.
4. Failpoints around escalation lifecycle (after_effort_selected, after_low_attempt_failed, before_escalated_dispatch, after_escalated_result, before_escalated_commit).
5. Preservation and strict freezing of v8 context efficiency engine and schemas.
6. Error handling, bounds checking, race condition protections, and non-reentrant locks.
"""

import json
import os
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

def main():
    print("================================================================================")
    print("AGY-Herdr Software Factory (v9.0.0) — Independent Audit (claude-sonnet-4-6)")
    print("================================================================================")

    # Base commit for v8.0.0
    base_commit = "403ba92"

    # Read the core diffs
    diff_cmd = [
        "git", "diff", f"{base_commit}..HEAD", "--",
        "tools/reasoning.py",
        "tools/factory.py",
        "tools/context.py",
        "reasoning_policy.json"
    ]
    diff_text = subprocess.check_output(diff_cmd, cwd=str(REPO_ROOT)).decode("utf-8", errors="replace")

    # Persist the complete patch for reference
    patch_path = REPO_ROOT / "certification" / "v9" / "audit_diff.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(diff_text, encoding="utf-8")
    print(f"Audit patch persisted to: {patch_path}")

    # Complete reasoning policy content
    policy_text = (REPO_ROOT / "reasoning_policy.json").read_text(encoding="utf-8")

    audit_prompt = f"""You are the Independent Code Auditor for AGY-Herdr Software Factory v9.0.0 (Reasoning Efficiency).
Perform a strict, rigorous independent audit of the v9 reasoning efficiency engine implementation, policy, and orchestrator modifications.
All relevant implementation code, reasoning policy, and git diffs are provided directly in this prompt below. Do not invoke external tools or browse the filesystem; evaluate the provided code directly.

CRITICAL: DO NOT CALL ANY TOOLS. Return ONLY the structured audit evaluation.

Audit specifically for:
1. Deterministic Model-Specific Reasoning Policy:
   - Does `reasoning_policy.json` correctly map models, roles, and execution classes to calibrated efforts without hardcoding or uncalibrated defaults?
   - Is lowest-sufficient-effort calibration maintained across Fixtures A–F (Routine, Standard, Deep, Planner, Reviewer, Final Auditor)?
2. Bounded Escalation Logic:
   - Is escalation strictly bounded to at most 1 ladder step within the same model family?
   - Are escalations allowed ONLY for quality failures (test failure, path violation, verification error)?
   - Do infrastructure failures (timeouts, harness crashes, memory exhaustion, auth errors) fail closed without wasting reasoning tokens?
3. Telemetry Isolation & Non-Fabrication:
   - Are the 15 provider telemetry fields captured truthfully without synthetic token fabrication or hallucinated cost metrics?
   - Is `execution_purpose` partitioning (`PRODUCTION`, `CALIBRATION`, `CERTIFICATION`, `DETERMINISTIC_TEST`) strictly isolated across storage and metrics summarization?
4. Escalation Lifecycle Failpoints:
   - Are failpoints cleanly wired and tested around the escalation lifecycle: `after_effort_selected`, `after_low_attempt_failed`, `before_escalated_dispatch`, `after_escalated_result`, `before_escalated_commit`?
5. Architecture Freezing & Backwards Compatibility:
   - Are v8 context compiler, anchor recall, secret redaction, and bounded handoffs completely frozen and preserved without regression?
6. Robustness & Security:
   - Are there any race conditions, lock order violations, foreign host mutations, prompt injection leaks, or silent truncations?

=== REASONING POLICY (reasoning_policy.json) ===
{policy_text}

=== GIT DIFF (v8.0.0 -> v9.0.0) ===
{diff_text}

Output ONLY a JSON object adhering to this schema:
{{
  "verdict": "ACCEPTED" or "REMEDIATION_REQUIRED",
  "findings": [
    {{
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "area": "implementation" | "tests" | "security" | "traceability" | "reasoning_efficiency",
      "evidence": "concrete file and line or logic reference",
      "recommendation": "suggested fix or remediation"
    }}
  ]
}}
"""

    audit_schema = {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["ACCEPTED", "REMEDIATION_REQUIRED"]
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["CRITICAL", "MAJOR", "MINOR", "INFO"]
                        },
                        "area": {
                            "type": "string",
                            "enum": ["implementation", "tests", "security", "traceability", "reasoning_efficiency"]
                        },
                        "evidence": {"type": "string"},
                        "recommendation": {"type": "string"}
                    },
                    "required": ["severity", "area", "evidence", "recommendation"]
                }
            }
        },
        "required": ["verdict", "findings"]
    }

    cmd = [
        "agy",
        "--model", "claude-sonnet-4-6",
        "--output-format", "json",
        "--json-schema", json.dumps(audit_schema),
        "--dangerously-skip-permissions"
    ]

    print("Submitting audit request to claude-sonnet-4-6...")
    proc = subprocess.run(cmd, input=audit_prompt, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        print(f"Error executing agy: {proc.stderr}")
        return 1

    out = proc.stdout.strip()
    print("Audit Response received.")

    def decode_loose_json(s: str) -> str:
        out_chars = []
        in_string = False
        escape = False
        i = 0
        while i < len(s):
            c = s[i]
            if not in_string:
                if c == '"':
                    in_string = True
                out_chars.append(c)
                i += 1
            else:
                if escape:
                    out_chars.append(c)
                    escape = False
                    i += 1
                else:
                    if c == "\\":
                        if i + 1 < len(s):
                            nxt = s[i + 1]
                            if nxt in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't'):
                                out_chars.append(c)
                                escape = True
                                i += 1
                            elif nxt == 'u' and i + 5 < len(s) and all(h in "0123456789abcdefABCDEF" for h in s[i+2:i+6]):
                                out_chars.append(c)
                                escape = True
                                i += 1
                            else:
                                out_chars.append("\\\\")
                                i += 1
                        else:
                            out_chars.append("\\\\")
                            i += 1
                    elif c == '"':
                        in_string = False
                        out_chars.append(c)
                        i += 1
                    else:
                        out_chars.append(c)
                        i += 1
        return "".join(out_chars)

    def parse_llm_json(s: str) -> dict:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            raise ValueError(f"Failed to find JSON object in: {s[:200]}")
        content = m.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            cleaned = decode_loose_json(content)
            return json.loads(cleaned, strict=False)

    try:
        raw_obj = parse_llm_json(out)
        if "structured_output" in raw_obj and isinstance(raw_obj["structured_output"], dict):
            report = raw_obj["structured_output"]
        elif "response" in raw_obj and isinstance(raw_obj["response"], str):
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
    out_path = REPO_ROOT / "certification" / "v9" / "independent-audit.json"
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
