#!/usr/bin/env python3
"""Effort Calibration Suite & Downward Search Runner (Factory v9.0.0).

Executes bounded, repeatable calibration across Fixtures A through F
to discover lowest sufficient reasoning effort satisfying all quality gates.
Separates calibration telemetry with execution_purpose='CALIBRATION'.
"""
import copy
import datetime
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CERT_DIR = PROJECT_ROOT / "certification" / "v9"
CERT_DIR.mkdir(parents=True, exist_ok=True)
RUNS_LOG = CERT_DIR / "calibration-runs.jsonl"


def log_calibration_call(record: dict):
    """Appends calibration call record to calibration-runs.jsonl."""
    record["execution_purpose"] = "CALIBRATION"
    record["recorded_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(RUNS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_agy_call(
    worker_cmd: str,
    prompt: str,
    model: str,
    effort: str,
    cwd: pathlib.Path,
    schema: dict = None,
    timeout: int = 120
) -> dict:
    """Invokes AGY CLI worker with specific model and effort, capturing exact provider telemetry."""
    cmd = [
        worker_cmd,
        "--mode", "accept-edits",
        "--dangerously-skip-permissions",
        "--add-dir", str(cwd),
        "-p", prompt,
        "--model", model,
        "--effort", effort,
        "--output-format", "json"
    ]
    if schema:
        cmd.extend(["--json-schema", json.dumps(schema)])

    start_t = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        duration = round(time.time() - start_t, 3)
        raw_out = proc.stdout
        exit_code = proc.returncode

        data = {}
        try:
            data = json.loads(raw_out.strip())
        except Exception:
            for line in reversed(raw_out.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        break
                    except Exception:
                        pass

        usage = data.get("usage", {})
        return {
            "exit_code": exit_code,
            "timed_out": False,
            "duration_seconds": duration,
            "data": data,
            "usage": {
                "input_tokens": usage.get("input_tokens"),
                "cached_input_tokens": usage.get("cache_read_tokens") or usage.get("cached_input_tokens"),
                "reasoning_tokens": usage.get("thinking_tokens") or usage.get("reasoning_tokens"),
                "output_tokens": usage.get("output_tokens")
            },
            "raw_output": raw_out[:1000]
        }
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_t, 3)
        return {
            "exit_code": -1,
            "timed_out": True,
            "duration_seconds": duration,
            "data": {},
            "usage": {},
            "raw_output": "TIMED_OUT"
        }


def calibrate_fixture_a(efforts=("low", "medium", "high")) -> dict:
    """Calibrate Fixture A — Routine Task."""
    results = {}
    fix_dir = PROJECT_ROOT / "fixtures" / "calibration" / "fixture_a"
    spec = json.loads((fix_dir / "task_spec.json").read_text(encoding="utf-8"))

    for effort in efforts:
        with tempfile.TemporaryDirectory() as td:
            work_dir = pathlib.Path(td)
            for f in ["record_formatter.py", "test_formatter.py"]:
                shutil.copy(fix_dir / f, work_dir / f)

            prompt = spec["prompt"]
            res = run_agy_call("agy3", prompt, "gemini-3.8-flash", effort, work_dir, timeout=90)

            # Test deterministic validation
            test_proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", ".", "-v"], cwd=str(work_dir), capture_output=True, text=True)
            passed = (test_proc.returncode == 0) and ("to_canonical_json" in (work_dir / "record_formatter.py").read_text())

            rec = {
                "fixture": "fixture_a",
                "role": "worker",
                "execution_class": "routine",
                "task_type": "backend",
                "model": "gemini-3.8-flash",
                "effort": effort,
                "passed": passed,
                "duration_seconds": res["duration_seconds"],
                "usage": res["usage"],
                "exit_code": res["exit_code"],
                "test_returncode": test_proc.returncode
            }
            log_calibration_call(rec)
            results[effort] = rec
            print(f"[Fixture A] effort={effort} passed={passed} reasoning_tokens={res['usage'].get('reasoning_tokens')} duration={res['duration_seconds']}s")
    return results


