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

    def test_all_nine_delivery_types_exist(self):
        expected = {
            "new_feature", "ai_rag", "data_dashboard", "bug_resolution",
            "security_response", "release_readiness", "cost_optimization",
            "new_product_discovery", "backend_utility",
        }
        self.assertEqual(self.mod.SUPPORTED_DELIVERY_TYPES, expected)

    def test_new_feature_has_contract_task(self):
        tasks = self._graph("new_feature")
        types = [t["task_type"] for t in tasks]
        self.assertIn("contract_definition", types)

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
        self.assertEqual(report["merge_recommendation"], "ready_for_human_merge")
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
            "agent_teams_requested": False,
            "tasks": [],
            "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["execution_mode"], "subagents")
        self.assertFalse(report["agent_teams_requested"])

    def test_agent_teams_mode_in_report(self):
        run_data = {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "agent_teams",
            "agent_teams_requested": True,
            "tasks": [],
            "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["execution_mode"], "agent_teams")
        self.assertTrue(report["agent_teams_requested"])

    def test_report_includes_both_mode_fields(self):
        run_data = {
            "run_id": "RUN-001", "objective": "",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [], "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertIn("execution_mode", report)
        self.assertIn("agent_teams_requested", report)


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
            "new_product_discovery", "backend_utility",
        ]:
            self.assertIn(dt, content, f"Delivery type '{dt}' not in script")


# ---------------------------------------------------------------------------
# Task graph immutability, QA evidence recording, and finalization regression
# ---------------------------------------------------------------------------

class TaskGraphImmutabilityTest(unittest.TestCase):
    """
    Regression tests for task graph immutability and authoritative finalization.
    Covers the 10 required areas from the immutability spec:
    1. --force rejected on active run; file unchanged
    2. completed/verified cannot return to planned
    3. report generation does not modify graph
    4. valid transitions accepted; invalid rejected
    5. successful QA recording → auto gates set
    6. no QA or failed exit code → not_ready
    7. backend_utility complete + QA + human=false → awaiting_human_approval
    8. backend_utility complete + QA + human=true → ready_for_human_merge
    9. updated_at >= created_at
    10. all existing tests still pass (ensured by running full suite)
    """

    def setUp(self):
        self.mod = _load_ops_module()
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_and_graph(self, delivery_type: str = "bug_resolution") -> tuple:
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", "test run"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", delivery_type])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text()
        )
        run_id = project_data["current_run_id"]
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        return run_id, run_file

    # --- Test 1: --force rejected on active run ---

    def test_force_rejected_when_task_advanced_beyond_planned(self):
        """--force must fail when any task has progressed past 'planned'."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        first_task_id = json.loads(run_file.read_text())["tasks"][0]["id"]

        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", first_task_id, "--status", "ready"])

        bytes_before = run_file.read_bytes()

        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "new_feature", "--force"])
        self.assertNotEqual(result.returncode, 0,
                            "--force must be rejected on active run")
        self.assertEqual(run_file.read_bytes(), bytes_before,
                         "Failed --force must not modify the run state file")

    def test_force_rejected_returns_exit_code_16(self):
        """--force on active run exits with code 16."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        first_task_id = json.loads(run_file.read_text())["tasks"][0]["id"]

        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", first_task_id, "--status", "ready"])

        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "new_feature", "--force"])
        self.assertEqual(result.returncode, 16)

    def test_force_rejected_when_delegation_events_exist(self):
        """--force must fail when delegation events exist."""
        run_id, run_file = self._init_and_graph("bug_resolution")

        events_dir = self.target / ".devflow" / "delegation-events"
        events_dir.mkdir()
        event = {
            "schema_version": "1", "evidence_id": "evt-001",
            "timestamp": "2026-06-27T12:00:00Z", "run_id": run_id,
            "hook_event": "SubagentStart", "lifecycle_state": "started",
            "agent_type": "backend-engineer", "evidence_source": "native_hook_event",
        }
        (events_dir / "evt-001.json").write_text(json.dumps(event), encoding="utf-8")

        bytes_before = run_file.read_bytes()
        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "new_feature", "--force"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(run_file.read_bytes(), bytes_before)

    def test_force_allowed_when_all_tasks_planned_no_events(self):
        """--force is allowed when all tasks are still 'planned' and no events exist."""
        run_id, run_file = self._init_and_graph("bug_resolution")

        result = run_ops(["generate-task-graph", "--target", str(self.target),
                          "--delivery-type", "new_feature", "--force"])
        self.assertEqual(result.returncode, 0,
                         "--force must succeed on a fresh (all-planned) run with no events")
        run_data = json.loads(run_file.read_text())
        self.assertEqual(run_data["delivery_type"], "new_feature")

    # --- Test 2: completed/verified task cannot return to planned ---

    def test_verified_task_cannot_transition_to_planned(self):
        """verified → planned is a forbidden state transition."""
        ok, _ = self.mod.validate_task_transition("T-001", "verified", "planned", {})
        self.assertFalse(ok, "verified → planned must be invalid")

    def test_completed_task_cannot_transition_to_planned(self):
        """completed → planned is a forbidden state transition."""
        ok, _ = self.mod.validate_task_transition("T-001", "completed", "planned", {})
        self.assertFalse(ok, "completed → planned must be invalid")

    def test_cli_rejects_verified_to_planned(self):
        """CLI update-task-status rejects verified → planned."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        first_task_id = json.loads(run_file.read_text())["tasks"][0]["id"]

        for status in ["ready", "in_progress", "completed"]:
            run_ops(["update-task-status", "--target", str(self.target),
                     "--task-id", first_task_id, "--status", status])
        run_data = json.loads(run_file.read_text())
        run_data["approval_gates"]["qa_sign_off"] = True
        run_file.write_text(json.dumps(run_data, indent=2) + "\n", encoding="utf-8")
        run_ops(["update-task-status", "--target", str(self.target),
                 "--task-id", first_task_id, "--status", "verified"])

        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", first_task_id, "--status", "planned"])
        self.assertEqual(result.returncode, 15,
                         "verified → planned must exit 15")

    # --- Test 3: report generation does not modify graph ---

    def test_report_generation_preserves_task_list(self):
        """generate-run-report must not modify the tasks list in run state."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        tasks_before = json.loads(run_file.read_text())["tasks"]

        run_ops(["generate-run-report", "--target", str(self.target)])

        tasks_after = json.loads(run_file.read_text())["tasks"]
        self.assertEqual(tasks_before, tasks_after,
                         "generate-run-report must not modify task list")

    def test_report_generation_preserves_delivery_type(self):
        """generate-run-report must not change delivery_type in run state."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        dt_before = json.loads(run_file.read_text()).get("delivery_type")

        run_ops(["generate-run-report", "--target", str(self.target)])

        dt_after = json.loads(run_file.read_text()).get("delivery_type")
        self.assertEqual(dt_before, dt_after)

    # --- Test 4: valid/invalid transitions (CLI) ---

    def test_valid_transition_accepted_via_cli(self):
        """Valid task state transition is accepted by CLI."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        first_task_id = json.loads(run_file.read_text())["tasks"][0]["id"]
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", first_task_id, "--status", "ready"])
        self.assertEqual(result.returncode, 0)

    def test_invalid_transition_rejected_via_cli(self):
        """Invalid task state transition (planned → completed) exits 15."""
        run_id, run_file = self._init_and_graph("bug_resolution")
        first_task_id = json.loads(run_file.read_text())["tasks"][0]["id"]
        result = run_ops(["update-task-status", "--target", str(self.target),
                          "--task-id", first_task_id, "--status", "completed"])
        self.assertEqual(result.returncode, 15)

    # --- Tests 5 & 6: record-qa-evidence ---

    def test_record_qa_evidence_success_sets_gates_true(self):
        """Successful QA recording sets tests_passing and qa_sign_off to True."""
        run_id, run_file = self._init_and_graph("backend_utility")

        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--total", "10", "--passed", "10", "--failed", "0",
            "--exit-code", "0", "--evidence-path", "tests/results.xml",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

        gates = json.loads(run_file.read_text()).get("approval_gates", {})
        self.assertTrue(gates.get("tests_passing"), "tests_passing must be True")
        self.assertTrue(gates.get("qa_sign_off"), "qa_sign_off must be True")

    def test_record_qa_evidence_failure_clears_gates(self):
        """Failed QA evidence (exit code != 0) sets gates to False."""
        run_id, run_file = self._init_and_graph("backend_utility")

        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--total", "10", "--passed", "8", "--failed", "2", "--exit-code", "1",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

        gates = json.loads(run_file.read_text()).get("approval_gates", {})
        self.assertFalse(gates.get("tests_passing"), "tests_passing must be False")
        self.assertFalse(gates.get("qa_sign_off"), "qa_sign_off must be False")

    def test_finalization_not_ready_without_qa_evidence(self):
        """Without QA recording, finalization produces not_ready."""
        run_id, run_file = self._init_and_graph("backend_utility")
        run_ops(["generate-run-report", "--target", str(self.target)])

        report = json.loads(
            (self.target / ".devflow" / "reports" / f"{run_id}-report.json").read_text()
        )
        self.assertEqual(report["technical_readiness"], "not_ready")
        self.assertEqual(report["merge_recommendation"], "not_ready")

    def test_finalization_not_ready_when_qa_failed(self):
        """With failed QA evidence (exit code != 0), finalization produces not_ready."""
        run_id, run_file = self._init_and_graph("backend_utility")

        run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--total", "10", "--passed", "5", "--failed", "5", "--exit-code", "1",
        ])
        run_ops(["generate-run-report", "--target", str(self.target)])

        report = json.loads(
            (self.target / ".devflow" / "reports" / f"{run_id}-report.json").read_text()
        )
        self.assertEqual(report["technical_readiness"], "not_ready")
        self.assertEqual(report["merge_recommendation"], "not_ready")

    # --- Tests 7 & 8: backend_utility + QA done → readiness state machine ---

    def _completed_backend_utility_run_data(self, human: bool) -> dict:
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "test")
        for task in tasks:
            task["status"] = "verified"
        return {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "contract_approved": True,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": human,
            },
        }

    def test_backend_utility_complete_human_false_awaiting_human_approval(self):
        """backend_utility all tasks verified + QA passed + human=false → awaiting_human_approval."""
        report = self.mod.build_run_report(
            self._completed_backend_utility_run_data(human=False), "RUN-001"
        )
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")

    def test_backend_utility_complete_human_true_ready_for_human_merge(self):
        """backend_utility all tasks verified + QA passed + human=true → ready_for_human_merge."""
        report = self.mod.build_run_report(
            self._completed_backend_utility_run_data(human=True), "RUN-001"
        )
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "ready_for_human_merge")
        self.assertEqual(report["merge_recommendation"], "ready_for_human_merge")

    # --- Test 9: updated_at >= created_at ---

    def test_updated_at_not_before_created_at_after_finalization(self):
        """updated_at must be >= created_at after generate-run-report."""
        run_id, run_file = self._init_and_graph("backend_utility")
        run_ops(["generate-run-report", "--target", str(self.target)])

        run_data = json.loads(run_file.read_text())
        created_at = run_data.get("created_at", "")
        updated_at = run_data.get("updated_at", "")
        self.assertTrue(created_at, "created_at must be present")
        self.assertTrue(updated_at, "updated_at must be set by generate-run-report")
        self.assertGreaterEqual(
            updated_at, created_at,
            f"updated_at ({updated_at!r}) must be >= created_at ({created_at!r})",
        )


