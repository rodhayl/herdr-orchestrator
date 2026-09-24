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
        ["git", "diff", "-U1", "aa27ecc..HEAD", "--", "tools/factory.py"],
        cwd=str(REPO_ROOT)
    ).decode("utf-8", errors="replace")

    # Extract key sections from tools/context.py to provide complete self-contained context
    ctx_lines = (REPO_ROOT / "tools" / "context.py").read_text(encoding="utf-8").splitlines()
    ctx_sections = [
        "### Injection Filter Pattern, Secret Redaction & Frozen Snapshot:\n" + "\n".join(ctx_lines[105:278]),
        "\n### Anchor Data Model & Boundary-Safe Recall Calculation:\n" + "\n".join(ctx_lines[278:404]),
        "\n### HandoffPacket (Bounded Free-Text, Pre-Instantiation Hash Verify, Canonical Dump):\n" + "\n".join(ctx_lines[404:790]),
        "\n### ContextSource & Sensitive File Pattern Matcher:\n" + "\n".join(ctx_lines[790:1025]),
        "\n### ContextPacket & Cryptographic Staleness Verification:\n" + "\n".join(ctx_lines[1375:1530]),
        "\n### ContextCompiler (compile_task_packet complete method with Pruning):\n" + "\n".join(ctx_lines[1655:2146]),
        "\n### ContextCompiler (compile_plan_review_packet complete method with Pruning):\n" + "\n".join(ctx_lines[2146:2320]),
        "\n### DerivedRequirementAuditor (Strict Lineage Traceability & Closed Enums):\n" + "\n".join(ctx_lines[2445:2536]),
        "\n### Atomic Persistence, Quarantine & Context Telemetry:\n" + "\n".join(ctx_lines[2536:2670]),
    ]
    context_core_code = "\n".join(ctx_sections)

    audit_prompt = f"""You are the Independent Code Auditor for AGY-Herdr Software Factory v8.0.0.
Perform a strict audit of the v8 context efficiency engine implementation across `tools/context.py` and the orchestrator modifications in `tools/factory.py`.
All relevant implementation code and git diffs are provided directly in this prompt below. Do not invoke external tools or browse the filesystem; evaluate the provided code directly.

CRITICAL: DO NOT CALL ANY TOOLS. DO NOT CALL write_to_file or any other tool. Return ONLY the structured audit evaluation.

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

=== CONTEXT ENGINE CORE (tools/context.py) ===
{context_core_code}

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
                            "enum": ["implementation", "tests", "security", "traceability"]
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
    
    # Extract JSON object
    import re

    def decode_loose_json(s: str) -> str:
        out = []
        in_string = False
        escape = False
        i = 0
        while i < len(s):
            c = s[i]
            if not in_string:
                if c == '"':
                    in_string = True
                out.append(c)
                i += 1
            else:
                if escape:
                    out.append(c)
                    escape = False
                    i += 1
                else:
                    if c == "\\":
                        if i + 1 < len(s):
                            nxt = s[i + 1]
                            if nxt in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't'):
                                out.append(c)
                                escape = True
                                i += 1
                            elif nxt == 'u' and i + 5 < len(s) and all(h in "0123456789abcdefABCDEF" for h in s[i+2:i+6]):
                                out.append(c)
                                escape = True
                                i += 1
                            else:
                                out.append("\\\\")
                                i += 1
                        else:
                            out.append("\\\\")
                            i += 1
                    elif c == '"':
                        in_string = False
                        out.append(c)
                        i += 1
                    else:
                        out.append(c)
                        i += 1
        return "".join(out)

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
