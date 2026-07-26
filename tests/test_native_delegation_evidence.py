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

# PEP 563: without this, the `list | None` annotations below are evaluated at
# def-time and raise TypeError on Python 3.9 — the interpreter macOS ships as
# /usr/bin/python3 — which silently dropped this entire module from
# `unittest discover` while CI (3.12) stayed green.
from __future__ import annotations

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
GUARD_SCRIPT = REPO_ROOT / "scripts" / "devflow_target_guard.py"


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

    def test_observed_delegation_count_is_total_event_count(self):
        # observed_delegation_count counts ALL loaded lifecycle events, not just SubagentStart
        events = [
            {"hook_event": "SubagentStart", "agent_type": "backend-engineer"},
            {"hook_event": "SubagentStart", "agent_type": "qa-automation"},
            {"hook_event": "SubagentStop", "agent_type": "backend-engineer"},
        ]
        run_data = self._make_run_data()
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertEqual(report["delegation_evidence"]["observed_delegation_count"], 3)

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
            "observed_agent_types", "unattributed_event_count",
            "limitation_note", "boundary_note",
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


# ---------------------------------------------------------------------------
# Required coverage: smoke fixture, run-state canonical fields,
# human-approval gate semantics, scorecard fields, sensitive-field leak
# ---------------------------------------------------------------------------

class SmokeFixtureEvidenceTest(unittest.TestCase):
    """
    Test 1: Fixture with 2 target-role start/stop events + 1 unknown stop.
    Verifies observed_delegation_count == 5, native_delegation_observed == True,
    delegation_evidence_status == "observed", and no bire-bir role attribution
    for the unknown event.
    """

    def setUp(self):
        self.mod = _load_ops_module()

    def _smoke_events(self) -> list[dict]:
        return [
            {"hook_event": "SubagentStart", "agent_type": "backend-engineer"},
            {"hook_event": "SubagentStart", "agent_type": "qa-automation"},
            {"hook_event": "SubagentStop", "agent_type": "backend-engineer"},
            {"hook_event": "SubagentStop", "agent_type": "qa-automation"},
            {"hook_event": "SubagentStop", "agent_type": "unknown"},
        ]

    def _run_data(self) -> dict:
        return {
            "run_id": "RUN-001",
            "objective": "smoke",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": [],
            "approval_gates": {},
        }

    def test_smoke_fixture_observed_delegation_count_is_five(self):
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        self.assertEqual(report["delegation_evidence"]["observed_delegation_count"], 5)

    def test_smoke_fixture_native_delegation_observed_true(self):
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        self.assertTrue(report["delegation_evidence"]["native_delegation_observed"])

    def test_smoke_fixture_delegation_evidence_status_observed(self):
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        self.assertEqual(
            report["delegation_evidence"]["delegation_evidence_status"], "observed"
        )

    def test_smoke_fixture_observed_agent_types_excludes_unknown(self):
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        agent_types = report["delegation_evidence"]["observed_agent_types"]
        self.assertIn("backend-engineer", agent_types)
        self.assertIn("qa-automation", agent_types)
        self.assertNotIn("unknown", agent_types)

    def test_smoke_fixture_unattributed_event_count_is_one(self):
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        self.assertEqual(report["delegation_evidence"]["unattributed_event_count"], 1)

    def test_smoke_fixture_no_causal_binding_claimed(self):
        # Scorecard must NOT claim that any task artifact came from a specific session.
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        # limitation_note must acknowledge no causal binding
        note = report["delegation_evidence"]["limitation_note"].lower()
        self.assertIn("causal binding", note)

    def test_smoke_fixture_task_statuses_empty_for_zero_tasks(self):
        report = self.mod.build_run_report(
            self._run_data(), "RUN-001", delegation_events=self._smoke_events()
        )
        # task_statuses should not contain role attribution from events
        self.assertEqual(report["task_statuses"], [])