# ---------------------------------------------------------------------------
# Security applicability policy tests
# ---------------------------------------------------------------------------

class SecurityApplicabilityPolicyTest(unittest.TestCase):
    """
    Verifies the three-concept security gate model:
        security_review_required / security_review_status / security_gate_satisfied

    Coverage:
    1. Low-risk backend_utility → not_applicable, gate satisfied, awaiting_human_approval
    2. Each risk signal category → required=True, pending, gate not satisfied, not_ready
    3. Risky run with evidence → completed, gate satisfied, awaiting_human_approval
    4. Low-risk report: not_applicable asserted; no Security Red Team claim
    5. Applicability constants, function, and closed enum correct
    6. Backward-compat: run_data without security_review_required defaults to required=True
    """

    def setUp(self):
        self.mod = _load_ops_module()

    def _verified_tasks(self, delivery_type: str = "backend_utility",
                        objective: str = "Parse CSV files") -> list:
        tasks = self.mod.generate_task_graph_nodes("RUN-001", delivery_type, objective)
        for t in tasks:
            t["status"] = "verified"
        return tasks

    def _make_run(self, objective: str, human: bool,
                  security_evidence: bool = False,
                  security_review_required: bool | None = None,
                  delivery_type: str = "backend_utility") -> dict:
        """Build a complete run_data dict with explicit security applicability."""
        if security_review_required is None:
            sec = self.mod.determine_security_applicability(delivery_type, objective)
        else:
            reason = ("low_risk_local_utility" if not security_review_required
                      else "explicit_security_signal")
            sec = {
                "security_review_required": security_review_required,
                "security_applicability_reason": reason,
            }
        return {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": self._verified_tasks(delivery_type, objective),
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": security_evidence,
                "human_approval": human,
            },
            **sec,
        }

    # --- 1. Low-risk backend_utility ---

    def test_low_risk_security_review_not_required(self):
        result = self.mod.determine_security_applicability(
            "backend_utility", "Parse CSV files and compute summary statistics"
        )
        self.assertFalse(result["security_review_required"])

    def test_low_risk_applicability_reason(self):
        result = self.mod.determine_security_applicability(
            "backend_utility", "Parse CSV files and compute summary statistics"
        )
        self.assertEqual(result["security_applicability_reason"], "low_risk_local_utility")

    def test_low_risk_run_security_review_status_not_applicable(self):
        report = self.mod.build_run_report(
            self._make_run("Parse CSV files", human=False), "RUN-001"
        )
        sec = report["security_applicability"]
        self.assertFalse(sec["security_review_required"])
        self.assertEqual(sec["security_review_status"], "not_applicable")
        self.assertTrue(sec["security_gate_satisfied"])

    def test_low_risk_run_awaiting_human_approval_when_human_false(self):
        """Low-risk backend_utility: QA done + human=False → awaiting_human_approval."""
        report = self.mod.build_run_report(
            self._make_run("Parse CSV files", human=False), "RUN-001"
        )
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")

    def test_low_risk_run_ready_for_human_merge_when_human_true(self):
        report = self.mod.build_run_report(
            self._make_run("Parse CSV files", human=True), "RUN-001"
        )
        self.assertEqual(report["merge_recommendation"], "ready_for_human_merge")

    # --- 2. Risky signals → required=True, pending, gate not satisfied, not_ready ---

    def test_api_surface_signal_required_true(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "Build REST API endpoint for data retrieval"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "api_or_http_surface")

    def test_auth_signal_required_true(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "Add JWT authentication to service"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "auth_or_authorization")

    def test_external_service_signal_required_true(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "Integrate Slack notifications and email alerts"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "external_integration")

    def test_payment_signal_required_true(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "Add Stripe payment billing integration"
        )
        self.assertTrue(r["security_review_required"])

    def test_database_migration_signal_required_true(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "Add database migration to add column to users table"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "database_or_migration")

    def test_deployment_signal_required_true(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "Deploy service to Kubernetes production infrastructure"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "deployment_or_infrastructure")

    def test_risky_run_without_security_evidence_is_not_ready(self):
        """Risky objective + no security evidence → not_ready."""
        run_data = self._make_run(
            "Build REST API endpoint for data retrieval",
            human=False, security_evidence=False,
        )
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertTrue(sec["security_review_required"])
        self.assertEqual(sec["security_review_status"], "pending")
        self.assertFalse(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "not_ready")
        self.assertEqual(report["merge_recommendation"], "not_ready")

    def test_risky_run_auth_signal_status_pending_without_evidence(self):
        run_data = self._make_run(
            "Add JWT authentication to service",
            human=False, security_evidence=False,
        )
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["security_applicability"]["security_review_status"], "pending")
        self.assertFalse(report["security_applicability"]["security_gate_satisfied"])

    # --- 3. Security evidence recorded on risky run → completed, gate satisfied ---

    def test_risky_run_with_security_evidence_gate_satisfied(self):
        run_data = self._make_run(
            "Build REST API endpoint for user data",
            human=False, security_evidence=True,
        )
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertTrue(sec["security_review_required"])
        self.assertEqual(sec["security_review_status"], "completed")
        self.assertTrue(sec["security_gate_satisfied"])

    def test_risky_run_with_security_evidence_awaiting_human(self):
        """Risky run: evidence present + all auto gates pass + human=False → awaiting_human_approval."""
        run_data = self._make_run(
            "Build REST API endpoint for user data",
            human=False, security_evidence=True,
        )
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")

    # --- 4. Low-risk report: not_applicable; no Security Red Team claim ---

    def test_low_risk_provenance_security_review_not_applicable(self):
        run_data = self._make_run("Parse CSV files", human=False)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["evidence_provenance"]["security_review"], "not_applicable")

    def test_low_risk_report_no_security_review_complete_claim(self):
        """Low-risk run: approval_gates.security_review_complete stays False; not overridden."""
        run_data = self._make_run("Parse CSV files", human=False, security_evidence=False)
        report = self.mod.build_run_report(run_data, "RUN-001")
        # Security gate is satisfied via not_applicable path, NOT via security_review_complete
        self.assertFalse(report["approval_gates"].get("security_review_complete", True))
        self.assertEqual(report["security_applicability"]["security_review_status"], "not_applicable")

    def test_low_risk_not_applicable_not_completed(self):
        """not_applicable must never equal 'completed'."""
        run_data = self._make_run("Parse CSV files", human=False)
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec_status = report["security_applicability"]["security_review_status"]
        self.assertEqual(sec_status, "not_applicable")
        self.assertNotEqual(sec_status, "completed")

    # --- 5. Constants, function, and closed enum ---

    def test_determine_security_applicability_exists(self):
        self.assertTrue(callable(self.mod.determine_security_applicability))

    def test_security_applicability_reasons_constant(self):
        self.assertIsInstance(self.mod.SECURITY_APPLICABILITY_REASONS, frozenset)
        self.assertIn("low_risk_local_utility", self.mod.SECURITY_APPLICABILITY_REASONS)
        self.assertIn("api_or_http_surface", self.mod.SECURITY_APPLICABILITY_REASONS)
        self.assertIn("explicit_security_signal", self.mod.SECURITY_APPLICABILITY_REASONS)

    def test_security_triggering_risk_signals_constant(self):
        self.assertIsInstance(self.mod.SECURITY_TRIGGERING_RISK_SIGNALS, frozenset)
        self.assertIn("api_surface", self.mod.SECURITY_TRIGGERING_RISK_SIGNALS)
        self.assertIn("auth", self.mod.SECURITY_TRIGGERING_RISK_SIGNALS)

    def test_mandatory_delivery_types_always_require_security(self):
        """new_feature, ai_rag, security_response, release_readiness always required."""
        for dt in ["new_feature", "ai_rag", "security_response", "release_readiness"]:
            r = self.mod.determine_security_applicability(dt, "low risk with no signals here")
            self.assertTrue(
                r["security_review_required"],
                f"{dt} should always require security review",
            )
            self.assertEqual(r["security_applicability_reason"], "explicit_security_signal")

    def test_reason_is_always_in_closed_enum(self):
        for objective in [
            "Parse CSV files", "Build REST API", "Add JWT authentication",
            "Deploy to Kubernetes", "Add database migration",
        ]:
            for dt in ["backend_utility", "new_feature", "bug_resolution"]:
                r = self.mod.determine_security_applicability(dt, objective)
                self.assertIn(
                    r["security_applicability_reason"],
                    self.mod.SECURITY_APPLICABILITY_REASONS,
                    f"{dt}/{objective!r}: reason not in closed enum",
                )

    def test_security_gate_satisfied_true_when_not_required(self):
        run_data = {
            "run_id": "RUN-001", "objective": "utility",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [],
            "approval_gates": {"security_review_complete": False},
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertTrue(report["security_applicability"]["security_gate_satisfied"])

    def test_security_gate_satisfied_false_when_required_no_evidence(self):
        run_data = {
            "run_id": "RUN-001", "objective": "api endpoint",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [],
            "approval_gates": {"security_review_complete": False},
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertFalse(report["security_applicability"]["security_gate_satisfied"])

    def test_security_applicability_field_in_report(self):
        run_data = {
            "run_id": "RUN-001", "objective": "",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [], "approval_gates": {},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertIn("security_applicability", report)
        sec = report["security_applicability"]
        for key in ["security_review_required", "security_review_status",
                    "security_gate_satisfied", "security_applicability_reason"]:
            self.assertIn(key, sec, f"security_applicability missing key: {key!r}")

    # --- 6. Backward compatibility: missing field defaults to required=True ---

    def test_backward_compat_no_security_review_required_defaults_true(self):
        """Run state without security_review_required → default True (safe)."""
        run_data = {
            "run_id": "RUN-001", "objective": "test",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [], "approval_gates": {"security_review_complete": False},
            # no security_review_required key
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertTrue(report["security_applicability"]["security_review_required"])
        self.assertEqual(report["security_applicability"]["security_review_status"], "pending")
        self.assertFalse(report["security_applicability"]["security_gate_satisfied"])

    def test_backward_compat_security_review_complete_true_satisfies_gate(self):
        """Legacy run data: security_review_complete=True with no security_review_required → gate satisfied."""
        run_data = {
            "run_id": "RUN-001", "objective": "test",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [], "approval_gates": {"security_review_complete": True},
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertTrue(report["security_applicability"]["security_gate_satisfied"])
        self.assertEqual(report["security_applicability"]["security_review_status"], "completed")

    # --- 7. Detector precision and negation regression tests ---

    def test_stdlib_only_no_external_deps_not_required(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "pure Python, stdlib-only, no external dependencies"
        )
        self.assertFalse(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "low_risk_local_utility")

    def test_negated_api_network_file_io_not_required(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "no external API, no network I/O, no file I/O"
        )
        self.assertFalse(r["security_review_required"])

    def test_call_external_api_required_true_external_integration(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "call an external API, no new dependencies"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "external_integration")

    def test_pip_install_overrides_no_external_deps(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "no external dependencies, but pip install package-x"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "dependency_change")

    def test_oauth_positive_overrides_no_api_negation(self):
        r = self.mod.determine_security_applicability(
            "backend_utility", "no API, but add OAuth authentication"
        )
        self.assertTrue(r["security_review_required"])
        self.assertEqual(r["security_applicability_reason"], "auth_or_authorization")

    def test_low_risk_backend_utility_full_canonical_state(self):
        """Low-risk backend_utility + QA evidence + human=False → full expected canonical state."""
        run_data = self._make_run(
            "pure Python, stdlib-only, no external dependencies",
            human=False,
            security_evidence=False,
            delivery_type="backend_utility",
        )
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "not_applicable")
        self.assertTrue(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")


if __name__ == "__main__":
    unittest.main()