def calibrate_fixture_b(efforts=("medium", "high", "low")) -> dict:
    """Calibrate Fixture B — Standard Implementation."""
    results = {}
    fix_dir = PROJECT_ROOT / "fixtures" / "calibration" / "fixture_b"
    spec = json.loads((fix_dir / "task_spec.json").read_text(encoding="utf-8"))

    for effort in efforts:
        with tempfile.TemporaryDirectory() as td:
            work_dir = pathlib.Path(td)
            for f in ["models.py", "store.py", "cli.py", "test_event_store.py"]:
                shutil.copy(fix_dir / f, work_dir / f)

            prompt = spec["prompt"]
            res = run_agy_call("agy3", prompt, "gemini-3.8-flash", effort, work_dir, timeout=120)

            # Test deterministic validation
            test_proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", ".", "-v"], cwd=str(work_dir), capture_output=True, text=True)
            passed = (test_proc.returncode == 0) and ("start_time" in (work_dir / "store.py").read_text())

            rec = {
                "fixture": "fixture_b",
                "role": "worker",
                "execution_class": "standard",
                "task_type": "backend",
                "model": "gemini-3.8-flash",
                "effort": effort,
                "passed": passed,
                "duration_seconds": res["duration_seconds"],
                "usage": res["usage"],
                "exit_code": res["exit_code"],
                "test_returncode": test_proc.returncode
            }
            log_calibration_call(rec)
            results[effort] = rec
            print(f"[Fixture B] effort={effort} passed={passed} reasoning_tokens={res['usage'].get('reasoning_tokens')} duration={res['duration_seconds']}s")
    return results


def calibrate_fixture_c(efforts=("high", "medium")) -> dict:
    """Calibrate Fixture C — Deep Debugging."""
    results = {}
    fix_dir = PROJECT_ROOT / "fixtures" / "calibration" / "fixture_c"
    spec = json.loads((fix_dir / "task_spec.json").read_text(encoding="utf-8"))

    for effort in efforts:
        with tempfile.TemporaryDirectory() as td:
            work_dir = pathlib.Path(td)
            for f in ["transactional_cache.py", "hash_chain.py", "test_deep_debug.py"]:
                shutil.copy(fix_dir / f, work_dir / f)

            prompt = spec["prompt"]
            res = run_agy_call("agy3", prompt, "gemini-3.8-flash", effort, work_dir, timeout=120)

            # Test deterministic validation
            test_proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", ".", "-v"], cwd=str(work_dir), capture_output=True, text=True)
            passed = (test_proc.returncode == 0)

            rec = {
                "fixture": "fixture_c",
                "role": "worker",
                "execution_class": "deep",
                "task_type": "debugging",
                "model": "gemini-3.8-flash",
                "effort": effort,
                "passed": passed,
                "duration_seconds": res["duration_seconds"],
                "usage": res["usage"],
                "exit_code": res["exit_code"],
                "test_returncode": test_proc.returncode
            }
            log_calibration_call(rec)
            results[effort] = rec
            print(f"[Fixture C] effort={effort} passed={passed} reasoning_tokens={res['usage'].get('reasoning_tokens')} duration={res['duration_seconds']}s")
    return results


def calibrate_fixture_d(efforts=("medium", "high")) -> dict:
    """Calibrate Fixture D — Planner."""
    results = {}
    fix_dir = PROJECT_ROOT / "fixtures" / "calibration" / "fixture_d"
    goal_input = json.loads((fix_dir / "goal_input.json").read_text(encoding="utf-8"))

    prompt = f"""You are the Project Autopilot Plan Compiler.
Convert the following Goal Specification into an OrchestrationPlan JSON DAG:
=== GOAL SPECIFICATION ===
{json.dumps(goal_input, indent=2)}

Requirements:
1. Every requirement R1, R2, R3, R4, R5 MUST be satisfied by at least one task.
2. Valid acyclic DAG dependencies.
3. Every task must declare at least one validation command in 'validations'.
4. Output JSON adhering to: {{"plan_id": "string", "tasks": [{{"task_id": "string", "name": "string", "task_type": "string", "satisfies": ["string"], "dependencies": ["string"], "validations": [["string"]]}}]}}
"""
    for effort in efforts:
        with tempfile.TemporaryDirectory() as td:
            work_dir = pathlib.Path(td)
            res = run_agy_call("agy2", prompt, "gemini-3.8-flash", effort, work_dir, timeout=90)
            data = res.get("data", {})
            plan = {}
            if "tasks" in data:
                plan = data
            elif "response" in data:
                m = re.search(r"\{[\s\S]*\}", data["response"])
                if m:
                    try:
                        plan = json.loads(m.group(0))
                    except Exception:
                        pass

            tasks = plan.get("tasks", [])
            covered_reqs = set()
            for t in tasks:
                covered_reqs.update(t.get("satisfies", []))

            passed = (
                len(tasks) >= 2
                and set(["R1", "R2", "R3", "R4", "R5"]).issubset(covered_reqs)
                and all(len(t.get("validations", [])) > 0 for t in tasks)
            )

            rec = {
                "fixture": "fixture_d",
                "role": "planner",
                "execution_class": "standard",
                "task_type": "specification",
                "model": "gemini-3.8-flash",
                "effort": effort,
                "passed": passed,
                "task_count": len(tasks),
                "covered_requirements": list(covered_reqs),
                "duration_seconds": res["duration_seconds"],
                "usage": res["usage"],
                "exit_code": res["exit_code"]
            }
            log_calibration_call(rec)
            results[effort] = rec
            print(f"[Fixture D] effort={effort} passed={passed} tasks={len(tasks)} reqs={len(covered_reqs)}/5 reasoning_tokens={res['usage'].get('reasoning_tokens')}")
    return results


