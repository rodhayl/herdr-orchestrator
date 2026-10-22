#!/usr/bin/env python3
"""
factory_tests/test_v8_randomized_stress.py

Executes >= 100 seeded randomized synthetic DAG stress tests to verify:
1. Strict property invariants (anchor recall == 1.0, budget adherence).
2. Deterministic idempotency (same input -> bit-for-bit identical packet).
3. Redundancy chunk analysis validity (0.0 <= redundancy_ratio <= 1.0).
4. No cycle corruption and robust graceful handling across varying topologies.
"""

import copy
import random
import unittest
import pathlib

from tools.context import (
    ContextCompiler,
    ContextPolicy,
    DEFAULT_CONTEXT_POLICY,
    FilesystemGitContextSource,
    calculate_rendered_anchor_recall,
    calculate_context_redundancy,
    DerivedRequirementAuditor,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestV8RandomizedStress(unittest.TestCase):
    def setUp(self):
        self.policy = ContextPolicy(DEFAULT_CONTEXT_POLICY)
        self.source = FilesystemGitContextSource(REPO_ROOT)
        self.compiler = ContextCompiler(self.policy, self.source)

    def test_seeded_synthetic_dag_stress_100_runs(self):
        """Generates 100 randomized synthetic DAG configurations and verifies context invariants."""
        num_iterations = 100
        rng = random.Random(42)  # Seeded for reproducible deterministic verification

        for i in range(num_iterations):
            # Generate random requirements (3 to 8 requirements)
            num_reqs = rng.randint(3, 8)
            req_ids = [f"R{r}" for r in range(1, num_reqs + 1)]
            criteria = [
                {
                    "id": rid,
                    "provenance": "USER_EXPLICIT",
                    "description": f"Random requirement {rid} with payload {rng.randbytes(8).hex()}",
                }
                for rid in req_ids
            ]

            # Optionally add 1-2 derived requirements
            if rng.random() > 0.4:
                parent = rng.choice(req_ids)
                did = f"D{len(criteria)+1}"
                criteria.append({
                    "id": did,
                    "provenance": "DERIVED",
                    "description": f"Derived criterion for {parent}",
                    "derived_from": [parent],
                    "rationale": f"Architectural necessity derived from {parent}",
                    "created_by": "goal_structurer",
                })
                req_ids.append(did)

            goal_spec = {
                "goal_id": f"goal-stress-{i:03d}",
                "title": f"Random Goal Spec #{i}",
                "acceptance_criteria": criteria,
            }

            # Generate random topological DAG (2 to 5 tasks)
            num_tasks = rng.randint(2, 5)
            tasks = []
            for t_idx in range(num_tasks):
                task_id = f"task_{t_idx:02d}"
                # Dependencies can only point backwards to ensure DAG is acyclic
                deps = [f"task_{p:02d}" for p in range(t_idx) if rng.random() > 0.6]
                assigned_reqs = rng.sample(req_ids, k=rng.randint(1, min(3, len(req_ids))))
                allowed_paths = [f"src/module_{t_idx}_{p}.py" for p in range(rng.randint(1, 3))]
                validations = [[f"python3 -m unittest tests/test_{task_id}.py"]]

                tasks.append({
                    "task_id": task_id,
                    "title": f"Task {task_id}",
                    "dependencies": deps,
                    "satisfies": assigned_reqs,
                    "requirements": assigned_reqs,
                    "allowed_paths": allowed_paths,
                    "validations": validations,
                    "prompt": f"Instructions for {task_id} with seed {i}.",
                })

            plan = {
                "plan_id": f"plan-stress-{i:03d}",
                "tasks": tasks,
            }

            # 1. Audit derived requirements
            audit = DerivedRequirementAuditor.audit_requirements(goal_spec, plan=plan)
            self.assertEqual(audit["orphan_count"], 0)

            # 2. Compile task packets for each task in the DAG
            compiled_packets = []
            for tdef in tasks:
                packet = self.compiler.compile_task_packet(
                    goal_id=goal_spec["goal_id"],
                    run_id=f"run-stress-{i:03d}",
                    task_id=tdef["task_id"],
                    attempt_id=1,
                    task_def=tdef,
                    plan=plan,
                    goal_spec=goal_spec,
                    worktree_path=str(REPO_ROOT),
                    allowed_paths=tdef["allowed_paths"],
                    dependencies=tdef["dependencies"],
                    handoffs=[],
                )
                compiled_packets.append(packet)

                # Invariant A: Anchor recall must be 100%
                full_prompt = packet.render_full_prompt()
                recall, missing = calculate_rendered_anchor_recall(packet.required_anchors, full_prompt)
                self.assertEqual(
                    recall,
                    1.0,
                    f"Iteration {i}, task {tdef['task_id']} failed anchor recall. Missing: {missing}",
                )

                # Invariant B: Packet byte size within hard budget
                self.assertLessEqual(
                    packet.packet_bytes,
                    16384,
                    f"Iteration {i}, task {tdef['task_id']} exceeded hard budget: {packet.packet_bytes} bytes",
                )

                # Invariant C: Idempotency (compiling twice yields bit-for-bit identical packet hash)
                packet_repeat = self.compiler.compile_task_packet(
                    goal_id=goal_spec["goal_id"],
                    run_id=f"run-stress-{i:03d}",
                    task_id=tdef["task_id"],
                    attempt_id=1,
                    task_def=tdef,
                    plan=plan,
                    goal_spec=goal_spec,
                    worktree_path=str(REPO_ROOT),
                    allowed_paths=tdef["allowed_paths"],
                    dependencies=tdef["dependencies"],
                    handoffs=[],
                )
                self.assertEqual(packet.packet_hash, packet_repeat.packet_hash)
                self.assertEqual(packet.packet_bytes, packet_repeat.packet_bytes)

            # 3. Test redundancy analysis over compiled prompts in this DAG
            all_rendered = [p.render_full_prompt() for p in compiled_packets]
            red_stats = calculate_context_redundancy(all_rendered)
            self.assertGreaterEqual(red_stats["redundancy_ratio"], 0.0)
            self.assertLessEqual(red_stats["redundancy_ratio"], 1.0)
            self.assertEqual(
                red_stats["total_factory_supplied_bytes"],
                red_stats["unique_content_bytes"] + red_stats["repeated_content_bytes"],
            )


if __name__ == "__main__":
    unittest.main()
