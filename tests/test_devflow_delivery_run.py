"""
Tests for the autonomous delivery evidence run capabilities in devflow_operations.py.

Covers (10 minimum test areas):
1.  Each supported delivery type produces a deterministic task graph
2.  Task graph nodes have valid dependency references and no cycles
3.  Task packets have all required fields
4.  Task packets contain no sensitive / forbidden fields
5.  Valid and invalid task state transitions
6.  QA sign-off required before 'verified'; no 'ready' merge without it
7.  Run summary does not claim success when delegation is not confirmed
8.  --agent-teams and default mode appear correctly in run state and report
9.  Existing target guard and plugin build tests are not broken (run via full suite)
10. generate-task-graph, update-task-status, generate-run-report subcommands work end-to-end
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPS_SCRIPT = REPO_ROOT / "scripts" / "devflow_operations.py"


def _load_ops_module():
    spec = importlib.util.spec_from_file_location("devflow_ops", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_git_repo(path: Path, branch: str = "main", feature_branch=None) -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@devflow.test"],
        check=True, capture_output=True, cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "DevFlow Test"],
        check=True, capture_output=True, cwd=str(path),
    )
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))
    if feature_branch:
        subprocess.run(
            ["git", "checkout", "-b", feature_branch],
            check=True, capture_output=True, cwd=str(path),
        )


def run_ops(args: list, env=None, **kwargs) -> subprocess.CompletedProcess:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(OPS_SCRIPT)] + args,
        capture_output=True,
        text=True,
        env=run_env,
        **kwargs,
    )


def _init_and_run(target: Path, objective: str = "test run") -> str:
    """Init devflow and create a run; return run_id."""
    run_ops(["init-target", "--target", str(target)])
    run_ops(["create-run", "--target", str(target), "--objective", objective])
    project_data = json.loads((target / ".devflow" / "project.json").read_text())
    return project_data["current_run_id"]


def _all_delivery_types():
    mod = _load_ops_module()
    return sorted(mod.SUPPORTED_DELIVERY_TYPES)


# ---------------------------------------------------------------------------
# 1. Each delivery type produces a deterministic task graph
# ---------------------------------------------------------------------------

class DeliveryTypeTaskGraphDeterminismTest(unittest.TestCase):
    """Task graph for each delivery type is deterministic (same input → same output)."""

    def setUp(self):
        self.mod = _load_ops_module()

    def _graph(self, delivery_type: str) -> list:
        return self.mod.generate_task_graph_nodes("RUN-001", delivery_type, "test objective")

    def test_all_delivery_types_produce_tasks(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            self.assertGreater(len(tasks), 0, f"{dt} produced no tasks")

    def test_graphs_are_deterministic(self):
        for dt in _all_delivery_types():
            run1 = self._graph(dt)
            run2 = self._graph(dt)
            self.assertEqual(run1, run2, f"{dt} task graph is not deterministic")

    def test_all_eight_delivery_types_exist(self):
        expected = {
            "new_feature", "ai_rag", "data_dashboard", "bug_resolution",
            "security_response", "release_readiness", "cost_optimization",
            "new_product_discovery",
        }
        self.assertEqual(self.mod.SUPPORTED_DELIVERY_TYPES, expected)

    def test_new_feature_has_contract_task(self):
        tasks = self._graph("new_feature")
        types = [t["task_type"] for t in tasks]
        self.assertIn("contract", types)

    def test_ai_rag_has_eval_task(self):
        tasks = self._graph("ai_rag")
        types = [t["task_type"] for t in tasks]
        self.assertIn("eval", types)

    def test_new_product_discovery_has_approval_task(self):
        tasks = self._graph("new_product_discovery")
        types = [t["task_type"] for t in tasks]
        self.assertIn("approval", types)

    def test_every_graph_ends_with_release_or_approval_task(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            last_type = tasks[-1]["task_type"]
            self.assertIn(
                last_type, ("release", "approval"),
                f"{dt}: last task type should be 'release' or 'approval', got '{last_type}'",
            )

    def test_all_tasks_start_as_planned(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            for task in tasks:
                self.assertEqual(
                    task["status"], "planned",
                    f"{dt} / {task['id']}: status should start as 'planned'",
                )

    def test_all_tasks_delegation_status_planned(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            for task in tasks:
                self.assertEqual(
                    task.get("delegation_status"), "planned",
                    f"{dt} / {task['id']}: delegation_status should start as 'planned'",
                )

    def test_task_ids_scoped_to_run(self):
        tasks = self._graph("new_feature")
        for task in tasks:
            self.assertTrue(
                task["id"].startswith("RUN-001-TASK-"),
                f"Task ID should start with run prefix: {task['id']}",
            )

    def test_dependency_ids_scoped_to_same_run(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            task_ids = {t["id"] for t in tasks}
            for task in tasks:
                for dep_id in task["dependency_ids"]:
                    self.assertIn(
                        dep_id, task_ids,
                        f"{dt}/{task['id']}: dependency '{dep_id}' not in task graph",
                    )


# ---------------------------------------------------------------------------
# 2. Task graph nodes have valid dependency references and no cycles
# ---------------------------------------------------------------------------

class TaskGraphStructureTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def _graph(self, delivery_type: str) -> list:
        return self.mod.generate_task_graph_nodes("RUN-001", delivery_type, "test")

    def _has_cycle(self, tasks: list) -> bool:
        """Return True if the dependency graph has a cycle (DFS coloring)."""
        adj: dict[str, list[str]] = {t["id"]: t["dependency_ids"] for t in tasks}
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {t["id"]: WHITE for t in tasks}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for dep in adj.get(node, []):
                if color.get(dep) == GRAY:
                    return True
                if color.get(dep) == WHITE and dfs(dep):
                    return True
            color[node] = BLACK
            return False

        for task in tasks:
            if color[task["id"]] == WHITE:
                if dfs(task["id"]):
                    return True
        return False

    def test_no_cycles_in_any_graph(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            self.assertFalse(
                self._has_cycle(tasks),
                f"{dt}: task graph contains a dependency cycle",
            )

    def test_all_dependency_ids_reference_existing_tasks(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            task_ids = {t["id"] for t in tasks}
            for task in tasks:
                for dep_id in task["dependency_ids"]:
                    self.assertIn(
                        dep_id, task_ids,
                        f"{dt}/{task['id']}: dep '{dep_id}' not found in graph",
                    )

    def test_first_task_has_no_dependencies(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            self.assertEqual(
                tasks[0]["dependency_ids"], [],
                f"{dt}: first task should have no dependencies",
            )

    def test_task_ids_are_unique(self):
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            ids = [t["id"] for t in tasks]
            self.assertEqual(len(ids), len(set(ids)), f"{dt}: duplicate task IDs found")

    def test_required_task_fields_present(self):
        required = {
            "id", "title", "task_type", "assigned_role",
            "dependency_ids", "acceptance_criteria_ref",
            "qa_expectation", "status", "output_path",
            "expected_evidence_path", "delegation_status",
        }
        for dt in _all_delivery_types():
            tasks = self._graph(dt)
            for task in tasks:
                missing = required - task.keys()
                self.assertEqual(
                    missing, set(),
                    f"{dt}/{task.get('id', '?')}: missing fields: {missing}",
                )


# ---------------------------------------------------------------------------
# 3. Task packets have all required fields
# ---------------------------------------------------------------------------

class TaskPacketRequiredFieldsTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def _packet(self, delivery_type: str, task_index: int = 0) -> dict:
        tasks = self.mod.generate_task_graph_nodes("RUN-001", delivery_type, "test objective")
        return self.mod.generate_task_packet_dict(tasks[task_index], "RUN-001", "test objective")

    def test_required_fields_present(self):
        required = {
            "schema_version", "run_id", "task_id", "objective_summary",
            "assigned_role", "title", "task_type", "context_refs",
            "dependency_ids", "expected_output_paths", "expected_evidence_path",
            "qa_expectation", "prohibitions", "human_approval_points",
            "delegation_status",
        }
        packet = self._packet("new_feature")
        missing = required - packet.keys()
        self.assertEqual(missing, set(), f"Missing required fields: {missing}")

    def test_prohibitions_is_non_empty_list(self):
        packet = self._packet("new_feature")
        self.assertIsInstance(packet["prohibitions"], list)
        self.assertGreater(len(packet["prohibitions"]), 0)

    def test_human_approval_points_is_non_empty_list(self):
        packet = self._packet("new_feature")
        self.assertIsInstance(packet["human_approval_points"], list)
        self.assertGreater(len(packet["human_approval_points"]), 0)

    def test_human_approval_mentions_main_merge(self):
        for dt in _all_delivery_types():
            packet = self._packet(dt)
            combined = " ".join(packet["human_approval_points"]).lower()
            self.assertIn(
                "main", combined,
                f"{dt}: human_approval_points should mention main merge",
            )

    def test_prohibitions_mention_main_branch(self):
        packet = self._packet("new_feature")
        combined = " ".join(packet["prohibitions"]).lower()
        self.assertIn("main", combined)

    def test_prohibitions_mention_secret(self):
        packet = self._packet("new_feature")
        combined = " ".join(packet["prohibitions"]).lower()
        self.assertIn("secret", combined)

    def test_all_delivery_types_produce_valid_packets(self):
        required = {
            "schema_version", "run_id", "task_id", "objective_summary",
            "assigned_role", "title", "task_type", "context_refs",
            "dependency_ids", "expected_output_paths", "expected_evidence_path",
            "qa_expectation", "prohibitions", "human_approval_points",
            "delegation_status",
        }
        for dt in _all_delivery_types():
            tasks = self.mod.generate_task_graph_nodes("RUN-001", dt, "test")
            for task in tasks:
                packet = self.mod.generate_task_packet_dict(task, "RUN-001", "test")
                missing = required - packet.keys()
                self.assertEqual(
                    missing, set(),
                    f"{dt}/{task['id']}: packet missing fields: {missing}",
                )

    def test_packet_schema_version_is_string_1(self):
        packet = self._packet("bug_resolution")
        self.assertEqual(packet["schema_version"], "1")

    def test_packet_run_id_matches(self):
        packet = self._packet("bug_resolution")
        self.assertEqual(packet["run_id"], "RUN-001")

    def test_packet_task_id_matches(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "bug_resolution", "test")
        packet = self.mod.generate_task_packet_dict(tasks[0], "RUN-001", "test")
        self.assertEqual(packet["task_id"], tasks[0]["id"])

    def test_packet_delegation_status_is_planned(self):
        for dt in _all_delivery_types():
            packet = self._packet(dt)
            self.assertEqual(
                packet["delegation_status"], "planned",
                f"{dt}: new packets should have delegation_status='planned'",
            )


# ---------------------------------------------------------------------------
# 4. Task packets contain no sensitive / forbidden fields
# ---------------------------------------------------------------------------

class TaskPacketForbiddenFieldsTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def _packet(self, delivery_type: str, task_index: int = 0) -> dict:
        tasks = self.mod.generate_task_graph_nodes("RUN-001", delivery_type, "test objective")
        return self.mod.generate_task_packet_dict(tasks[task_index], "RUN-001", "test objective")

    def test_no_forbidden_fields_in_any_packet(self):
        forbidden = self.mod.FORBIDDEN_PACKET_FIELDS
        for dt in _all_delivery_types():
            tasks = self.mod.generate_task_graph_nodes("RUN-001", dt, "test")
            for task in tasks:
                packet = self.mod.generate_task_packet_dict(task, "RUN-001", "test")
                bad = set(packet.keys()) & forbidden
                self.assertEqual(
                    bad, set(),
                    f"{dt}/{task['id']}: packet has forbidden fields: {bad}",
                )

    def test_validate_packet_rejects_token_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"token": "secret-value"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_password_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"password": "hunter2"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_secret_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"secret": "abc"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_credential_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"credential": "cred"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_url_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"url": "https://example.com"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_api_key_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"api_key": "sk-abc"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_notebook_content_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"notebook_content": "raw text"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_rejects_raw_content_field(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_task_packet_dict({"raw_content": "some content"})
        self.assertEqual(ctx.exception.code, 10)

    def test_validate_packet_accepts_safe_packet(self):
        safe_packet = {
            "schema_version": "1",
            "run_id": "RUN-001",
            "task_id": "RUN-001-TASK-001",
            "objective_summary": "test",
            "assigned_role": "delivery-lead",
            "title": "Planning",
            "task_type": "planning",
            "context_refs": [".devflow/context/"],
            "dependency_ids": [],
            "expected_output_paths": [".devflow/context/"],
            "expected_evidence_path": ".devflow/context/",
            "qa_expectation": "Task graph hazır",
            "prohibitions": ["main branch'e yazma"],
            "human_approval_points": ["main merge insan onayı gerektirir"],
            "delegation_status": "planned",
        }
        try:
            self.mod.validate_task_packet_dict(safe_packet)
        except SystemExit as e:
            self.fail(f"Safe packet should not be rejected, got exit {e.code}")


# ---------------------------------------------------------------------------
# 5. Valid and invalid task state transitions
# ---------------------------------------------------------------------------

class TaskStateTransitionTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def _ok(self, from_s: str, to_s: str, gates: dict | None = None) -> bool:
        ok, _ = self.mod.validate_task_transition("T-001", from_s, to_s, gates or {})
        return ok

    # Valid transitions
    def test_planned_to_ready(self):
        self.assertTrue(self._ok("planned", "ready"))

    def test_planned_to_failed(self):
        self.assertTrue(self._ok("planned", "failed"))

    def test_ready_to_in_progress(self):
        self.assertTrue(self._ok("ready", "in_progress"))

    def test_ready_to_blocked(self):
        self.assertTrue(self._ok("ready", "blocked"))

    def test_in_progress_to_completed(self):
        self.assertTrue(self._ok("in_progress", "completed"))

    def test_in_progress_to_blocked(self):
        self.assertTrue(self._ok("in_progress", "blocked"))

    def test_in_progress_to_awaiting_human_approval(self):
        self.assertTrue(self._ok("in_progress", "awaiting_human_approval"))

    def test_blocked_to_ready(self):
        self.assertTrue(self._ok("blocked", "ready"))

    def test_failed_to_planned_retry(self):
        self.assertTrue(self._ok("failed", "planned"))

    def test_completed_to_verified_with_qa_sign_off(self):
        self.assertTrue(self._ok("completed", "verified", {"qa_sign_off": True}))

    def test_awaiting_human_to_verified_with_human_approval(self):
        self.assertTrue(self._ok(
            "awaiting_human_approval", "verified",
            {"human_approval": True},
        ))

    # Invalid transitions
    def test_planned_to_in_progress_invalid(self):
        self.assertFalse(self._ok("planned", "in_progress"))

    def test_planned_to_completed_invalid(self):
        self.assertFalse(self._ok("planned", "completed"))

    def test_planned_to_verified_invalid(self):
        self.assertFalse(self._ok("planned", "verified"))

    def test_completed_to_in_progress_invalid(self):
        self.assertFalse(self._ok("completed", "in_progress"))

    def test_verified_to_completed_invalid(self):
        self.assertFalse(self._ok("verified", "completed"))

    def test_verified_to_planned_invalid(self):
        self.assertFalse(self._ok("verified", "planned"))

    def test_failed_to_verified_invalid(self):
        self.assertFalse(self._ok("failed", "verified"))

    # QA gate enforcement
    def test_completed_to_verified_without_qa_blocked(self):
        ok, msg = self.mod.validate_task_transition(
            "T-001", "completed", "verified", {"qa_sign_off": False}
        )
        self.assertFalse(ok)
        self.assertIn("qa_sign_off", msg.lower())

    def test_completed_to_verified_without_qa_gates_empty(self):
        ok, _ = self.mod.validate_task_transition("T-001", "completed", "verified", {})
        self.assertFalse(ok)

    def test_completed_to_awaiting_human_no_qa_needed(self):
        # completed → awaiting_human_approval does NOT require qa_sign_off
        self.assertTrue(self._ok("completed", "awaiting_human_approval", {}))

    # Human approval gate enforcement
    def test_awaiting_human_to_verified_without_human_approval_blocked(self):
        ok, msg = self.mod.validate_task_transition(
            "T-001", "awaiting_human_approval", "verified", {"human_approval": False}
        )
        self.assertFalse(ok)
        self.assertIn("human_approval", msg.lower())

    def test_invalid_from_state_error(self):
        ok, msg = self.mod.validate_task_transition("T-001", "nonexistent", "planned", {})
        self.assertFalse(ok)
        self.assertIn("nonexistent", msg)

    def test_invalid_to_state_error(self):
        ok, msg = self.mod.validate_task_transition("T-001", "planned", "nonexistent", {})
        self.assertFalse(ok)
        self.assertIn("nonexistent", msg)

    def test_all_states_in_constant(self):
        expected = {
            "planned", "ready", "in_progress", "blocked",
            "completed", "verified", "failed", "awaiting_human_approval",
        }
        self.assertEqual(self.mod.TASK_STATES, expected)


# ---------------------------------------------------------------------------
# 6. QA required before verified; no merge-ready without it
# ---------------------------------------------------------------------------

class QAGateEnforcementTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def _make_run_data(self, tasks: list, gates: dict) -> dict:
        return {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "subagents",
            "requested_agent_teams": False,
            "tasks": tasks,
            "approval_gates": gates,
        }

    def _all_tasks_completed(self) -> list:
        """Minimal completed tasks for a 2-task graph."""
        return [
            {"id": "RUN-001-TASK-001", "title": "Planning", "task_type": "planning",
             "assigned_role": "delivery-lead", "dependency_ids": [],
             "status": "completed", "delegation_status": "planned"},
            {"id": "RUN-001-TASK-002", "title": "Release", "task_type": "release",
             "assigned_role": "integration-release", "dependency_ids": ["RUN-001-TASK-001"],
             "status": "completed", "delegation_status": "planned"},
        ]

    def test_no_verified_without_qa_sign_off(self):
        ok, _ = self.mod.validate_task_transition(
            "T", "completed", "verified", {"qa_sign_off": False}
        )
        self.assertFalse(ok, "Should not allow completed→verified without qa_sign_off")

    def test_run_report_not_ready_without_qa(self):
        tasks = self._all_tasks_completed()
        gates = {
            "contract_approved": True,
            "tests_passing": True,
            "security_review_complete": True,
            "qa_sign_off": False,
            "human_approval": False,
        }
        report = self.mod.build_run_report(self._make_run_data(tasks, gates), "RUN-001")
        self.assertNotEqual(
            report["merge_recommendation"], "ready",
            "Merge should not be 'ready' without qa_sign_off",
        )
        self.assertEqual(report["qa_result"], "not_completed")

    def test_run_report_not_ready_without_security_review(self):
        tasks = self._all_tasks_completed()
        gates = {
            "contract_approved": True,
            "tests_passing": True,
            "security_review_complete": False,
            "qa_sign_off": True,
            "human_approval": False,
        }
        report = self.mod.build_run_report(self._make_run_data(tasks, gates), "RUN-001")
        self.assertNotEqual(report["merge_recommendation"], "ready")

    def test_run_report_awaiting_human_when_qa_done_human_not(self):
        tasks = self._all_tasks_completed()
        gates = {
            "contract_approved": True,
            "tests_passing": True,
            "security_review_complete": True,
            "qa_sign_off": True,
            "human_approval": False,
        }
        report = self.mod.build_run_report(self._make_run_data(tasks, gates), "RUN-001")
        self.assertEqual(
            report["merge_recommendation"], "awaiting_human_approval",
            "Should be awaiting_human_approval when qa done but human not yet",
        )

    def test_run_report_ready_when_all_gates_passed(self):
        tasks = [
            {"id": "RUN-001-TASK-001", "title": "Planning", "task_type": "planning",
             "assigned_role": "delivery-lead", "dependency_ids": [],
             "status": "verified", "delegation_status": "planned"},
            {"id": "RUN-001-TASK-002", "title": "Release", "task_type": "release",
             "assigned_role": "integration-release", "dependency_ids": ["RUN-001-TASK-001"],
             "status": "verified", "delegation_status": "planned"},
        ]
        gates = {
            "contract_approved": True,
            "tests_passing": True,
            "security_review_complete": True,
            "qa_sign_off": True,
            "human_approval": True,
        }
        report = self.mod.build_run_report(self._make_run_data(tasks, gates), "RUN-001")
        self.assertEqual(report["merge_recommendation"], "ready")
        self.assertEqual(report["qa_result"], "passed")

    def test_run_report_not_ready_when_tasks_pending(self):
        tasks = [
            {"id": "RUN-001-TASK-001", "title": "Planning", "task_type": "planning",
             "assigned_role": "delivery-lead", "dependency_ids": [],
             "status": "in_progress", "delegation_status": "planned"},
        ]
        gates = {
            "qa_sign_off": True,
            "security_review_complete": True,
            "tests_passing": True,
            "human_approval": True,
        }
        report = self.mod.build_run_report(self._make_run_data(tasks, gates), "RUN-001")
        self.assertNotEqual(
            report["merge_recommendation"], "ready",
            "Should not be ready when tasks are still in progress",
        )

    def test_run_report_not_ready_when_no_tasks(self):
        gates = {
            "qa_sign_off": True,
            "security_review_complete": True,
            "tests_passing": True,
            "human_approval": True,
        }
        report = self.mod.build_run_report(self._make_run_data([], gates), "RUN-001")
        self.assertNotEqual(report["merge_recommendation"], "ready")


# ---------------------------------------------------------------------------
# 7. Run summary does not claim success when delegation not confirmed
# ---------------------------------------------------------------------------

class DelegationHonestyTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def _make_run_data(self, tasks: list) -> dict:
        return {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "subagents",
            "requested_agent_teams": False,
            "tasks": tasks,
            "approval_gates": {},
        }

    def test_delegation_not_confirmed_when_all_planned(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "test")
        run_data = self._make_run_data(tasks)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertFalse(
            report["delegation_evidence"]["any_delegation_confirmed"],
            "delegation_confirmed should be False when all tasks have delegation_status='planned'",
        )

    def test_delegation_boundary_note_mentions_not_confirmed(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "bug_resolution", "test")
        run_data = self._make_run_data(tasks)
        report = self.mod.build_run_report(run_data, "RUN-001")
        note = report["delegation_evidence"]["boundary_note"].lower()
        # Should indicate delegation was NOT confirmed
        self.assertTrue(
            "doğrulanmadı" in note or "planned" in note or "not" in note,
            f"Boundary note should say delegation was not confirmed: {note}",
        )

    def test_delegation_confirmed_when_one_task_confirmed(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "test")
        tasks[0]["delegation_status"] = "confirmed"
        run_data = self._make_run_data(tasks)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertTrue(report["delegation_evidence"]["any_delegation_confirmed"])

    def test_report_includes_human_approval_notes(self):
        tasks = []
        run_data = self._make_run_data(tasks)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertGreater(len(report["human_approval_required"]), 0)
        combined = " ".join(report["human_approval_required"]).lower()
        self.assertIn("main", combined)

    def test_report_merge_not_ready_without_confirmed_delegation_or_gates(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "security_response", "test")
        run_data = self._make_run_data(tasks)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(
            report["merge_recommendation"], "not_ready",
            "Freshly created run with planned tasks should never be 'ready'",
        )

    def test_report_includes_run_id_and_objective(self):
        tasks = []
        run_data = {
            "run_id": "RUN-042",
            "objective": "REQ-007: Add feature X",
            "execution_mode": "subagents",
            "requested_agent_teams": False,
            "tasks": tasks,
            "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-042")
        self.assertEqual(report["run_id"], "RUN-042")
        self.assertEqual(report["objective"], "REQ-007: Add feature X")


# ---------------------------------------------------------------------------
# 8. execution_mode in run state and report
# ---------------------------------------------------------------------------

class ExecutionModeTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def test_subagents_mode_in_report(self):
        run_data = {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "subagents",
            "requested_agent_teams": False,
            "tasks": [],
            "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["execution_mode"], "subagents")
        self.assertFalse(report["requested_agent_teams"])

    def test_agent_teams_mode_in_report(self):
        run_data = {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "agent_teams",
            "requested_agent_teams": True,
            "tasks": [],
            "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["execution_mode"], "agent_teams")
        self.assertTrue(report["requested_agent_teams"])

    def test_report_includes_both_mode_fields(self):
        run_data = {
            "run_id": "RUN-001", "objective": "",
            "execution_mode": "subagents", "requested_agent_teams": False,
            "tasks": [], "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertIn("execution_mode", report)
        self.assertIn("requested_agent_teams", report)


# ---------------------------------------------------------------------------
# 10. End-to-end subcommand tests (generate-task-graph, update-task-status,
#     generate-run-report)
# ---------------------------------------------------------------------------

class GenerateTaskGraphSubcommandTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_run(self, objective: str = "test run") -> str:
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", objective])
        return json.loads(
            (self.target / ".devflow" / "project.json").read_text()
        )["current_run_id"]

    def test_generate_task_graph_succeeds(self):
        run_id = self._init_run()
        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "bug_resolution"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_generate_task_graph_updates_run_state(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "bug_resolution"])
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_data = json.loads(run_file.read_text())
        self.assertGreater(len(run_data["tasks"]), 0)
        self.assertEqual(run_data["task_graph_status"], "generated")
        self.assertEqual(run_data["delivery_type"], "bug_resolution")

    def test_generate_task_graph_creates_task_packets(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "new_feature"])
        packets_dir = self.target / ".devflow" / "task-packets"
        packets = list(packets_dir.glob("*.json"))
        self.assertGreater(len(packets), 0, "Task packets should be created")

    def test_task_packet_files_have_required_fields(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "release_readiness"])
        packets_dir = self.target / ".devflow" / "task-packets"
        for pf in packets_dir.glob("*.json"):
            packet = json.loads(pf.read_text())
            for field in ["run_id", "task_id", "assigned_role", "qa_expectation",
                          "prohibitions", "human_approval_points", "delegation_status"]:
                self.assertIn(field, packet, f"{pf.name}: missing field '{field}'")

    def test_task_packet_no_forbidden_fields(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "ai_rag"])
        mod = _load_ops_module()
        forbidden = mod.FORBIDDEN_PACKET_FIELDS
        packets_dir = self.target / ".devflow" / "task-packets"
        for pf in packets_dir.glob("*.json"):
            packet = json.loads(pf.read_text())
            bad = set(packet.keys()) & forbidden
            self.assertEqual(bad, set(), f"{pf.name}: forbidden fields: {bad}")

    def test_unknown_delivery_type_exit_13(self):
        self._init_run()
        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "completely_unknown_type_xyz"])
        # argparse will reject this before we get to exit 13
        self.assertNotEqual(result.returncode, 0)

    def test_generate_task_graph_on_main_exit_7(self):
        """generate-task-graph should refuse on protected branch."""
        main_target = self.tmpdir / "main_project"
        main_target.mkdir()
        make_git_repo(main_target, branch="main")
        run_ops(["init-target", "--target", str(main_target)])  # will fail on main, but that's ok
        # Directly test by calling with a main-branch repo that has .devflow
        result = run_ops(["generate-task-graph", "--target", str(main_target),
                          "--delivery-type", "bug_resolution"])
        self.assertEqual(result.returncode, 7)

    def test_second_generate_without_force_is_no_op(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "bug_resolution"])
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        tasks_after_first = json.loads(run_file.read_text())["tasks"]

        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "new_feature"])
        # Should succeed (no-op) and not overwrite
        self.assertEqual(result.returncode, 0, result.stderr)
        tasks_after_second = json.loads(run_file.read_text())["tasks"]
        self.assertEqual(tasks_after_first, tasks_after_second)

    def test_force_flag_overwrites_existing_graph(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "bug_resolution"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "new_feature", "--force"])
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_data = json.loads(run_file.read_text())
        self.assertEqual(run_data["delivery_type"], "new_feature")

    def test_new_feature_graph_has_nine_tasks(self):
        run_id = self._init_run()
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "new_feature"])
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_data = json.loads(run_file.read_text())
        self.assertEqual(len(run_data["tasks"]), 9)


class UpdateTaskStatusSubcommandTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test")
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", "test"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "bug_resolution"])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text()
        )
        self.run_id = project_data["current_run_id"]
        run_file = self.target / ".devflow" / "runs" / f"{self.run_id}.json"
        self.first_task_id = json.loads(run_file.read_text())["tasks"][0]["id"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_data(self) -> dict:
        run_file = self.target / ".devflow" / "runs" / f"{self.run_id}.json"
        return json.loads(run_file.read_text())

    def _task_status(self) -> str:
        for t in self._run_data()["tasks"]:
            if t["id"] == self.first_task_id:
                return t["status"]
        return ""

    def test_valid_transition_succeeds(self):
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", self.first_task_id, "--status", "ready"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_valid_transition_updates_run_state(self):
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "ready"])
        self.assertEqual(self._task_status(), "ready")

    def test_invalid_transition_exit_15(self):
        # planned → completed is invalid (must go through ready → in_progress first)
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", self.first_task_id, "--status", "completed"])
        self.assertEqual(result.returncode, 15)

    def test_invalid_transition_does_not_change_state(self):
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "completed"])
        # Status should remain "planned"
        self.assertEqual(self._task_status(), "planned")

    def test_completed_to_verified_without_qa_exit_15(self):
        # Walk task to completed state
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "ready"])
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "in_progress"])
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "completed"])
        # Now try verified without qa_sign_off
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", self.first_task_id, "--status", "verified"])
        self.assertEqual(result.returncode, 15)
        self.assertIn("qa_sign_off", result.stderr)

    def test_completed_to_verified_with_qa_sign_off_succeeds(self):
        # Walk to completed
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "ready"])
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "in_progress"])
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", self.first_task_id, "--status", "completed"])
        # Set qa_sign_off = True manually
        run_file = self.target / ".devflow" / "runs" / f"{self.run_id}.json"
        run_data = json.loads(run_file.read_text())
        run_data["approval_gates"]["qa_sign_off"] = True
        run_file.write_text(json.dumps(run_data, indent=2) + "\n", encoding="utf-8")
        # Now verified should work
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", self.first_task_id, "--status", "verified"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonexistent_task_exit_14(self):
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", "RUN-999-TASK-999", "--status", "ready"])
        self.assertEqual(result.returncode, 14)

    def test_on_protected_main_branch_exit_7(self):
        main_target = self.tmpdir / "main_project"
        main_target.mkdir()
        make_git_repo(main_target, branch="main")
        result = run_ops(["update-task-status", "--target", str(main_target),
                          "--task-id", "RUN-001-TASK-001", "--status", "ready"])
        self.assertEqual(result.returncode, 7)


class GenerateRunReportSubcommandTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test")
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", "REQ-007: test"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "bug_resolution"])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text()
        )
        self.run_id = project_data["current_run_id"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_run_report_succeeds(self):
        result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_file_created(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        self.assertTrue(report_file.exists())

    def test_report_has_required_fields(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        for field in [
            "schema_version", "run_id", "objective", "execution_mode",
            "task_graph_summary", "task_statuses", "approval_gates",
            "qa_result", "human_approval_required", "delegation_evidence",
            "merge_recommendation", "report_generated_at",
        ]:
            self.assertIn(field, report, f"Report missing field: '{field}'")

    def test_report_merge_recommendation_not_ready_for_fresh_run(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        self.assertEqual(
            report["merge_recommendation"], "not_ready",
            "Fresh run should have merge_recommendation='not_ready'",
        )

    def test_report_delegation_not_confirmed_for_fresh_run(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        self.assertFalse(
            report["delegation_evidence"]["any_delegation_confirmed"],
            "Fresh run should have delegation_confirmed=False",
        )

    def test_report_human_approval_required_non_empty(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        self.assertGreater(len(report["human_approval_required"]), 0)

    def test_report_qa_not_completed_for_fresh_run(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        self.assertEqual(report["qa_result"], "not_completed")

    def test_report_execution_mode_correct(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        self.assertEqual(report["execution_mode"], "subagents")

    def test_report_run_id_matches(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        report = json.loads(report_file.read_text())
        self.assertEqual(report["run_id"], self.run_id)

    def test_stdout_mentions_merge_recommendation(self):
        result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("merge_recommendation", result.stdout)

    def test_stdout_mentions_delegation_boundary_note(self):
        result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("NOT", result.stdout)


# ---------------------------------------------------------------------------
# New subcommands appear in script
# ---------------------------------------------------------------------------

class NewSubcommandsInScriptTest(unittest.TestCase):

    def test_generate_task_graph_in_script(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("generate-task-graph", content)

    def test_update_task_status_in_script(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("update-task-status", content)

    def test_generate_run_report_in_script(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("generate-run-report", content)

    def test_new_exit_codes_documented(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for code in ["13", "14", "15"]:
            self.assertIn(code, content, f"Exit code {code} not documented")

    def test_task_states_all_present_in_script(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for state in [
            "planned", "ready", "in_progress", "blocked",
            "completed", "verified", "failed", "awaiting_human_approval",
        ]:
            self.assertIn(state, content, f"Task state '{state}' not in script")

    def test_all_delivery_types_in_script(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for dt in [
            "new_feature", "ai_rag", "data_dashboard", "bug_resolution",
            "security_response", "release_readiness", "cost_optimization",
            "new_product_discovery",
        ]:
            self.assertIn(dt, content, f"Delivery type '{dt}' not in script")


if __name__ == "__main__":
    unittest.main()