def calibrate_fixture_e(efforts=("medium", "high")) -> dict:
    """Calibrate Fixture E — Plan Reviewer with Seeded Defects."""
    results = {}
    fix_dir = PROJECT_ROOT / "fixtures" / "calibration" / "fixture_e"
    plan = json.loads((fix_dir / "plan_with_seeded_defects.json").read_text(encoding="utf-8"))
    truth = json.loads((fix_dir / "seeded_findings_ground_truth.json").read_text(encoding="utf-8"))

    prompt = f"""Review the following OrchestrationPlan against deterministic quality invariants.
Goal requirements: R1, R2, R3, R4, R5.
=== PROPOSED PLAN ===
{json.dumps(plan, indent=2)}

Audit for:
1. Missing requirements (R1-R5).
2. Inadequate or empty validation commands.
3. Unsafe allowed paths (e.g. root '/').
4. Derived requirements without parent provenance.
5. Unsupported capabilities.

Return JSON in format:
{{"verdict": "REVISE", "findings": [{{"id": "string", "severity": "CRITICAL|MAJOR|MINOR", "description": "string"}}]}}
"""
    for effort in efforts:
        with tempfile.TemporaryDirectory() as td:
            work_dir = pathlib.Path(td)
            res = run_agy_call("agy2", prompt, "gemini-3.8-flash", effort, work_dir, timeout=90)
            data = res.get("data", {})
            findings_text = json.dumps(data).lower()

            recalled_defects = []
            for defect in truth["seeded_defects"]:
                patterns = defect["match_patterns"]
                if any(p.lower() in findings_text for p in patterns):
                    recalled_defects.append(defect["id"])

            critical_major_truth = [d["id"] for d in truth["seeded_defects"] if d["severity"] in ("CRITICAL", "MAJOR")]
            recalled_cm = [d for d in critical_major_truth if d in recalled_defects]
            recall_rate = len(recalled_cm) / len(critical_major_truth)
            passed = (recall_rate == 1.0)

            rec = {
                "fixture": "fixture_e",
                "role": "plan_reviewer",
                "execution_class": "standard",
                "task_type": "review",
                "model": "gemini-3.8-flash",
                "effort": effort,
                "passed": passed,
                "recalled_defects": recalled_defects,
                "total_critical_major": len(critical_major_truth),
                "recall_rate": recall_rate,
                "duration_seconds": res["duration_seconds"],
                "usage": res["usage"],
                "exit_code": res["exit_code"]
            }
            log_calibration_call(rec)
            results[effort] = rec
            print(f"[Fixture E] effort={effort} passed={passed} recall={len(recalled_cm)}/{len(critical_major_truth)} ({recall_rate*100:.1f}%) reasoning_tokens={res['usage'].get('reasoning_tokens')}")
    return results


