"""
Tests for native delegation evidence and scope discipline.

Required test coverage (10 areas):
1.  SubagentStart / SubagentStop → sanitized evidence record produced correctly
2.  Evidence record contains no forbidden sensitive fields
3.  No native event → report shows delegation as not_observed or unavailable
4.  Native event fixture present → report shows only supported observation
5.  Requested agent-teams and observed native delegation are separate report fields
6.  Work-product verified and role execution observed are separate report fields
7.  backend_utility delivery type omits frontend / API contract / ADR / security report
8.  Auth/API/external-service risk signal in objective detected deterministically
9.  Acceptance criteria provenance shows correctly in report
10. Existing target guard, plugin build, and full test suite pass (run externally)
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
RECORDER_SCRIPT = REPO_ROOT / "scripts" / "devflow_delegation_recorder.py"


def _load_ops_module():
    spec = importlib.util.spec_from_file_location("devflow_ops", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_recorder(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RECORDER_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _make_devflow(tmpdir: Path, run_id: str = "RUN-TEST-001") -> Path:
    devflow = tmpdir / ".devflow"
    devflow.mkdir(parents=True, exist_ok=True)
    project = {"current_run_id": run_id, "run_counter": 1}
    (devflow / "project.json").write_text(
        json.dumps(project, indent=2), encoding="utf-8"
    )
    return devflow


# ---------------------------------------------------------------------------
# 1 & 2: Delegation recorder — evidence record schema and forbidden fields
# ---------------------------------------------------------------------------

class DelegationRecorderTest(unittest.TestCase):
    """Tests 1 and 2: recorder produces correct schema; no forbidden fields."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.devflow = _make_devflow(self.tmpdir)
        self.events_dir = self.devflow / "delegation-events"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _event_files(self) -> list[Path]:
        if not self.events_dir.exists():
            return []
        return sorted(self.events_dir.glob("*.json"))

    def _load_first_event(self) -> dict:
        files = self._event_files()
        self.assertEqual(len(files), 1, "Expected exactly one event file")
        return json.loads(files[0].read_text(encoding="utf-8"))

    # --- Test 1: SubagentStart creates a sanitized evidence record ---

    def test_subagent_start_creates_evidence_file(self):
        result = _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(self._event_files()), 1)

    def test_subagent_stop_creates_evidence_file(self):
        result = _run_recorder({"hook_event_name": "SubagentStop"}, self.tmpdir)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(self._event_files()), 1)

    def test_subagent_start_lifecycle_state_is_started(self):
        _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        record = self._load_first_event()
        self.assertEqual(record["lifecycle_state"], "started")

    def test_subagent_stop_lifecycle_state_is_stopped(self):
        _run_recorder({"hook_event_name": "SubagentStop"}, self.tmpdir)
        record = self._load_first_event()
        self.assertEqual(record["lifecycle_state"], "stopped")

    def test_evidence_record_has_all_required_schema_fields(self):
        _run_recorder({"hook_event_name": "SubagentStart", "agent_type": "delivery-lead"}, self.tmpdir)
        record = self._load_first_event()
        required = {
            "schema_version", "evidence_id", "timestamp",
            "run_id", "hook_event", "lifecycle_state",
            "agent_type", "evidence_source",
        }
        missing = required - record.keys()
        self.assertEqual(missing, set(), f"Missing required fields: {missing}")

    def test_evidence_record_has_exactly_required_fields(self):
        _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        record = self._load_first_event()
        allowed = {
            "schema_version", "evidence_id", "timestamp",
            "run_id", "hook_event", "lifecycle_state",
            "agent_type", "evidence_source",
        }
        extra = record.keys() - allowed
        self.assertEqual(extra, set(), f"Unexpected fields in record: {extra}")

    def test_hook_event_field_matches_input(self):
        _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        record = self._load_first_event()
        self.assertEqual(record["hook_event"], "SubagentStart")

    def test_evidence_source_is_native_hook_event(self):
        _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        record = self._load_first_event()
        self.assertEqual(record["evidence_source"], "native_hook_event")

    def test_run_id_read_from_devflow_project(self):
        _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        record = self._load_first_event()
        self.assertEqual(record["run_id"], "RUN-TEST-001")

    def test_agent_type_captured_from_payload(self):
        _run_recorder(
            {"hook_event_name": "SubagentStart", "agent_type": "backend-engineer"},
            self.tmpdir,
        )
        record = self._load_first_event()
        self.assertEqual(record["agent_type"], "backend-engineer")

    # --- Test 2: No forbidden fields in evidence record ---

    def test_no_forbidden_fields_when_clean_payload(self):
        _run_recorder({"hook_event_name": "SubagentStart"}, self.tmpdir)
        record = self._load_first_event()
        forbidden = [
            "session_id", "agent_id", "transcript_path", "agent_transcript_path",
            "prompt", "input", "output", "last_assistant_message", "task_description",
            "file_content", "token", "secret", "credential", "url", "api_key",
            "password", "message", "content", "text", "log",
        ]
        for field in forbidden:
            self.assertNotIn(field, record, f"Forbidden field '{field}' in evidence record")

    def test_forbidden_fields_in_stdin_not_persisted(self):
        payload = {
            "hook_event_name": "SubagentStart",
            "agent_type": "backend-engineer",
            "session_id": "abc-secret-123",
            "transcript_path": "/var/log/claude/session.log",
            "prompt": "write malicious code",
            "agent_id": "agent-xyz-9999",
            "last_assistant_message": "I did everything",
            "token": "sk-supersecret",
            "credential": "hunter2",
            "url": "https://internal.corp/api",
        }
        _run_recorder(payload, self.tmpdir)
        record = self._load_first_event()
        for forbidden in [
            "session_id", "transcript_path", "prompt", "agent_id",
            "last_assistant_message", "token", "credential", "url",
        ]:
            self.assertNotIn(
                forbidden, record,
                f"Forbidden field '{forbidden}' leaked into evidence record",
            )

    def test_agent_type_with_secret_keyword_sanitized(self):
        payload = {"hook_event_name": "SubagentStart", "agent_type": "my-secret-token-agent"}
        _run_recorder(payload, self.tmpdir)
        record = self._load_first_event()
        self.assertEqual(
            record["agent_type"], "unknown",
            "agent_type containing 'secret' or 'token' should be sanitized to 'unknown'",
        )

    # --- Non-blocking behavior ---

    def test_unknown_event_type_is_non_blocking(self):
        result = _run_recorder({"hook_event_name": "UnknownEvent"}, self.tmpdir)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(self._event_files()), 0)

    def test_empty_stdin_is_non_blocking(self):
        result = subprocess.run(
            [sys.executable, str(RECORDER_SCRIPT)],
            input="",
            capture_output=True,
            text=True,
            cwd=str(self.tmpdir),
        )
        self.assertEqual(result.returncode, 0)

    def test_invalid_json_stdin_is_non_blocking(self):
        result = subprocess.run(
            [sys.executable, str(RECORDER_SCRIPT)],
            input="not valid json {{{",
            capture_output=True,
            text=True,
            cwd=str(self.tmpdir),
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_devflow_dir_is_non_blocking(self):
        empty_dir = self.tmpdir / "no_devflow"
        empty_dir.mkdir()
        result = _run_recorder({"hook_event_name": "SubagentStart"}, empty_dir)
        self.assertEqual(result.returncode, 0)


# ---------------------------------------------------------------------------
# 3, 4, 5, 6, 9: Delegation report fields (requested vs observed separation)
# ---------------------------------------------------------------------------

class DelegationReportFieldsTest(unittest.TestCase):
    """Tests 3-6 and 9: report clearly separates requested / configured / observed."""

    def setUp(self):
        self.mod = _load_ops_module()

    def _make_run_data(
        self,
        agent_teams: bool = False,
        tasks: list | None = None,
        gates: dict | None = None,
    ) -> dict:
        return {
            "run_id": "RUN-001",
            "objective": "test",
            "execution_mode": "agent_teams" if agent_teams else "subagents",
            "requested_agent_teams": agent_teams,
            "tasks": tasks or [],
            "approval_gates": gates or {},
        }

    # --- Test 3: No native event → not_observed or unavailable ---

    def test_no_delegation_events_none_gives_unavailable(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=None)
        status = report["delegation_evidence"]["delegation_evidence_status"]
        self.assertEqual(status, "unavailable")

    def test_empty_delegation_events_list_gives_not_observed(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        status = report["delegation_evidence"]["delegation_evidence_status"]
        self.assertEqual(status, "not_observed")

    def test_no_native_event_native_delegation_observed_is_false(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        self.assertFalse(report["delegation_evidence"]["native_delegation_observed"])

    def test_no_native_event_observed_count_is_zero(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        self.assertEqual(report["delegation_evidence"]["observed_delegation_count"], 0)

    # --- Test 4: Native event fixture present → status "observed" ---

    def test_subagent_start_event_gives_observed_status(self):
        events = [
            {
                "schema_version": "1",
                "evidence_id": "test-uuid-1",
                "timestamp": "2026-06-27T12:00:00Z",
                "run_id": "RUN-001",
                "hook_event": "SubagentStart",
                "lifecycle_state": "started",
                "agent_type": "backend-engineer",
                "evidence_source": "native_hook_event",
            }
        ]
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertEqual(
            report["delegation_evidence"]["delegation_evidence_status"], "observed"
        )

    def test_subagent_start_event_sets_native_delegation_observed_true(self):
        events = [{"hook_event": "SubagentStart", "agent_type": "delivery-lead"}]
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertTrue(report["delegation_evidence"]["native_delegation_observed"])

    def test_observed_delegation_count_matches_subagent_starts(self):
        events = [
            {"hook_event": "SubagentStart", "agent_type": "backend-engineer"},
            {"hook_event": "SubagentStart", "agent_type": "qa-automation"},
            {"hook_event": "SubagentStop", "agent_type": "backend-engineer"},
        ]
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertEqual(report["delegation_evidence"]["observed_delegation_count"], 2)

    def test_only_subagent_stop_does_not_count_as_observed(self):
        events = [{"hook_event": "SubagentStop", "agent_type": "backend-engineer"}]
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertFalse(report["delegation_evidence"]["native_delegation_observed"])
        self.assertEqual(report["delegation_evidence"]["delegation_evidence_status"], "not_observed")

    # --- Test 5: Requested agent-teams ≠ observed native delegation ---

    def test_agent_teams_requested_does_not_imply_native_observed(self):
        run_data = self._make_run_data(agent_teams=True)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        de = report["delegation_evidence"]
        self.assertTrue(de["agent_teams_requested"])
        self.assertFalse(de["native_delegation_observed"])

    def test_requested_execution_mode_reflects_configuration(self):
        run_data = self._make_run_data(agent_teams=True)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        self.assertEqual(
            report["delegation_evidence"]["requested_execution_mode"], "agent_teams"
        )

    def test_subagent_mode_with_no_agent_teams(self):
        run_data = self._make_run_data(agent_teams=False)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        de = report["delegation_evidence"]
        self.assertFalse(de["agent_teams_requested"])
        self.assertEqual(de["requested_execution_mode"], "subagents")

    def test_delegation_fields_all_present(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        de = report["delegation_evidence"]
        for field in [
            "requested_execution_mode", "agent_teams_requested",
            "native_delegation_observed", "observed_delegation_count",
            "delegation_evidence_status", "any_delegation_confirmed",
            "boundary_note",
        ]:
            self.assertIn(field, de, f"delegation_evidence missing field: '{field}'")

    # --- Test 6: Work-product verified ≠ role execution observed ---

    def test_task_verified_does_not_imply_native_observed(self):
        tasks = [
            {
                "id": "RUN-001-TASK-001",
                "title": "Planning",
                "task_type": "planning",
                "assigned_role": "delivery-lead",
                "dependency_ids": [],
                "status": "verified",
                "delegation_status": "planned",
            }
        ]
        run_data = self._make_run_data(tasks=tasks)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        de = report["delegation_evidence"]
        self.assertFalse(de["native_delegation_observed"])
        self.assertEqual(de["delegation_evidence_status"], "not_observed")

    def test_task_verified_status_preserved_separately(self):
        tasks = [
            {
                "id": "RUN-001-TASK-001",
                "title": "Planning",
                "task_type": "planning",
                "assigned_role": "delivery-lead",
                "dependency_ids": [],
                "status": "verified",
                "delegation_status": "planned",
            }
        ]
        run_data = self._make_run_data(tasks=tasks)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        task_status = next(
            t for t in report["task_statuses"] if t["id"] == "RUN-001-TASK-001"
        )
        self.assertEqual(task_status["status"], "verified")
        self.assertEqual(task_status["delegation_status"], "planned")

    def test_delegation_confirmed_flag_independent_of_task_status(self):
        tasks = [
            {
                "id": "RUN-001-TASK-001",
                "title": "Planning",
                "task_type": "planning",
                "assigned_role": "delivery-lead",
                "dependency_ids": [],
                "status": "completed",
                "delegation_status": "planned",
            }
        ]
        run_data = self._make_run_data(tasks=tasks)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        self.assertFalse(report["delegation_evidence"]["any_delegation_confirmed"])

    # --- Test 9: Acceptance criteria provenance ---

    def test_acceptance_criteria_provenance_is_generated_in_run(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001")
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("acceptance_criteria"), "generated_in_run")

    def test_human_approval_provenance_unavailable_without_gate(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001")
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("human_approval"), "unavailable")

    def test_human_approval_provenance_human_review_with_gate(self):
        run_data = self._make_run_data(gates={"human_approval": True})
        report = self.mod.build_run_report(run_data, "RUN-001")
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("human_approval"), "human_review")

    def test_security_review_provenance_unavailable_without_gate(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001")
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("security_review"), "unavailable")

    def test_security_review_provenance_generated_in_run_with_gate(self):
        run_data = self._make_run_data(gates={"security_review_complete": True})
        report = self.mod.build_run_report(run_data, "RUN-001")
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("security_review"), "generated_in_run")

    def test_native_delegation_provenance_unavailable_without_event(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=[])
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("native_delegation"), "unavailable")

    def test_native_delegation_provenance_native_hook_event_with_start(self):
        events = [{"hook_event": "SubagentStart", "agent_type": "backend-engineer"}]
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        provenance = report.get("evidence_provenance", {})
        self.assertEqual(provenance.get("native_delegation"), "native_hook_event")

    def test_evidence_provenance_field_present_in_report(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertIn("evidence_provenance", report)

    def test_evidence_provenance_has_all_categories(self):
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001")
        provenance = report["evidence_provenance"]
        for key in [
            "acceptance_criteria", "qa_result", "security_review",
            "human_approval", "native_delegation",
        ]:
            self.assertIn(key, provenance, f"evidence_provenance missing key: '{key}'")


# ---------------------------------------------------------------------------
# 7: backend_utility delivery type omits unnecessary tasks
# ---------------------------------------------------------------------------

class BackendUtilityDeliveryTypeTest(unittest.TestCase):
    """Test 7: backend_utility has minimal tasks; no frontend/contract/ADR/security."""

    def setUp(self):
        self.mod = _load_ops_module()

    def _graph(self) -> list:
        return self.mod.generate_task_graph_nodes(
            "RUN-001", "backend_utility", "Refactor CSV parsing utility"
        )

    def test_backend_utility_in_supported_types(self):
        self.assertIn("backend_utility", self.mod.SUPPORTED_DELIVERY_TYPES)

    def test_backend_utility_produces_tasks(self):
        tasks = self._graph()
        self.assertGreater(len(tasks), 0)

    def test_backend_utility_has_exactly_four_tasks(self):
        tasks = self._graph()
        self.assertEqual(
            len(tasks), 4,
            f"Expected 4 tasks, got {len(tasks)}: {[t['title'] for t in tasks]}",
        )

    def test_backend_utility_no_frontend_engineer_role(self):
        tasks = self._graph()
        roles = [t["assigned_role"] for t in tasks]
        self.assertNotIn("frontend-engineer", roles)

    def test_backend_utility_no_contract_task_type(self):
        tasks = self._graph()
        task_types = [t["task_type"] for t in tasks]
        self.assertNotIn("contract", task_types)

    def test_backend_utility_no_contract_broker_role(self):
        tasks = self._graph()
        roles = [t["assigned_role"] for t in tasks]
        self.assertNotIn("contract-broker", roles)

    def test_backend_utility_no_adr_via_solution_architect(self):
        tasks = self._graph()
        roles = [t["assigned_role"] for t in tasks]
        self.assertNotIn("solution-architect", roles)

    def test_backend_utility_no_standalone_security_review_task(self):
        tasks = self._graph()
        task_types = [t["task_type"] for t in tasks]
        self.assertNotIn("security_review", task_types)

    def test_backend_utility_has_planning_task(self):
        tasks = self._graph()
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("planning", task_types)

    def test_backend_utility_has_implementation_task(self):
        tasks = self._graph()
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("implementation", task_types)

    def test_backend_utility_has_qa_task(self):
        tasks = self._graph()
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("qa", task_types)

    def test_backend_utility_has_release_task(self):
        tasks = self._graph()
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("release", task_types)

    def test_backend_utility_graph_is_deterministic(self):
        tasks1 = self._graph()
        tasks2 = self._graph()
        self.assertEqual(tasks1, tasks2)

    def test_backend_utility_task_ids_scoped_to_run(self):
        tasks = self._graph()
        for t in tasks:
            self.assertTrue(
                t["id"].startswith("RUN-001-TASK-"),
                f"Task ID not scoped to run: {t['id']}",
            )

    def test_backend_utility_no_cycles(self):
        tasks = self._graph()
        adj = {t["id"]: t["dependency_ids"] for t in tasks}
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {t["id"]: WHITE for t in tasks}

        def dfs(node):
            color[node] = GRAY
            for dep in adj.get(node, []):
                if color.get(dep) == GRAY:
                    return True
                if color.get(dep) == WHITE and dfs(dep):
                    return True
            color[node] = BLACK
            return False

        has_cycle = any(
            dfs(t["id"]) for t in tasks if color[t["id"]] == WHITE
        )
        self.assertFalse(has_cycle, "backend_utility task graph has a cycle")


# ---------------------------------------------------------------------------
# 8: Objective risk signal detection — deterministic keyword matching
# ---------------------------------------------------------------------------

class ObjectiveRiskSignalTest(unittest.TestCase):
    """Test 8: detect_objective_risk_signals is deterministic and testable."""

    def setUp(self):
        self.mod = _load_ops_module()

    def _signals(self, objective: str) -> frozenset:
        return self.mod.detect_objective_risk_signals(objective)

    def test_function_exists(self):
        self.assertTrue(callable(self.mod.detect_objective_risk_signals))

    def test_objective_risk_signals_constant_exists(self):
        self.assertIsInstance(self.mod.OBJECTIVE_RISK_SIGNALS, dict)
        self.assertGreater(len(self.mod.OBJECTIVE_RISK_SIGNALS), 0)

    def test_pure_python_csv_utility_no_signals(self):
        signals = self._signals("Parse CSV files and compute summary statistics")
        self.assertNotIn("api_surface", signals)
        self.assertNotIn("auth", signals)
        self.assertNotIn("payment", signals)
        self.assertNotIn("external_service", signals)
        self.assertNotIn("deployment", signals)
        self.assertNotIn("schema_migration", signals)
        self.assertNotIn("frontend", signals)

    def test_rest_api_endpoint_detects_api_surface(self):
        signals = self._signals("Build REST API endpoint for user data retrieval")
        self.assertIn("api_surface", signals)

    def test_jwt_authentication_detects_auth(self):
        signals = self._signals("Add JWT authentication and authorization to service")
        self.assertIn("auth", signals)

    def test_oauth_login_detects_auth(self):
        signals = self._signals("Implement OAuth login and session management")
        self.assertIn("auth", signals)

    def test_stripe_payment_detects_payment(self):
        signals = self._signals("Integrate Stripe payment and subscription billing")
        self.assertIn("payment", signals)

    def test_slack_notification_detects_external_service(self):
        signals = self._signals("Send Slack notifications and integrate email alerts")
        self.assertIn("external_service", signals)

    def test_kubernetes_deploy_detects_deployment(self):
        signals = self._signals("Deploy service to Kubernetes cluster on AWS")
        self.assertIn("deployment", signals)

    def test_database_migration_detects_schema_migration(self):
        signals = self._signals("Add database migration to add new column to users table")
        self.assertIn("schema_migration", signals)

    def test_react_component_detects_frontend(self):
        signals = self._signals("Build React component and HTML form for user input")
        self.assertIn("frontend", signals)

    def test_detection_is_case_insensitive(self):
        lower = self._signals("build rest api endpoint")
        upper = self._signals("BUILD REST API ENDPOINT")
        mixed = self._signals("Build REST Api Endpoint")
        self.assertEqual(lower, upper)
        self.assertEqual(upper, mixed)

    def test_detection_is_deterministic(self):
        objective = "Build REST API with JWT auth and Stripe payment"
        s1 = self._signals(objective)
        s2 = self._signals(objective)
        self.assertEqual(s1, s2)

    def test_empty_objective_no_signals(self):
        signals = self._signals("")
        self.assertEqual(signals, frozenset())

    def test_multiple_signals_detected_together(self):
        signals = self._signals(
            "Build REST API with JWT auth, Stripe payment, and Slack notification"
        )
        self.assertIn("api_surface", signals)
        self.assertIn("auth", signals)
        self.assertIn("payment", signals)
        self.assertIn("external_service", signals)

    def test_returns_frozenset(self):
        signals = self._signals("test objective")
        self.assertIsInstance(signals, frozenset)


# ---------------------------------------------------------------------------
# load_delegation_events integration
# ---------------------------------------------------------------------------

class LoadDelegationEventsTest(unittest.TestCase):
    """Verify load_delegation_events correctly reads from .devflow/delegation-events/."""

    def setUp(self):
        self.mod = _load_ops_module()
        self.tmpdir = Path(tempfile.mkdtemp())
        self.devflow = self.tmpdir / ".devflow"
        self.devflow.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_event(self, hook_event: str, evidence_id: str = "test-id") -> None:
        events_dir = self.devflow / "delegation-events"
        events_dir.mkdir(exist_ok=True)
        record = {
            "schema_version": "1",
            "evidence_id": evidence_id,
            "timestamp": "2026-06-27T12:00:00Z",
            "run_id": "RUN-001",
            "hook_event": hook_event,
            "lifecycle_state": "started" if hook_event == "SubagentStart" else "stopped",
            "agent_type": "backend-engineer",
            "evidence_source": "native_hook_event",
        }
        (events_dir / f"{evidence_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )

    def test_no_events_dir_returns_unavailable(self):
        events, status = self.mod.load_delegation_events(self.devflow)
        self.assertEqual(status, "unavailable")
        self.assertEqual(events, [])

    def test_empty_events_dir_returns_not_observed(self):
        (self.devflow / "delegation-events").mkdir()
        events, status = self.mod.load_delegation_events(self.devflow)
        self.assertEqual(status, "not_observed")
        self.assertEqual(events, [])

    def test_subagent_start_event_returns_observed(self):
        self._write_event("SubagentStart", "evt-001")
        events, status = self.mod.load_delegation_events(self.devflow)
        self.assertEqual(status, "observed")
        self.assertEqual(len(events), 1)

    def test_only_subagent_stop_returns_not_observed(self):
        self._write_event("SubagentStop", "evt-002")
        events, status = self.mod.load_delegation_events(self.devflow)
        self.assertEqual(status, "not_observed")

    def test_multiple_subagent_starts_counted(self):
        self._write_event("SubagentStart", "evt-003")
        self._write_event("SubagentStart", "evt-004")
        events, status = self.mod.load_delegation_events(self.devflow)
        self.assertEqual(status, "observed")
        self.assertEqual(len(events), 2)


# ---------------------------------------------------------------------------
# generate-run-report end-to-end with delegation events
# ---------------------------------------------------------------------------

def make_git_repo(path: Path, feature_branch: str = "devflow/test") -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
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
    subprocess.run(
        ["git", "checkout", "-b", feature_branch],
        check=True, capture_output=True, cwd=str(path),
    )


def run_ops(args: list, env=None) -> subprocess.CompletedProcess:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(OPS_SCRIPT)] + args,
        capture_output=True, text=True, env=run_env,
    )


class GenerateRunReportDelegationTest(unittest.TestCase):
    """End-to-end test: generate-run-report with and without delegation events."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target)
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", "utility run"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "backend_utility"])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text()
        )
        self.run_id = project_data["current_run_id"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _report(self) -> dict:
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_file = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        return json.loads(report_file.read_text())

    def test_report_without_events_dir_has_unavailable_status(self):
        report = self._report()
        self.assertEqual(
            report["delegation_evidence"]["delegation_evidence_status"], "unavailable"
        )

    def test_report_with_empty_events_dir_has_not_observed_status(self):
        (self.target / ".devflow" / "delegation-events").mkdir()
        report = self._report()
        self.assertEqual(
            report["delegation_evidence"]["delegation_evidence_status"], "not_observed"
        )

    def test_report_with_subagent_start_event_has_observed_status(self):
        events_dir = self.target / ".devflow" / "delegation-events"
        events_dir.mkdir()
        event = {
            "schema_version": "1",
            "evidence_id": "e2e-test-id",
            "timestamp": "2026-06-27T12:00:00Z",
            "run_id": self.run_id,
            "hook_event": "SubagentStart",
            "lifecycle_state": "started",
            "agent_type": "backend-engineer",
            "evidence_source": "native_hook_event",
        }
        (events_dir / "e2e-test-id.json").write_text(
            json.dumps(event, indent=2), encoding="utf-8"
        )
        report = self._report()
        self.assertEqual(
            report["delegation_evidence"]["delegation_evidence_status"], "observed"
        )
        self.assertTrue(report["delegation_evidence"]["native_delegation_observed"])

    def test_report_has_evidence_provenance(self):
        report = self._report()
        self.assertIn("evidence_provenance", report)
        self.assertEqual(
            report["evidence_provenance"]["acceptance_criteria"], "generated_in_run"
        )

    def test_backend_utility_report_has_four_tasks(self):
        report = self._report()
        self.assertEqual(report["task_graph_summary"]["total"], 4)


if __name__ == "__main__":
    unittest.main()