class CanonicalRunStateFieldsTest(unittest.TestCase):
    """
    Test 4: New run states contain canonical delegation fields;
    legacy requested_agent_teams must NOT be written to new states.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        # Create a feature-branch git repo
        subprocess.run(
            ["git", "init", "-b", "main", str(self.target)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "t@t.test"],
            check=True, capture_output=True, cwd=str(self.target),
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            check=True, capture_output=True, cwd=str(self.target),
        )
        (self.target / "README.md").write_text("t\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"],
            check=True, capture_output=True, cwd=str(self.target),
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            check=True, capture_output=True, cwd=str(self.target),
        )
        subprocess.run(
            ["git", "checkout", "-b", "devflow/test"],
            check=True, capture_output=True, cwd=str(self.target),
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_state(self) -> dict:
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        project = json.loads(
            (self.target / ".devflow" / "project.json").read_text()
        )
        run_id = project["current_run_id"]
        return json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text()
        )

    def test_new_run_state_has_requested_execution_mode(self):
        data = self._run_state()
        self.assertIn("requested_execution_mode", data)

    def test_new_run_state_has_agent_teams_requested(self):
        data = self._run_state()
        self.assertIn("agent_teams_requested", data)

    def test_new_run_state_no_legacy_requested_agent_teams(self):
        data = self._run_state()
        self.assertNotIn("requested_agent_teams", data)

    def test_new_run_state_has_native_delegation_observed(self):
        data = self._run_state()
        self.assertIn("native_delegation_observed", data)
        self.assertFalse(data["native_delegation_observed"])

    def test_new_run_state_has_observed_delegation_count(self):
        data = self._run_state()
        self.assertIn("observed_delegation_count", data)
        self.assertEqual(data["observed_delegation_count"], 0)

    def test_new_run_state_has_delegation_evidence_status(self):
        data = self._run_state()
        self.assertIn("delegation_evidence_status", data)
        self.assertEqual(data["delegation_evidence_status"], "unavailable")


class HumanApprovalGateSemanticTest(unittest.TestCase):
    """
    Tests 5 & 6: human_approval=false → awaiting_human_approval;
                 human_approval=true  → ready_for_human_merge.
    Scorecard separates technical_readiness from merge_recommendation.
    """

    def setUp(self):
        self.mod = _load_ops_module()

    def _completed_tasks(self) -> list:
        return [
            {
                "id": "RUN-001-TASK-001", "title": "Planning",
                "task_type": "planning", "assigned_role": "delivery-lead",
                "dependency_ids": [], "status": "verified",
                "delegation_status": "planned",
            },
            {
                "id": "RUN-001-TASK-002", "title": "Release",
                "task_type": "release", "assigned_role": "integration-release",
                "dependency_ids": ["RUN-001-TASK-001"], "status": "verified",
                "delegation_status": "planned",
            },
        ]

    def _auto_gates_passed(self, human: bool) -> dict:
        return {
            "contract_approved": True,
            "tests_passing": True,
            "security_review_complete": True,
            "qa_sign_off": True,
            "human_approval": human,
        }

    def _run_data(self, human: bool) -> dict:
        return {
            "run_id": "RUN-001", "objective": "test",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": self._completed_tasks(),
            "approval_gates": self._auto_gates_passed(human),
            # Measured QA, not asserted counts — otherwise the run is held at
            # "unverified_evidence" and these human-gate assertions never get
            # to exercise what they are about.
            "qa_evidence": {"source": "executed", "qa_passed": True, "exit_code": 0},
        }

    def _observed_delegation(self) -> list:
        """A SubagentStart event, so the run counts as actually delegated."""
        return [{
            "hook_event": "SubagentStart",
            "lifecycle_state": "started",
            "run_id": "RUN-001",
            "agent_type": "backend-engineer",
        }]

    # Test 5: human approval false
    def test_human_approval_false_merge_recommendation_awaiting(self):
        report = self.mod.build_run_report(
            self._run_data(human=False), "RUN-001",
            delegation_events=self._observed_delegation(),
        )
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")

    def test_human_approval_false_status_awaiting(self):
        report = self.mod.build_run_report(
            self._run_data(human=False), "RUN-001",
            delegation_events=self._observed_delegation(),
        )
        self.assertEqual(report["status"], "awaiting_human_approval")

    def test_human_approval_false_technical_readiness_ready(self):
        # Auto gates pass → technical_readiness is ready even without human approval
        report = self.mod.build_run_report(self._run_data(human=False), "RUN-001")
        self.assertEqual(report["technical_readiness"], "ready")

    # Test 6: human approval true
    def test_human_approval_true_merge_recommendation_ready_for_human_merge(self):
        report = self.mod.build_run_report(
            self._run_data(human=True), "RUN-001",
            delegation_events=self._observed_delegation(),
        )
        self.assertEqual(report["merge_recommendation"], "ready_for_human_merge")

    def test_human_approval_true_status_ready_for_human_merge(self):
        report = self.mod.build_run_report(
            self._run_data(human=True), "RUN-001",
            delegation_events=self._observed_delegation(),
        )
        self.assertEqual(report["status"], "ready_for_human_merge")

    def test_unobserved_delegation_holds_recommendation(self):
        """The gap this exists to close: every auto gate green, no agent ever ran."""
        report = self.mod.build_run_report(self._run_data(human=True), "RUN-001")
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["merge_recommendation"], "unverified_evidence")
        self.assertIn(
            "delegation_unobserved",
            report["evidence_verification"]["unverified_reasons"],
        )

    def test_merge_recommendation_never_plain_ready(self):
        # "ready" must not appear as merge_recommendation (replaced by ready_for_human_merge)
        for human in (True, False):
            report = self.mod.build_run_report(self._run_data(human=human), "RUN-001")
            self.assertNotEqual(report["merge_recommendation"], "ready")

    # Test 7: scorecard field completeness
    def test_scorecard_has_native_event_count(self):
        events = [{"hook_event": "SubagentStart", "agent_type": "backend-engineer"}]
        run_data = self._run_data(human=False)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertIn("observed_delegation_count", report["delegation_evidence"])

    def test_scorecard_has_observed_agent_types(self):
        events = [{"hook_event": "SubagentStart", "agent_type": "backend-engineer"}]
        run_data = self._run_data(human=False)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        self.assertIn("observed_agent_types", report["delegation_evidence"])
        self.assertIn("backend-engineer", report["delegation_evidence"]["observed_agent_types"])

    def test_scorecard_has_evidence_provenance(self):
        report = self.mod.build_run_report(self._run_data(human=False), "RUN-001")
        self.assertIn("evidence_provenance", report)
        provenance = report["evidence_provenance"]
        for key in ["acceptance_criteria", "qa_result", "native_delegation", "human_approval"]:
            self.assertIn(key, provenance)

    def test_scorecard_has_limitation_note(self):
        report = self.mod.build_run_report(self._run_data(human=False), "RUN-001")
        self.assertIn("limitation_note", report["delegation_evidence"])
        self.assertGreater(len(report["delegation_evidence"]["limitation_note"]), 0)

    def test_scorecard_has_technical_readiness(self):
        report = self.mod.build_run_report(self._run_data(human=False), "RUN-001")
        self.assertIn("technical_readiness", report)

    def test_scorecard_has_status(self):
        report = self.mod.build_run_report(self._run_data(human=False), "RUN-001")
        self.assertIn("status", report)

    # Test 8: no sensitive fields in report or state
    def test_no_sensitive_fields_in_report(self):
        report = self.mod.build_run_report(self._run_data(human=False), "RUN-001")
        forbidden = [
            "session_id", "agent_id", "transcript_path", "prompt",
            "last_assistant_message", "token", "secret", "credential",
            "url", "api_key", "password", "raw_task_description",
        ]
        report_str = json.dumps(report)
        for field in forbidden:
            self.assertNotIn(f'"{field}"', report_str,
                             f"Sensitive field '{field}' found in report")

    def test_no_sensitive_fields_in_delegation_evidence(self):
        events = [
            {"hook_event": "SubagentStart", "agent_type": "backend-engineer"},
            {"hook_event": "SubagentStop", "agent_type": "unknown"},
        ]
        run_data = self._run_data(human=False)
        report = self.mod.build_run_report(run_data, "RUN-001", delegation_events=events)
        de_str = json.dumps(report["delegation_evidence"])
        for field in ["session_id", "transcript", "prompt", "token", "credential"]:
            self.assertNotIn(field, de_str,
                             f"Sensitive field '{field}' found in delegation_evidence")


# ---------------------------------------------------------------------------
# Guard helper (reused from guard test pattern)
# ---------------------------------------------------------------------------

def _run_guard(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def _write_payload(path: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": "data"}}


def _edit_payload(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


# ---------------------------------------------------------------------------
# Test 2: task delegation_status "confirmed" ≠ native hook event count
# ---------------------------------------------------------------------------

class TaskDelegationVsHookEventTest(unittest.TestCase):
    """Test 2: observed_delegation_count from hook events, not task delegation_status."""

    def setUp(self):
        self.mod = _load_ops_module()

    def _run_data_with_confirmed_tasks(self) -> dict:
        return {
            "run_id": "RUN-001", "objective": "test",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [
                {"id": "RUN-001-TASK-001", "title": "T1", "task_type": "planning",
                 "assigned_role": "delivery-lead", "dependency_ids": [],
                 "status": "completed", "delegation_status": "confirmed"},
                {"id": "RUN-001-TASK-002", "title": "T2", "task_type": "qa",
                 "assigned_role": "qa-automation", "dependency_ids": [],
                 "status": "completed", "delegation_status": "confirmed"},
            ],
            "approval_gates": {},
        }

    def test_two_confirmed_tasks_no_hook_events_count_is_zero(self):
        report = self.mod.build_run_report(
            self._run_data_with_confirmed_tasks(), "RUN-001", delegation_events=[]
        )
        self.assertEqual(report["delegation_evidence"]["observed_delegation_count"], 0)

    def test_two_confirmed_tasks_no_hook_events_status_not_observed(self):
        report = self.mod.build_run_report(
            self._run_data_with_confirmed_tasks(), "RUN-001", delegation_events=[]
        )
        self.assertEqual(
            report["delegation_evidence"]["delegation_evidence_status"], "not_observed"
        )

    def test_two_confirmed_tasks_native_delegation_observed_false(self):
        report = self.mod.build_run_report(
            self._run_data_with_confirmed_tasks(), "RUN-001", delegation_events=[]
        )
        self.assertFalse(report["delegation_evidence"]["native_delegation_observed"])

    def test_hook_event_count_overrides_task_count(self):
        events = [{"hook_event": "SubagentStart", "agent_type": "backend-engineer"}]
        report = self.mod.build_run_report(
            self._run_data_with_confirmed_tasks(), "RUN-001", delegation_events=events
        )
        # 2 confirmed tasks + 1 hook event → count must be 1 (hook events only)
        self.assertEqual(report["delegation_evidence"]["observed_delegation_count"], 1)


# ---------------------------------------------------------------------------
# Test 3: delegation_evidence_status "confirmed" never produced
# ---------------------------------------------------------------------------

class DelegationStatusEnumTest(unittest.TestCase):
    """Test 3: only observed/not_observed/unavailable are valid status values."""

    CANONICAL_STATUSES = frozenset({"observed", "not_observed", "unavailable"})

    def setUp(self):
        self.mod = _load_ops_module()

    def _base_run_data(self) -> dict:
        return {
            "run_id": "RUN-001", "objective": "test",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": [], "approval_gates": {},
        }

    def test_unavailable_when_events_none(self):
        report = self.mod.build_run_report(self._base_run_data(), "RUN-001", delegation_events=None)
        status = report["delegation_evidence"]["delegation_evidence_status"]
        self.assertEqual(status, "unavailable")
        self.assertIn(status, self.CANONICAL_STATUSES)

    def test_not_observed_when_events_empty(self):
        report = self.mod.build_run_report(self._base_run_data(), "RUN-001", delegation_events=[])
        status = report["delegation_evidence"]["delegation_evidence_status"]
        self.assertEqual(status, "not_observed")
        self.assertIn(status, self.CANONICAL_STATUSES)

    def test_observed_when_subagent_start_present(self):
        events = [{"hook_event": "SubagentStart", "agent_type": "be"}]
        report = self.mod.build_run_report(self._base_run_data(), "RUN-001", delegation_events=events)
        status = report["delegation_evidence"]["delegation_evidence_status"]
        self.assertEqual(status, "observed")
        self.assertIn(status, self.CANONICAL_STATUSES)

    def test_confirmed_status_never_produced_for_any_event_set(self):
        for events in [None, [], [{"hook_event": "SubagentStart", "agent_type": "be"}]]:
            report = self.mod.build_run_report(
                self._base_run_data(), "RUN-001", delegation_events=events
            )
            status = report["delegation_evidence"]["delegation_evidence_status"]
            self.assertNotEqual(status, "confirmed",
                                f"'confirmed' must never be produced (events={events})")

    def test_only_canonical_status_values_emitted(self):
        for events in [None, [], [{"hook_event": "SubagentStart", "agent_type": "be"}]]:
            report = self.mod.build_run_report(
                self._base_run_data(), "RUN-001", delegation_events=events
            )
            status = report["delegation_evidence"]["delegation_evidence_status"]
            self.assertIn(status, self.CANONICAL_STATUSES,
                          f"Non-canonical delegation status: {status!r}")


# ---------------------------------------------------------------------------
# Test 6: Canonical scorecard path is .devflow/reports/, not .devflow/docs/
# Test 9: Authoritative CLI finalization produces canonical state/report
# ---------------------------------------------------------------------------

def _make_cli_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"],
                   check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"],
                   check=True, capture_output=True, cwd=str(path))
    (path / "README.md").write_text("t\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "checkout", "-b", "devflow/test"],
                   check=True, capture_output=True, cwd=str(path))


class CanonicalScorecardPathTest(unittest.TestCase):
    """Test 6: Scorecard written to .devflow/reports/, never .devflow/docs/."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "proj"
        self.target.mkdir()
        _make_cli_git_repo(self.target)
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        project = json.loads((self.target / ".devflow" / "project.json").read_text())
        self.run_id = project["current_run_id"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_run_report_writes_scorecard_to_reports_dir(self):
        result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)
        scorecard = self.target / ".devflow" / "reports" / f"{self.run_id}-scorecard.md"
        self.assertTrue(scorecard.exists(), f"Scorecard not found at {scorecard}")

    def test_scorecard_contains_run_id(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        scorecard = self.target / ".devflow" / "reports" / f"{self.run_id}-scorecard.md"
        content = scorecard.read_text(encoding="utf-8")
        self.assertIn(self.run_id, content)

    def test_scorecard_not_in_docs_dir(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        docs_dir = self.target / ".devflow" / "docs"
        if docs_dir.exists():
            scorecards_in_docs = list(docs_dir.glob("*scorecard*")) + list(docs_dir.glob("*report*"))
            self.assertEqual(
                scorecards_in_docs, [],
                f"Scorecard/report found in .devflow/docs/: {scorecards_in_docs}",
            )

    def test_report_json_also_written_to_reports_dir(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report_json = self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        self.assertTrue(report_json.exists())

    def test_delegation_evidence_status_enum_in_scorecard(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        scorecard = self.target / ".devflow" / "reports" / f"{self.run_id}-scorecard.md"
        content = scorecard.read_text(encoding="utf-8")
        # status must be one of the canonical enum values
        has_canonical = any(s in content for s in ["unavailable", "not_observed", "observed"])
        self.assertTrue(has_canonical, "Scorecard must contain canonical delegation status")
        self.assertNotIn("confirmed", content)


# ---------------------------------------------------------------------------
# Test 7: updated_at >= created_at in run state after finalization
# ---------------------------------------------------------------------------

class UpdatedAtTimestampTest(unittest.TestCase):
    """Test 7: generate-run-report sets updated_at; updated_at >= created_at."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "proj"
        self.target.mkdir()
        _make_cli_git_repo(self.target)
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        project = json.loads((self.target / ".devflow" / "project.json").read_text())
        self.run_id = project["current_run_id"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_state(self) -> dict:
        return json.loads(
            (self.target / ".devflow" / "runs" / f"{self.run_id}.json").read_text()
        )

    def test_run_state_has_no_updated_at_before_finalization(self):
        data = self._run_state()
        # before generate-run-report, updated_at is absent (not set by create-run)
        self.assertNotIn("updated_at", data)

    def test_generate_run_report_sets_updated_at(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        data = self._run_state()
        self.assertIn("updated_at", data)

    def test_updated_at_gte_created_at(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        data = self._run_state()
        created = data.get("created_at", "")
        updated = data.get("updated_at", "")
        self.assertTrue(created, "created_at must be present")
        self.assertTrue(updated, "updated_at must be present")
        self.assertGreaterEqual(updated, created,
                                f"updated_at ({updated}) must be >= created_at ({created})")

    def test_updated_at_is_iso_utc_format(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        data = self._run_state()
        updated = data.get("updated_at", "")
        self.assertRegex(updated, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                         f"updated_at must be ISO UTC: {updated!r}")


# ---------------------------------------------------------------------------
# Test 8: Direct Write/Edit to canonical run/report paths blocked by guard
# ---------------------------------------------------------------------------

class DirectWriteBypassGuardTest(unittest.TestCase):
    """Test 8: Target guard blocks direct Write/Edit to .devflow/runs/ and .devflow/reports/."""

    def test_write_to_devflow_runs_blocked(self):
        result = _run_guard(_write_payload(".devflow/runs/RUN-001.json"))
        self.assertEqual(result.returncode, 2,
                         "Write to .devflow/runs/ must be blocked")

    def test_write_to_devflow_reports_blocked(self):
        result = _run_guard(_write_payload(".devflow/reports/RUN-001-scorecard.md"))
        self.assertEqual(result.returncode, 2,
                         "Write to .devflow/reports/ must be blocked")

    def test_edit_to_devflow_runs_blocked(self):
        result = _run_guard(_edit_payload(".devflow/runs/RUN-001.json"))
        self.assertEqual(result.returncode, 2,
                         "Edit to .devflow/runs/ must be blocked")

    def test_edit_to_devflow_reports_blocked(self):
        result = _run_guard(_edit_payload(".devflow/reports/RUN-001-scorecard.md"))
        self.assertEqual(result.returncode, 2,
                         "Edit to .devflow/reports/ must be blocked")

    def test_absolute_path_devflow_runs_blocked(self):
        result = _run_guard(_write_payload("/Users/user/project/.devflow/runs/RUN-001.json"))
        self.assertEqual(result.returncode, 2)

    def test_absolute_path_devflow_reports_blocked(self):
        result = _run_guard(_write_payload("/tmp/project/.devflow/reports/RUN-001-report.json"))
        self.assertEqual(result.returncode, 2)

    def test_write_to_delegation_events_allowed(self):
        result = _run_guard(_write_payload(".devflow/delegation-events/evt-001.json"))
        self.assertEqual(result.returncode, 0,
                         "Write to .devflow/delegation-events/ must be allowed (recorder)")

    def test_write_to_context_allowed(self):
        result = _run_guard(_write_payload(".devflow/context/context-pack.md"))
        self.assertEqual(result.returncode, 0,
                         "Write to .devflow/context/ must be allowed")

    def test_write_to_task_packets_allowed(self):
        result = _run_guard(_write_payload(".devflow/task-packets/RUN-001-TASK-001.json"))
        self.assertEqual(result.returncode, 0,
                         "Write to .devflow/task-packets/ must be allowed")

    def test_deny_message_does_not_leak_path(self):
        result = _run_guard(_write_payload(".devflow/runs/RUN-001.json"))
        # Deny message must not echo the user-supplied path
        self.assertNotIn("RUN-001", result.stderr)
        self.assertNotIn(".devflow/runs", result.stderr)


# ---------------------------------------------------------------------------
# Test 9: Authoritative CLI finalization produces canonical state and scorecard
# ---------------------------------------------------------------------------

class CLIFinalizationCommandTest(unittest.TestCase):
    """Test 9: generate-run-report is the authoritative finalization path."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "proj"
        self.target.mkdir()
        _make_cli_git_repo(self.target)
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        project = json.loads((self.target / ".devflow" / "project.json").read_text())
        self.run_id = project["current_run_id"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cli_finalization_exits_zero(self):
        result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_finalization_writes_canonical_run_state(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        run_state = json.loads(
            (self.target / ".devflow" / "runs" / f"{self.run_id}.json").read_text()
        )
        self.assertIn("native_delegation_observed", run_state)
        self.assertIn("observed_delegation_count", run_state)
        self.assertIn("delegation_evidence_status", run_state)
        self.assertIn("updated_at", run_state)

    def test_cli_finalization_writes_canonical_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report = json.loads(
            (self.target / ".devflow" / "reports" / f"{self.run_id}-report.json").read_text()
        )
        self.assertIn("technical_readiness", report)
        self.assertIn("merge_recommendation", report)
        self.assertIn("status", report)
        self.assertIn("delegation_evidence", report)

    def test_cli_finalization_delegation_status_enum_valid(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        report = json.loads(
            (self.target / ".devflow" / "reports" / f"{self.run_id}-report.json").read_text()
        )
        status = report["delegation_evidence"]["delegation_evidence_status"]
        self.assertIn(status, {"observed", "not_observed", "unavailable"})
        self.assertNotEqual(status, "confirmed")

    def test_cli_finalization_with_five_events_canonical_projection(self):
        events_dir = self.target / ".devflow" / "delegation-events"
        events_dir.mkdir(parents=True, exist_ok=True)
        smoke_events = [
            {"hook_event": "SubagentStart", "agent_type": "devflow-plugin:backend-engineer"},
            {"hook_event": "SubagentStart", "agent_type": "devflow-plugin:qa-automation"},
            {"hook_event": "SubagentStop", "agent_type": "devflow-plugin:backend-engineer"},
            {"hook_event": "SubagentStop", "agent_type": "devflow-plugin:qa-automation"},
            {"hook_event": "SubagentStop", "agent_type": "unknown"},
        ]
        for i, evt in enumerate(smoke_events):
            record = {
                "schema_version": "1", "evidence_id": f"evt-{i:03d}",
                "timestamp": "2026-06-27T12:00:00Z",
                "run_id": self.run_id, **evt,
                "lifecycle_state": "started" if evt["hook_event"] == "SubagentStart" else "stopped",
                "evidence_source": "native_hook_event",
            }
            (events_dir / f"evt-{i:03d}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
        run_ops(["generate-run-report", "--target", str(self.target)])
        report = json.loads(
            (self.target / ".devflow" / "reports" / f"{self.run_id}-report.json").read_text()
        )
        de = report["delegation_evidence"]
        self.assertEqual(de["observed_delegation_count"], 5)
        self.assertTrue(de["native_delegation_observed"])
        self.assertEqual(de["delegation_evidence_status"], "observed")
        self.assertIn("devflow-plugin:backend-engineer", de["observed_agent_types"])
        self.assertIn("devflow-plugin:qa-automation", de["observed_agent_types"])
        self.assertNotIn("unknown", de["observed_agent_types"])
        self.assertEqual(de["unattributed_event_count"], 1)


# ---------------------------------------------------------------------------
# Test 10: State-report consistency, event validation, artifact tracking
# ---------------------------------------------------------------------------

class RunReportStateConsistencyTest(unittest.TestCase):
    """
    Regression tests for:
    - Wrong-run and malformed events not counted (Test 3)
    - Run state and JSON report carry identical canonical derived values (Test 4)
    - Artifacts added; status not 'created' after finalization (Test 5)
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "proj"
        self.target.mkdir()
        _make_cli_git_repo(self.target)
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        project = json.loads((self.target / ".devflow" / "project.json").read_text())
        self.run_id = project["current_run_id"]
        self.run_file = self.target / ".devflow" / "runs" / f"{self.run_id}.json"
        self.report_file = (
            self.target / ".devflow" / "reports" / f"{self.run_id}-report.json"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_event(self, filename: str, **overrides: object) -> None:
        events_dir = self.target / ".devflow" / "delegation-events"
        events_dir.mkdir(exist_ok=True)
        base: dict = {
            "schema_version": "1",
            "evidence_id": filename.replace(".json", ""),
            "timestamp": "2026-06-27T12:00:00Z",
            "run_id": self.run_id,
            "hook_event": "SubagentStart",
            "lifecycle_state": "started",
            "agent_type": "backend-engineer",
            "evidence_source": "native_hook_event",
        }
        base.update(overrides)
        (events_dir / filename).write_text(json.dumps(base, indent=2), encoding="utf-8")

    def _state(self) -> dict:
        return json.loads(self.run_file.read_text())

    def _report(self) -> dict:
        return json.loads(self.report_file.read_text())

    # --- Test 3: wrong-run and malformed events excluded from count ---

    def test_wrong_run_id_event_not_counted(self):
        self._write_event("evt-good.json")
        self._write_event("evt-wrong.json", run_id="RUN-WRONG-999")
        run_ops(["generate-run-report", "--target", str(self.target)])
        de = self._report()["delegation_evidence"]
        self.assertEqual(de["observed_delegation_count"], 1,
                         "Wrong-run event must not be counted")
        self.assertTrue(de["native_delegation_observed"])

    def test_malformed_hook_event_not_counted(self):
        self._write_event("evt-good.json")
        self._write_event("evt-bad.json",
                          hook_event="NOT_A_HOOK", lifecycle_state="invalid_state")
        run_ops(["generate-run-report", "--target", str(self.target)])
        de = self._report()["delegation_evidence"]
        self.assertEqual(de["observed_delegation_count"], 1,
                         "Malformed hook_event event must not be counted")

    def test_missing_lifecycle_state_event_not_counted(self):
        self._write_event("evt-good.json")
        self._write_event("evt-no-lifecycle.json", lifecycle_state="")
        run_ops(["generate-run-report", "--target", str(self.target)])
        de = self._report()["delegation_evidence"]
        self.assertEqual(de["observed_delegation_count"], 1,
                         "Event with missing lifecycle_state must not be counted")

    # --- Test 4: run state and JSON report carry same canonical derived values ---

    def test_run_state_status_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(self._state()["status"], self._report()["status"])

    def test_run_state_technical_readiness_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(
            self._state()["technical_readiness"], self._report()["technical_readiness"]
        )

    def test_run_state_merge_recommendation_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(
            self._state()["merge_recommendation"], self._report()["merge_recommendation"]
        )

    def test_run_state_delegation_count_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(
            self._state()["observed_delegation_count"],
            self._report()["delegation_evidence"]["observed_delegation_count"],
        )

    def test_run_state_unattributed_count_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(
            self._state()["unattributed_event_count"],
            self._report()["delegation_evidence"]["unattributed_event_count"],
        )

    def test_run_state_security_review_status_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        state = self._state()
        report_sec = self._report().get("security_applicability", {})
        self.assertEqual(
            state.get("security_review_status"),
            report_sec.get("security_review_status"),
        )

    def test_run_state_security_gate_satisfied_matches_report(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        state = self._state()
        report_sec = self._report().get("security_applicability", {})
        self.assertEqual(
            state.get("security_gate_satisfied"),
            report_sec.get("security_gate_satisfied"),
        )

    # --- Test 5: status not 'created', artifacts added, existing fields preserved ---

    def test_status_not_created_after_finalization(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertNotEqual(self._state().get("status"), "created",
                            "Stale 'created' status must be replaced by generate-run-report")

    def test_artifacts_include_report_json_after_finalization(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        artifacts = self._state().get("artifacts", [])
        self.assertTrue(
            any("report.json" in a for a in artifacts),
            f"report.json must be in run state artifacts; got: {artifacts}",
        )

    def test_artifacts_include_scorecard_md_after_finalization(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        artifacts = self._state().get("artifacts", [])
        self.assertTrue(
            any("scorecard.md" in a for a in artifacts),
            f"scorecard.md must be in run state artifacts; got: {artifacts}",
        )

    def test_artifacts_no_duplicates_on_repeated_finalization(self):
        run_ops(["generate-run-report", "--target", str(self.target)])
        run_ops(["generate-run-report", "--target", str(self.target)])
        artifacts = self._state().get("artifacts", [])
        self.assertEqual(
            len(artifacts), len(set(artifacts)),
            "Repeated finalization must not create duplicate artifact entries",
        )

    def test_finalization_preserves_run_id_and_created_at(self):
        state_before = self._state()
        run_ops(["generate-run-report", "--target", str(self.target)])
        state_after = self._state()
        self.assertEqual(state_after["run_id"], state_before["run_id"])
        self.assertEqual(state_after["created_at"], state_before["created_at"])

    def test_five_event_state_and_report_delegation_consistency(self):
        """Five smoke events: run state and report carry identical delegation fields."""
        events_dir = self.target / ".devflow" / "delegation-events"
        events_dir.mkdir(parents=True, exist_ok=True)
        smoke = [
            {"hook_event": "SubagentStart", "lifecycle_state": "started",
             "agent_type": "devflow-plugin:backend-engineer"},
            {"hook_event": "SubagentStart", "lifecycle_state": "started",
             "agent_type": "devflow-plugin:qa-automation"},
            {"hook_event": "SubagentStop", "lifecycle_state": "stopped",
             "agent_type": "devflow-plugin:backend-engineer"},
            {"hook_event": "SubagentStop", "lifecycle_state": "stopped",
             "agent_type": "devflow-plugin:qa-automation"},
            {"hook_event": "SubagentStop", "lifecycle_state": "stopped",
             "agent_type": "unknown"},
        ]
        for i, evt in enumerate(smoke):
            record = {
                "schema_version": "1", "evidence_id": f"s{i:02d}",
                "timestamp": "2026-06-28T00:00:00Z",
                "run_id": self.run_id, **evt,
                "evidence_source": "native_hook_event",
            }
            (events_dir / f"s{i:02d}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
        run_ops(["generate-run-report", "--target", str(self.target)])
        state = self._state()
        report_de = self._report()["delegation_evidence"]
        self.assertEqual(state["observed_delegation_count"], 5)
        self.assertEqual(state["observed_delegation_count"],
                         report_de["observed_delegation_count"])
        self.assertEqual(state["unattributed_event_count"], 1)
        self.assertEqual(state["unattributed_event_count"],
                         report_de["unattributed_event_count"])
        self.assertEqual(state["delegation_evidence_status"], "observed")
        self.assertEqual(state["delegation_evidence_status"],
                         report_de["delegation_evidence_status"])
        self.assertNotEqual(state["status"], "created")

    # --- Unknown-agent run_id fallback: real-world bug scenario ---

    def test_unknown_agent_with_recorder_fallback_run_id_is_counted(self):
        """
        Real-world bug scenario: recorder wrote run_id='unknown' (project.json unreadable
        at hook-fire time).  The event must still be counted as unattributed, not excluded.
        """
        self._write_event("evt-start.json")  # SubagentStart, correct run_id → attributed
        self._write_event(
            "evt-unknown-fallback.json",
            hook_event="SubagentStop",
            lifecycle_state="stopped",
            agent_type="unknown",
            run_id="unknown",  # recorder sentinel fallback
        )
        run_ops(["generate-run-report", "--target", str(self.target)])
        de = self._report()["delegation_evidence"]
        self.assertEqual(de["observed_delegation_count"], 2,
                         "unknown run_id sentinel must not exclude event from count")
        self.assertEqual(de["unattributed_event_count"], 1,
                         "unknown-agent event must increment unattributed count")
        self.assertTrue(de["native_delegation_observed"])
        self.assertNotIn("unknown", de["observed_agent_types"])

    def test_unknown_agent_recorder_fallback_excluded_from_observed_agent_types(self):
        """Unknown agent (recorder fallback run_id) must not appear in observed_agent_types."""
        self._write_event("evt-start.json")
        self._write_event(
            "evt-unknown-fb.json",
            hook_event="SubagentStop",
            lifecycle_state="stopped",
            agent_type="unknown",
            run_id="unknown",
        )
        run_ops(["generate-run-report", "--target", str(self.target)])
        de = self._report()["delegation_evidence"]
        self.assertNotIn("unknown", de["observed_agent_types"])
        self.assertIn("backend-engineer", de["observed_agent_types"])

    def test_wrong_actual_run_id_still_excluded(self):
        """An event with a real mismatched run_id (not the 'unknown' sentinel) is still excluded."""
        self._write_event("evt-start.json")  # correct run_id
        self._write_event("evt-other-run.json", run_id="RUN-WRONG-777")  # real mismatch
        run_ops(["generate-run-report", "--target", str(self.target)])
        de = self._report()["delegation_evidence"]
        self.assertEqual(de["observed_delegation_count"], 1,
                         "Real wrong-run event must still be excluded")

    def test_five_event_fixture_with_unknown_recorder_fallback_run_id(self):
        """
        Five-event fixture where the unknown-agent SubagentStop has run_id='unknown'
        (the recorder's fallback sentinel).  Canonical projection must produce
        observed_delegation_count=5, unattributed_event_count=1.
        """
        events_dir = self.target / ".devflow" / "delegation-events"
        events_dir.mkdir(parents=True, exist_ok=True)
        smoke = [
            {"hook_event": "SubagentStart", "lifecycle_state": "started",
             "agent_type": "devflow-plugin:backend-engineer", "run_id": self.run_id},
            {"hook_event": "SubagentStart", "lifecycle_state": "started",
             "agent_type": "devflow-plugin:qa-automation", "run_id": self.run_id},
            {"hook_event": "SubagentStop", "lifecycle_state": "stopped",
             "agent_type": "devflow-plugin:backend-engineer", "run_id": self.run_id},
            {"hook_event": "SubagentStop", "lifecycle_state": "stopped",
             "agent_type": "devflow-plugin:qa-automation", "run_id": self.run_id},
            # recorder wrote "unknown" because project.json was unreadable at hook time
            {"hook_event": "SubagentStop", "lifecycle_state": "stopped",
             "agent_type": "unknown", "run_id": "unknown"},
        ]
        for i, evt in enumerate(smoke):
            record = {
                "schema_version": "1", "evidence_id": f"fb{i:02d}",
                "timestamp": "2026-06-28T00:00:00Z",
                **evt,
                "evidence_source": "native_hook_event",
            }
            (events_dir / f"fb{i:02d}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
        run_ops(["generate-run-report", "--target", str(self.target)])
        state = self._state()
        report_de = self._report()["delegation_evidence"]
        # Both state and report must show 5 events, 1 unattributed
        self.assertEqual(state["observed_delegation_count"], 5)
        self.assertEqual(state["observed_delegation_count"],
                         report_de["observed_delegation_count"])
        self.assertEqual(state["unattributed_event_count"], 1)
        self.assertEqual(state["unattributed_event_count"],
                         report_de["unattributed_event_count"])
        self.assertEqual(state["delegation_evidence_status"], "observed")
        self.assertIn("devflow-plugin:backend-engineer", report_de["observed_agent_types"])
        self.assertIn("devflow-plugin:qa-automation", report_de["observed_agent_types"])
        self.assertNotIn("unknown", report_de["observed_agent_types"])


if __name__ == "__main__":
    unittest.main()