def calibrate_fixture_f(efforts=("high", "medium")) -> dict:
    """Calibrate Fixture F — Final Audit with Seeded Defects."""
    results = {}
    fix_dir = PROJECT_ROOT / "fixtures" / "calibration" / "fixture_f"
    truth = json.loads((fix_dir / "seeded_audit_ground_truth.json").read_text(encoding="utf-8"))

    prompt = f"""Perform an authoritative final code and security audit on the file_server implementation.
Authoritative requirements:
- R1: Serve files strictly inside DATA_DIR without path traversal
- R2: Safely list directory contents returning empty list if empty
- R3: Mandatory Authorization token header validation
- R4: Comprehensive test coverage

=== CODE UNDER AUDIT (server.py) ===
{(fix_dir / 'server.py').read_text()}

=== TESTS (test_server.py) ===
{(fix_dir / 'test_server.py').read_text()}

Output JSON findings with format:
{{"verdict": "REJECTED", "findings": [{{"id": "string", "severity": "CRITICAL|MAJOR|MINOR", "category": "string", "description": "string"}}]}}
"""
    for effort in efforts:
        with tempfile.TemporaryDirectory() as td:
            work_dir = pathlib.Path(td)
            # Use agy-audit worker (agy7)
            res = run_agy_call("agy7", prompt, "gemini-3.8-flash", effort, work_dir, timeout=90)
            data = res.get("data", {})
            findings_text = json.dumps(data).lower()

            recalled_defects = []
            for defect in truth["seeded_defects"]:
                patterns = defect["match_patterns"]
                if any(p.lower() in findings_text for p in patterns):
                    recalled_defects.append(defect["id"])

            critical_major_truth = [d["id"] for d in truth["seeded_defects"] if d["severity"] in ("CRITICAL", "MAJOR")]
            recalled_cm = [d for d in critical_major_truth if d in recalled_defects]
            recall_rate = len(recalled_cm) / len(critical_major_truth)
            passed = (recall_rate == 1.0)

            rec = {
                "fixture": "fixture_f",
                "role": "final_auditor",
                "execution_class": "deep",
                "task_type": "audit",
                "model": "gemini-3.8-flash",
                "effort": effort,
                "passed": passed,
                "recalled_defects": recalled_defects,
                "total_critical_major": len(critical_major_truth),
                "recall_rate": recall_rate,
                "duration_seconds": res["duration_seconds"],
                "usage": res["usage"],
                "exit_code": res["exit_code"]
            }
            log_calibration_call(rec)
            results[effort] = rec
            print(f"[Fixture F] effort={effort} passed={passed} recall={len(recalled_cm)}/{len(critical_major_truth)} ({recall_rate*100:.1f}%) reasoning_tokens={res['usage'].get('reasoning_tokens')}")
    return results


def main():
    print("=" * 80)
    print("Starting Bounded Effort Calibration Pass (Fixtures A - F)")
    print("=" * 80)

    # 1. Routine task: test low, medium
    print("\n--- [Fixture A] Worker Routine Calibration ---")
    res_a = calibrate_fixture_a(efforts=("low", "medium"))

    # 2. Standard implementation: test medium, high
    print("\n--- [Fixture B] Worker Standard Calibration ---")
    res_b = calibrate_fixture_b(efforts=("medium", "high"))

    # 3. Deep debugging: test high, medium
    print("\n--- [Fixture C] Worker Deep Calibration ---")
    res_c = calibrate_fixture_c(efforts=("high", "medium"))

    # 4. Planner: test medium, high
    print("\n--- [Fixture D] Planner Calibration ---")
    res_d = calibrate_fixture_d(efforts=("medium", "high"))

    # 5. Plan Reviewer: test medium, high
    print("\n--- [Fixture E] Plan Reviewer Calibration ---")
    res_e = calibrate_fixture_e(efforts=("medium", "high"))

    # 6. Final Auditor: test high, medium
    print("\n--- [Fixture F] Final Auditor Calibration ---")
    res_f = calibrate_fixture_f(efforts=("high", "medium"))

    print("\n" + "=" * 80)
    print("Calibration Pass Complete. Summary of Decisions:")
    print("=" * 80)
    print(f"Fixture A (Routine Worker): Lowest Sufficient = {'low' if res_a.get('low', {}).get('passed') else 'medium'}")
    print(f"Fixture B (Standard Worker): Lowest Sufficient = {'medium' if res_b.get('medium', {}).get('passed') else 'high'}")
    print(f"Fixture C (Deep Worker): Lowest Sufficient = {'medium' if res_c.get('medium', {}).get('passed') else 'high'}")
    print(f"Fixture D (Planner): Lowest Sufficient = {'medium' if res_d.get('medium', {}).get('passed') else 'high'}")
    print(f"Fixture E (Reviewer): Lowest Sufficient = {'medium' if res_e.get('medium', {}).get('passed') else 'high'}")
    print(f"Fixture F (Auditor): Lowest Sufficient = {'medium' if res_f.get('medium', {}).get('passed') else 'high'}")


if __name__ == "__main__":
    main()
